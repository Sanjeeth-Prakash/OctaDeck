import json
import sqlite3
import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

import app as relay
from provider_catalog import discover
from storage import Store


ADMIN = {"X-Relay-Admin": "dashboard"}


class MediaTests(unittest.TestCase):
    def setUp(self):
        self.temp = self.enterContext(TemporaryDirectory())
        self.store = Store(self.temp)
        self.enterContext(patch.object(relay, "db", self.store))
        self.client = self.enterContext(TestClient(relay.app, base_url="http://127.0.0.1"))
        self.key = {"Authorization": "Bearer " + self.store.token}

    def connection(self, capability, base="https://openrouter.ai/api/v1"):
        response = self.client.post("/admin/providers", headers=ADMIN, json={
            "label": "Fixture", "base": base, "model": "example/model",
            "tier": "balanced", "key": "test-provider-key", "capability": capability,
        })
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["health"])
        return "media/" + response.json()["id"]

    def upstream(self, handler):
        mock = httpx.MockTransport(handler)
        self.enterContext(patch.object(relay, "media_client", lambda: httpx.Client(transport=mock)))

    def test_catalog_uses_nvidia_endpoint_and_marks_only_explicit_free_alias(self):
        def handle(request):
            self.assertEqual(request.url, httpx.URL("https://integrate.api.nvidia.com/v1/models"))
            self.assertEqual(request.headers["Authorization"], "Bearer nvidia-test-key")
            self.assertEqual(request.method, "GET")
            return httpx.Response(200, json={"data": [{"id": "nvidia/model"}]})

        with httpx.Client(transport=httpx.MockTransport(handle)) as client:
            self.assertEqual(discover(client, "NVIDIA NIM", "chat", "nvidia-test-key"),
                             [{"id": "nvidia/model", "free_alias": False}])
        presets = self.client.get("/admin/provider-catalog", headers=ADMIN).json()
        self.assertTrue(any(item["name"] == "NVIDIA NIM" for item in presets))
        with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json={
            "data": [{"id": "paid/model"}, {"id": "a/model:free"}, {"id": "openrouter/free"}]
        }))) as client:
            rows = discover(client, "OpenRouter", "chat", "")
            self.assertEqual([row["free_alias"] for row in rows], [True, True, False])

    def test_legacy_connection_migrates_as_chat(self):
        with TemporaryDirectory() as path:
            with closing(sqlite3.connect(Path(path) / "relay.sqlite")) as db:
                db.execute("CREATE TABLE providers (id TEXT, label TEXT, base TEXT, model TEXT, tier TEXT, secret BLOB)")
                db.execute("INSERT INTO providers VALUES (?,?,?,?,?,?)",
                           ("old", "Legacy", "https://example.test/v1", "old-model", "fast", b""))
                db.commit()
            store = Store(path)
            self.assertEqual(store.providers()[0]["capability"], "chat")
            self.assertEqual(store.providers()[0]["model"], "old-model")

    def test_embeddings_use_explicit_model_and_existing_gateway_key(self):
        alias = self.connection("embeddings")

        def handle(request):
            self.assertEqual(request.url.path, "/api/v1/embeddings")
            self.assertEqual(json.loads(request.content), {"input": "test", "model": "example/model"})
            return httpx.Response(200, json={"data": [{"embedding": [0.1, -0.2]}], "usage": {"total_tokens": 3}})

        self.upstream(handle)
        payload = {"model": alias, "input": "test"}
        self.assertEqual(self.client.post("/v1/embeddings", json=payload).status_code, 401)
        self.assertEqual(self.client.post("/v1/embeddings", headers=self.key,
                                          json={**payload, "model": "auto"}).status_code, 422)
        result = self.client.post("/v1/embeddings", json=payload, headers=self.key)
        self.assertEqual(result.json()["data"][0]["embedding"], [0.1, -0.2])
        report = self.client.get("/admin/analytics/report?mode=embeddings", headers=ADMIN).json()
        self.assertEqual(report["traces"][0]["id"], result.headers["X-Request-ID"])
        self.assertEqual(report["traces"][0]["attempts"][0]["tokens"], 3)

    def test_speech_binary_transcription_multipart_and_images(self):
        speech = self.connection("speech")
        transcription = self.connection("transcription", "https://api.groq.com/openai/v1")
        image = self.connection("images")

        def handle(request):
            if request.url.path.endswith("/audio/speech"):
                self.assertEqual(json.loads(request.content)["voice"], "example")
                return httpx.Response(200, content=b"ID3fixture", headers={"Content-Type": "audio/mpeg"})
            if request.url.path.endswith("/audio/transcriptions"):
                self.assertIn("multipart/form-data", request.headers["content-type"])
                self.assertIn(b"fixture", request.read())
                return httpx.Response(200, json={"text": "Fixture transcript."})
            self.assertEqual(request.url.path, "/api/v1/images")
            return httpx.Response(200, json={"data": [{"b64_json": "Zml4dHVyZQ=="}]})

        self.upstream(handle)
        sound = self.client.post("/v1/audio/speech", headers=self.key,
                                 json={"model": speech, "input": "test", "voice": "example"})
        self.assertEqual(sound.content, b"ID3fixture")
        text = self.client.post("/v1/audio/transcriptions", headers=self.key, json={
            "model": transcription, "input_audio": {"data": "Zml4dHVyZQ==", "format": "wav"}
        })
        self.assertEqual(text.json()["text"], "Fixture transcript.")
        artwork = self.client.post("/v1/images/generations", headers=self.key,
                                   json={"model": image, "prompt": "A blue circle."})
        self.assertEqual(artwork.status_code, 200)

    def test_video_maps_job_and_uses_only_configured_provider_for_download(self):
        alias = self.connection("video")

        def handle(request):
            self.assertEqual(request.url.host, "openrouter.ai")
            if request.method == "POST":
                return httpx.Response(202, json={"id": "upstream-id", "status": "pending"})
            if request.url.path.endswith("/content"):
                self.assertEqual(request.url.path, "/api/v1/videos/upstream-id/content")
                return httpx.Response(200, content=b"video data", headers={"Content-Type": "video/mp4"})
            self.assertEqual(request.url.path, "/api/v1/videos/upstream-id")
            return httpx.Response(200, json={"status": "completed", "unsigned_urls": ["https://example.test/"]})

        self.upstream(handle)
        submitted = self.client.post("/v1/videos", headers=self.key,
                                     json={"model": alias, "prompt": "A paper boat."})
        self.assertEqual(submitted.status_code, 202)
        job = submitted.json()["id"]
        self.assertNotEqual(job, "upstream-id")
        result = self.client.get(f"/v1/videos/{job}", headers=self.key).json()
        self.assertEqual(result["content_url"], f"/v1/videos/{job}/content")
        self.assertEqual(self.client.get(result["content_url"], headers=self.key).content, b"video data")
        self.assertEqual(self.client.get(result["content_url"]).status_code, 401)
