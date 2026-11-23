"""Run live local-model smoke checks against the running Model Relay app."""
import argparse
import ast
import json
import re
from urllib.request import Request, urlopen

BASE = "http://127.0.0.1:8520"
ADMIN = {"X-Relay-Admin": "dashboard", "Content-Type": "application/json"}
EXPECTED = ast.dump(ast.parse("def total(prices):\n    return sum(prices)\n"))


def post(path, data, headers=ADMIN):
    request = Request(BASE+path,json.dumps(data).encode(),headers)
    with urlopen(request,timeout=255) as reply:
        return json.load(reply),reply.headers.get("X-Request-ID")


def run_model(name):
    model = "local/" + name
    body, chat_id = post("/admin/playground", {
        "model": model,
        "messages": [{"role":"user","content":"What is 2 + 2? Reply with just the number."}],
        "max_tokens": 32,
    })
    answer = body["choices"][0]["message"]["content"]
    if not answer.strip() or not chat_id:
        raise ValueError("Chat did not produce text and a request trace.")

    body, edit_id = post("/admin/playground", {
        "model": model,
        "messages": [
            {"role":"user","content":"Imported file total.py\n\ndef total(prices):\n    return len(prices)\n"},
            {"role":"user","content":"Make total return sum(prices). Keep the name and argument. "
                                     "Return only the complete Python file with no explanation."}
        ],
        "edit_file": "total.py", "max_tokens": 180,
    })
    code = body["choices"][0]["message"]["content"]
    checked, _ = post("/admin/playground/check", {"name":"total.py","content":code})
    if checked.get("check") != "Python syntax checked" or not edit_id:
        raise ValueError("Edit did not produce a syntax check and a request trace.")
    request = Request(BASE+"/admin/analytics/report?window=24h&trace="+edit_id,headers=ADMIN)
    with urlopen(request,timeout=10) as reply:
        trace = json.load(reply)["traces"][0]
    if trace["id"] != edit_id or trace["status"] != "ok" or any(
        attempt["model"] != name or attempt["provider"] != "Local Ollama" for attempt in trace["attempts"]
    ):
        raise ValueError("Edit trace did not stay pinned to the requested model.")
    result = {"model":name,"chat":bool(re.fullmatch(r"\s*4[.!]?\s*",answer)),
              "edit_matches_fixture": EXPECTED == ast.dump(ast.parse(code)),
              "edit_trace":edit_id}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("models",nargs="+")
    args=parser.parse_args()
    for name in args.models:
        result = run_model(name)
        print(json.dumps(result),flush=True)
        if not result["chat"] or not result["edit_matches_fixture"]:
            raise SystemExit("Model output differed from this test fixture.")


if __name__ == "__main__":
    main()
