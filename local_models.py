"""Local Ollama model inventory and single-flight downloads."""
import json
import re
from threading import Lock, Thread

import httpx

BASE = "http://127.0.0.1:11434"
PART = r"[A-Za-z0-9][A-Za-z0-9_.-]*"

def reference(value):
    name = value.strip().removeprefix("https://huggingface.co/")
    if value.strip().startswith("https://huggingface.co/"):
        name = "hf.co/" + name
    if len(name) > 240 or not re.fullmatch(
        rf"(?:hf\.co/{PART}/{PART}|(?:{PART}/)?{PART})(?::{PART})?", name
    ) or name.endswith((":cloud", "-cloud")):
        raise ValueError("Enter an Ollama model tag or a Hugging Face GGUF repository and optional quantization.")
    return name

def local_chat(client, model):
    result = client.post(BASE + "/api/show", json={"model": model})
    result.raise_for_status()
    meta = result.json()
    return "completion" in meta.get("capabilities", []) and not (
        meta.get("remote_model") or meta.get("remote_host") or model.endswith((":cloud", "-cloud"))
    )

def inventory():
    with httpx.Client(timeout=8, trust_env=False) as client:
        response = client.get(BASE + "/api/tags")
        response.raise_for_status()
        return [{"name": r["name"], "bytes": r["size"], "chat": local_chat(client, r["name"])}
                for r in response.json()["models"]]

class Installer:
    def __init__(self):
        self.lock = Lock()
        self.job = {"status": "idle", "model": ""}

    def snapshot(self):
        with self.lock:
            return dict(self.job)

    def update(self, **fields):
        with self.lock:
            self.job.update(fields)

    def start(self, name, register):
        name = reference(name)
        with self.lock:
            if self.job["status"] == "running":
                if name == self.job["model"]:
                    return dict(self.job)
                raise RuntimeError("A model is already being installed.")
            self.job = {"model":name, "status":"running", "detail":"Contacting Ollama"}
        Thread(target=self.pull, args=(name, register), daemon=True).start()
        return self.snapshot()

    def pull(self, name, register):
        try:
            with httpx.Client(timeout=httpx.Timeout(180, connect=5), trust_env=False) as client:
                installed = client.get(BASE + "/api/tags")
                installed.raise_for_status()
                names = {m["name"] for m in installed.json()["models"]}
                if name not in names and name + ":latest" not in names:
                    with client.stream("POST", BASE + "/api/pull", json={"model":name,"stream":True}) as res:
                        res.raise_for_status()
                        finished = False
                        for line in res.iter_lines():
                            if not line:
                                continue
                            event = json.loads(line)
                            if event.get("error"):
                                raise ValueError(str(event["error"])[:240])
                            status = event.get("status","Downloading")
                            self.update(detail=status, completed=event.get("completed"), total=event.get("total"))
                            finished = status == "success"
                        if not finished:
                            raise ValueError("Download ended before Ollama confirmed completion.")
                if not local_chat(client,name):
                    raise ValueError("Installed artifact does not support local text chat.")
                register(name)
                self.update(status="ready",detail="Installed and available through the gateway.")
        except (ValueError, KeyError, httpx.HTTPError, OSError) as exc:
            self.update(status="failed", detail=str(exc)[:280])
        except Exception:
            self.update(status="failed",detail="Model registration failed. Check local storage and retry.")
