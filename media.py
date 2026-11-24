"""Make a request to an explicitly selected non-chat connection."""

import base64
import json
import re
from time import monotonic, time

import httpx
from cryptography.fernet import InvalidToken

from health import auth_headers
from provider_catalog import CATALOG
from routing import RelayError, elapsed


OPENROUTER = CATALOG["OpenRouter"]["base"]
PATHS = {
    "embeddings": "/embeddings",
    "speech": "/audio/speech",
    "transcription": "/audio/transcriptions",
    "images": "/images/generations",
    "video": "/videos",
}
VIDEO_STATES = {"pending", "queued", "in_progress", "processing", "running", "completed", "failed", "cancelled", "expired"}
MAX_OUTPUT = 24 * 1024 * 1024


def media_provider(store, alias, mode):
    if not re.fullmatch(r"media/[0-9a-f]{32}", alias):
        raise RelayError("Select a saved model of the requested capability.", 422)
    provider_id = alias.split("/", 1)[1]
    provider = next((item for item in store.providers() if item["id"] == provider_id), None)
    if provider is None or provider["capability"] != mode:
        raise RelayError("Select a saved model of the requested capability.", 422)
    return provider


def read_upstream(store, client, provider, method, path, *, payload=None, binary=(), multipart=None):
    headers = auth_headers(store, provider)
    arguments = {"json": payload} if multipart is None else {"data": payload, "files": multipart}
    with client.stream(method, provider["base"] + path, headers=headers, **arguments) as response:
        status = response.status_code
        if not response.is_success:
            if status in {400, 401, 402, 403, 404, 409, 422, 429}:
                raise RelayError(f"Provider returned HTTP {status}.", status)
            raise RelayError("Provider returned an upstream error.", 502)
        content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if binary and content_type not in binary:
            raise RelayError("Provider returned an unexpected media format.", 502)
        data = bytearray()
        for chunk in response.iter_bytes():
            if len(data) + len(chunk) > MAX_OUTPUT:
                raise RelayError("Provider response exceeded the 24 MiB limit.", 502)
            data.extend(chunk)
    if binary:
        if not data:
            raise RelayError("Provider returned an empty media file.", 502)
        return bytes(data), content_type
    result = json.loads(data)
    if not isinstance(result, dict):
        raise ValueError("Invalid provider response")
    return result, "application/json"


def job_status(data, job):
    status = data.get("status")
    if status not in VIDEO_STATES:
        raise ValueError("Unexpected video job state")
    links = {"id": job, "status": status, "polling_url": f"/v1/videos/{job}"}
    if status == "completed":
        links["content_url"] = f"/v1/videos/{job}/content"
    if status in {"failed", "cancelled", "expired"}:
        links["error"] = f"Video generation {status} on the provider."
    return links


def payload_result(store, client, provider, mode, payload):
    path = PATHS[mode]
    if mode == "images" and provider["base"] == OPENROUTER:
        path = "/images"
    multipart = None
    payload = {**payload, "model": provider["model"]}
    if mode == "transcription" and provider["base"] != OPENROUTER:
        audio = payload.pop("input_audio")
        multipart = {"file": ("recording." + audio["format"], base64.b64decode(audio["data"], validate=True))}
    binary = ("audio/mpeg", "audio/mp3", "audio/wav", "audio/x-wav") if mode == "speech" else ()
    result, content_type = read_upstream(
        store, client, provider, "POST", path, payload=payload, binary=binary, multipart=multipart,
    )
    if mode == "video":
        upstream = result.get("id")
        if not isinstance(upstream, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,160}", upstream):
            raise ValueError("Invalid upstream job ID")
        job_status(result, upstream)
        job = store.save_video_job(provider["id"], upstream)
        if job is None:
            raise RelayError("The connection was removed while the provider accepted the video job.", 409)
        return job_status(result, job), content_type
    if mode in {"embeddings", "images"}:
        data = result.get("data")
        if not isinstance(data, list) or not data or not isinstance(data[0], dict):
            raise ValueError("Expected a nonempty data array")
        if mode == "embeddings" and not isinstance(data[0].get("embedding"), list):
            raise ValueError("Missing embedding")
        if mode == "images" and not any(isinstance(data[0].get(key), str) for key in ("url", "b64_json")):
            raise ValueError("Missing image output")
    if mode == "transcription" and not isinstance(result.get("text"), str):
        raise ValueError("Missing transcription")
    return result, content_type


def generate(store, client, mode, model, payload):
    provider = media_provider(store, model, mode)
    reason = "Explicit media connection selected."
    if mode == "video":
        reason = "Video submission. Poll the job for generation status."
    run = store.start(provider["tier"], reason, mode)
    started = monotonic()
    outcome, result, code = "provider error", None, None
    try:
        result, content_type = payload_result(store, client, provider, mode, payload)
        outcome = "ok"
        return result, content_type, run
    except RelayError as error:
        code = error.status
        outcome = str(error)
        error.run = run
        raise
    except InvalidToken as error:
        code, outcome = 401, "Saved credential could not be read."
        relay_error = RelayError(outcome, code)
        relay_error.run = run
        raise relay_error from error
    except (httpx.HTTPError, ValueError, TypeError) as error:
        outcome = "Provider response unavailable. Check upstream status before retrying."
        relay_error = RelayError(outcome, 502)
        relay_error.run = run
        raise relay_error from error
    finally:
        usage = result.get("usage") if isinstance(result, dict) else None
        usage = usage if isinstance(usage, dict) else {}
        duration = elapsed(started)
        store.attempt(run, mode, provider, outcome, duration, usage.get("total_tokens"), usage)
        store.finish(run, "ok" if outcome == "ok" else "failed", duration)
        state = {401: "rejected", 402: "billing", 403: "denied", 404: "missing", 429: "limited"}.get(code)
        if outcome == "ok" or state:
            store.save_health(provider["id"], {
                "state": state or "healthy", "detail": str(outcome), "http_status": code or (202 if mode == "video" else 200),
                "checked_at": time(), "duration_ms": duration,
            })


def video_result(store, client, job, content=False):
    saved = store.video_job(job)
    if not saved:
        raise RelayError("Video job not found.", 404)
    provider = media_provider(store, "media/" + saved["provider_id"], "video")
    path = "/videos/" + saved["upstream_id"]
    try:
        if content:
            return read_upstream(store, client, provider, "GET", path + "/content?index=0",
                                 binary=("video/mp4", "video/webm"))
        result, content_type = read_upstream(store, client, provider, "GET", path)
        return job_status(result, job), content_type
    except InvalidToken as error:
        raise RelayError("Saved credential could not be read.", 401) from error
    except (httpx.HTTPError, ValueError, TypeError) as error:
        raise RelayError("Provider video response unavailable.", 502) from error
