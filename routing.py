"""Select a model tier, run bounded text agents and record every provider attempt."""
import re
import time
import httpx
from cryptography.fernet import InvalidToken

from storage import TIERS
from local_models import BASE, local_chat
from playground import validate_replacement
from health import auth_headers

class RelayError(Exception):
    def __init__(self, message, status=502):
        super().__init__(message)
        self.status = status
        self.run = None

def choose(messages, requested):
    if requested in TIERS:
        return requested, "Caller selected this tier."
    last = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
    size = sum(len(m["content"]) for m in messages)
    if size > 4000 or re.search(r"\b(architect(?:ure)?|trade.?offs?|multi.step|root cause|migration plan)\b", last, re.I):
        return "strong", "Long context or a planning and reasoning cue."
    if size < 500 and not re.search(r"\b(compare|explain|debug|design|implement|analyse|analyze)\b", last, re.I):
        return "fast", "Short request with no deeper reasoning cue."
    return "balanced", "Moderate context or an explanation task."

def elapsed(start):
    return round((time.monotonic()-start)*1000)

def complete(db, client, run, stage, messages, tier, candidates, options):
    eligible = [p for p in candidates if p.get("state") not in ("rejected","denied","missing")]
    now = time.time()
    ranked = sorted(eligible, key=lambda p: (
                                                p.get("state") in ("limited","error") and now-(p.get("checked_at") or 0)<300,
                                                abs(TIERS.index(tier)-TIERS.index(p["tier"])),
                                                -TIERS.index(p["tier"])))
    for p in ranked[:3]:
        start = time.monotonic()
        try:
            r = client.post(p["base"]+"/chat/completions", headers=auth_headers(db,p),
                            json={"model":p["model"],"messages":messages,**options})
            if r.status_code != 200:
                status = r.status_code
                why = {401:"credential rejected",403:"access denied",404:"model or endpoint missing",
                       429:"rate limited"}.get(status,"provider error")
                outcome = f"HTTP {status} · {why}"
                transient = status in (401,403,404,408,429) or status >= 500
                if not transient:
                    db.attempt(run,stage,p,outcome,elapsed(start),None)
                    raise RelayError(outcome, 422 if status == 400 else 502)
            else:
                body = r.json()
                answer = body["choices"][0]["message"]["content"]
                if not isinstance(answer,str) or not answer.strip():
                    raise ValueError("Empty text")
                usage = body.get("usage") or {}
                tokens = usage.get("total_tokens") if isinstance(usage,dict) else None
                db.attempt(run,stage,p,"ok",elapsed(start),tokens,usage if isinstance(usage,dict) else None)
                return body
        except InvalidToken:
            outcome = "saved credential could not be read"
        except httpx.TimeoutException:
            outcome = "provider timed out"
        except httpx.RequestError:
            outcome = "provider unreachable"
        except (ValueError,KeyError,IndexError,TypeError):
            outcome = "invalid provider response"
        db.attempt(run,stage,p,outcome,elapsed(start),None)
    raise RelayError("No provider completed this request. Check provider health and the request trace." if candidates else "Add a provider first.",503)

def checked_file(body, target):
    choice = body["choices"][0]
    if choice.get("finish_reason") != "stop":
        raise ValueError("The replacement was truncated.")
    content = choice["message"]["content"]
    fence = re.fullmatch(r"`{3}[^\n]*\n([\s\S]*?)\n`{3}\s*", content)
    if fence:
        content = fence[1]
    check = validate_replacement(target, content)
    choice["message"]["content"] = content
    return check

def execute(db, client, messages, requested, mode, options, target=None):
    pinned = requested.removeprefix("local/") if requested.startswith("local/") else None
    tier, reason = ("balanced", "Pinned local model; local inference only.") if pinned else choose(messages, requested)
    run = db.start(tier,reason,mode)
    start = time.monotonic()
    status = "failed"
    try:
        candidates = db.providers()
        if pinned:
            try:
                eligible = local_chat(client, pinned)
            except (httpx.HTTPError, ValueError):
                eligible = False
            if not eligible:
                raise RelayError("Local model unavailable or incompatible. Check Models.", 422)
            candidates = [{"label":"Local Ollama","base":BASE+"/v1","model":pinned,"tier":tier,"secret":b""}]
        if target is not None:
            prompt = list(messages)
            for stage in ("editor", "repair"):
                body = complete(db,client,run,stage,prompt,tier,candidates,options)
                try:
                    body["file_check"] = checked_file(body,target)
                    db.attempt(run,"file check",candidates[0],"ok",0,None)
                    break
                except ValueError as error:
                    detail = str(error)
                    db.attempt(run,"file check",candidates[0],detail,0,None)
                    if stage == "repair":
                        raise RelayError("File failed verification after one repair attempt. Original is intact.",422)
                    prompt = [*messages,{"role":"assistant","content":body["choices"][0]["message"]["content"]},
                              {"role":"user","content":f"Check failed: {detail}. Return one complete corrected file."}]
        elif mode == "task" and tier == "strong":
            plan = complete(db,client,run,"planner",[
                {"role":"system","content":"Plan the requested text task in at most four concise steps."},
                *messages], "balanced",candidates,{"max_tokens":180})
            draft = complete(db,client,run,"writer",[
                {"role":"system","content":"Produce the deliverable. Use this suggested plan as context."},
                *messages,{"role":"assistant","content":plan["choices"][0]["message"]["content"]},
                {"role":"user","content":"Carry out the plan and write the answer."}],tier,candidates,options)
            body = complete(db,client,run,"reviewer",[
                {"role":"system","content":"Review the draft against the original request. Return a corrected final answer."},
                *messages,{"role":"assistant","content":draft["choices"][0]["message"]["content"]},
                {"role":"user","content":"Return the reviewed deliverable."}],tier,candidates,options)
        else:
            body = complete(db,client,run,"writer",messages,tier,candidates,options)
        status = "ok"
        return run, body
    except RelayError as exc:
        exc.run = run
        raise
    finally:
        db.finish(run,status,elapsed(start))
