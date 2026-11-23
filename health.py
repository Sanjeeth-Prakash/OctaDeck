"""Probe a saved provider with a small, independent chat request."""
from time import monotonic, time

import httpx
from cryptography.fernet import InvalidToken


def auth_headers(store, provider):
    if not provider["secret"]:
        return {}
    return {"Authorization": "Bearer " + store.cipher.decrypt(provider["secret"]).decode()}


def probe_provider(store, client, provider):
    start = monotonic()
    http_status = None
    try:
        headers = auth_headers(store, provider)
        response = client.post(provider["base"] + "/chat/completions", headers=headers, json={
            "model": provider["model"],
            "messages": [{"role": "user", "content": "Reply OK."}],
            "max_tokens": 16,
        })
        http_status = response.status_code
        if response.is_success:
            choice = response.json()["choices"][0]["message"]
            if not isinstance(choice, dict) or not isinstance(choice.get("content"), str):
                raise ValueError("Expected a text completion.")
            state, detail = "healthy", "Provider accepted this key and model."
        else:
            state, detail = {
                401: ("rejected", "Provider rejected the credential."),
                403: ("denied", "Access denied for this key or model."),
                404: ("missing", "Model ID or API endpoint was not found."),
                429: ("limited", "Provider rate limit or quota reached."),
            }.get(http_status, ("error", "Provider returned an error."))
    except InvalidToken:
        state, detail = "rejected", "Saved credential could not be read."
    except httpx.TimeoutException:
        state, detail = "error", "Provider timed out."
    except httpx.RequestError:
        state, detail = "error", "Provider could not be reached."
    except (KeyError, ValueError, IndexError, TypeError):
        state, detail = "error", "Provider returned an unexpected response."
    result = {"state": state, "detail": detail, "http_status": http_status,
              "checked_at": time(), "duration_ms": round((monotonic() - start) * 1000)}
    store.save_health(provider["id"], result)
    return result
