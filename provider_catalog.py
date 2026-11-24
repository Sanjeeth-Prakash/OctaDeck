"""Provider shortcuts and opt-in discovery at documented API endpoints."""

import json
import re

import httpx


# These notes describe plan types. Account limits and model access belong to the provider.
CATALOG = {
    "Ollama": {
        "base": "http://127.0.0.1:11434/v1", "model": "llama3.1:latest",
        "note": "Runs locally. No hosted API key required.",
        "docs": "https://docs.ollama.com/api/openai-compatibility",
        "modes": {"chat": "/models", "embeddings": None},
    },
    "NVIDIA NIM": {
        "base": "https://integrate.api.nvidia.com/v1",
        "note": "Hosted developer access. Check your NVIDIA account for available models and limits.",
        "docs": "https://docs.api.nvidia.com/nim/reference/llm-apis",
        "modes": {"chat": "/models", "embeddings": None},
    },
    "Gemini": {
        "base": "https://generativelanguage.googleapis.com/v1beta/openai",
        "note": "Selected models have a free tier. Availability and rate limits vary.",
        "docs": "https://ai.google.dev/gemini-api/docs/pricing",
        "modes": {"chat": "/models", "embeddings": None},
    },
    "Groq": {
        "base": "https://api.groq.com/openai/v1",
        "note": "Free and developer plans have different model and request limits.",
        "docs": "https://console.groq.com/docs/rate-limits",
        "modes": {"chat": "/models", "speech": None, "transcription": None},
    },
    "OpenRouter": {
        "base": "https://openrouter.ai/api/v1",
        "note": "Choose a :free model or openrouter/free for free chat. Other routes, including video, may charge.",
        "docs": "https://openrouter.ai/docs/faq",
        "modes": {"chat": "/models", "embeddings": "/embeddings/models", "speech": "/audio/speech/models",
                  "transcription": "/models?output_modalities=transcription", "images": "/images/models",
                  "video": "/videos/models"},
    },
    "Cerebras": {
        "base": "https://api.cerebras.ai/v1",
        "note": "Model availability and limits depend on your inference plan.",
        "docs": "https://inference-docs.cerebras.ai/resources/openai",
        "modes": {"chat": "/models"},
    },
    "Mistral": {
        "base": "https://api.mistral.ai/v1",
        "note": "Check the API plan on your Mistral account before running inference.",
        "docs": "https://docs.mistral.ai/resources/migration-guides",
        "modes": {"chat": "/models", "embeddings": None},
    },
    "Hugging Face": {
        "base": "https://router.huggingface.co/v1",
        "note": "Uses monthly inference credits. Usage beyond credits can be billed on an enabled billing account.",
        "docs": "https://huggingface.co/docs/inference-providers/en/pricing",
        "modes": {"chat": "/models"},
    },
    "Cloudflare Workers AI": {
        "base": "https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1",
        "note": "Replace {account_id} in the URL. The free plan is measured in neurons, with model restrictions.",
        "docs": "https://developers.cloudflare.com/workers-ai/configuration/open-ai-compatibility/",
        "modes": {"chat": None, "embeddings": None},
    },
    "OpenCode Zen": {
        "base": "https://opencode.ai/zen/v1",
        "note": "Use a documented Chat Completions model. Some models are free and others use different APIs.",
        "docs": "https://opencode.ai/docs/zen/",
        "modes": {"chat": None},
    },
    "Cohere": {
        "base": "https://api.cohere.ai/compatibility/v1",
        "note": "Trial keys are limited. Check your key type and model access before generating.",
        "docs": "https://docs.cohere.com/docs/compatibility-api",
        "modes": {"chat": None, "embeddings": None, "transcription": None},
    },
    "SiliconFlow": {
        "base": "https://api.siliconflow.com/v1",
        "note": "Check model prices and credits in your region before making requests.",
        "docs": "https://docs.siliconflow.com/en/api-reference/chat-completions/chat-completions",
        "modes": {"chat": "/models", "embeddings": None},
    },
    "Custom": {
        "base": "",
        "note": "Use a compatible provider's base URL and exact model ID. Charges depend on your provider.",
        "modes": {"chat": None, "embeddings": None, "speech": None, "transcription": None, "images": None},
    },
}

def presets():
    return [
        {
            "name": name, "base": item["base"], "note": item["note"],
            "model": item.get("model", ""), "docs": item.get("docs"),
            "modes": list(item["modes"]),
            "discovery": [kind for kind, path in item["modes"].items() if path],
        }
        for name, item in CATALOG.items()
    ]


class CatalogError(Exception):
    def __init__(self, message, status):
        super().__init__(message)
        self.status = status


def discover(client, name, capability, key):
    preset = CATALOG.get(name)
    path = preset and preset["modes"].get(capability)
    if not path:
        raise CatalogError("Enter the model ID from the provider's documentation.", 422)
    if name != "Ollama" and not key and name != "OpenRouter":
        raise CatalogError("Enter a provider key to fetch its model list.", 422)

    headers = {"Authorization": "Bearer " + key} if key else {}
    try:
        with client.stream("GET", preset["base"] + path, headers=headers) as response:
            if not response.is_success:
                status = response.status_code
                message = {
                    401: "Provider rejected this key.", 403: "Provider denied model listing for this key.",
                    429: "Provider rate limit reached while listing models.",
                }.get(status, f"Model listing failed with HTTP {status}.")
                raise CatalogError(message, status if status in {401, 403, 429} else 502)
            raw = bytearray()
            for chunk in response.iter_bytes():
                raw.extend(chunk)
                if len(raw) > 4_000_000:
                    raise ValueError("Catalog exceeds the size limit")
        listing = json.loads(raw)["data"]
        if not isinstance(listing, list):
            raise ValueError("Invalid data list")
    except httpx.RequestError as error:
        raise CatalogError("Could not reach the provider's model list.", 502) from error
    except (KeyError, TypeError, ValueError) as error:
        raise CatalogError("Unexpected model list. Enter the model ID manually.", 502) from error

    models = {}
    for item in listing:
        if isinstance(item, dict):
            model = item.get("id")
            if isinstance(model, str) and 0 < len(model) <= 200 and not re.search(r"\s", model):
                models[model] = (
                    name == "OpenRouter" and capability == "chat"
                    and (model.endswith(":free") or model == "openrouter/free")
                )
    return [{"id": model, "free_alias": free} for model, free in
            sorted(models.items(), key=lambda entry: (not entry[1], entry[0].casefold()))[:1000]]
