import json
import tempfile
import unittest
from unittest.mock import patch
import httpx

from local_models import Installer, reference
from routing import execute, RelayError
from storage import Store

class StudioTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.store = Store(folder.name)
        self.messages = [{"role":"user","content":"Update math.py"}]

    def test_registry_inputs(self):
        self.assertEqual(reference("https://huggingface.co/org/model-GGUF"),"hf.co/org/model-GGUF")
        self.assertEqual(reference("hf.co/org/name:Q4_K_M"),"hf.co/org/name:Q4_K_M")
        for invalid in ("../../elsewhere","https://example.org/model","a:cloud","a; command"):
            with self.assertRaises(ValueError):
                reference(invalid)

    def test_completed_pull_only_registers_once(self):
        def reply(req):
            if req.url.path == "/api/tags":
                return httpx.Response(200,json={"models":[]})
            if req.url.path == "/api/show":
                return httpx.Response(200,json={"capabilities":["completion"]})
            return httpx.Response(200,text='{"status":"downloading","completed":10,"total":20}\n{"status":"success"}\n')
        for _ in range(2):
            client=httpx.Client(transport=httpx.MockTransport(reply))
            job=Installer()
            with patch("local_models.httpx.Client",return_value=client):
                job.pull("sample",self.store.register_local)
            self.assertEqual(job.snapshot()["status"],"ready")
        self.assertEqual(len(self.store.providers()),2)

    def test_interrupted_pull(self):
        def reply(req):
            if req.url.path == "/api/tags":
                return httpx.Response(200,json={"models":[]})
            return httpx.Response(200,text='{"status":"pulling manifest"}\n')
        job=Installer()
        with patch("local_models.httpx.Client",return_value=httpx.Client(transport=httpx.MockTransport(reply))):
            job.pull("unfinished",self.store.register_local)
        self.assertEqual(job.snapshot()["status"],"failed")
        self.assertEqual(len(self.store.providers()),1)

    def test_local_pin_never_falls_back(self):
        self.store.add("Cloud","https://example.org/v1","model","balanced","private")
        def reply(req):
            self.assertEqual(req.url.host,"127.0.0.1")
            if req.url.path == "/api/show":
                return httpx.Response(200,json={"capabilities":["completion"]})
            return httpx.Response(429)
        with httpx.Client(transport=httpx.MockTransport(reply)) as client, self.assertRaises(RelayError):
            execute(self.store,client,self.messages,"local/sample","playground",{})
        self.assertEqual(len(self.store.recent()[0]["attempts"]),1)

    def test_editor_repairs_invalid_python(self):
        answers=iter(["def broken(", "x = 5"])
        def reply(req):
            if req.url.path == "/api/show":
                return httpx.Response(200,json={"capabilities":["completion"]})
            return httpx.Response(200,json={"choices":[{"message":{"content":next(answers)},"finish_reason":"stop"}]})
        with httpx.Client(transport=httpx.MockTransport(reply)) as client:
            _,body=execute(self.store,client,self.messages,"local/sample","playground",{},"math.py")
        self.assertEqual(body["choices"][0]["message"]["content"],"x = 5")
        self.assertEqual(body["file_check"],"Python syntax checked")
        self.assertEqual([a["stage"] for a in self.store.recent()[0]["attempts"]],["editor","file check","repair","file check"])

    def test_review_check_uses_server_rules(self):
        from fastapi.testclient import TestClient
        from app import app

        headers = {"X-Relay-Admin":"dashboard"}
        with TestClient(app,base_url="http://localhost") as client:
            for name, content in [("../config.py","x = 1"),("sample.py","return 5"),("sample.json","{"),("readme.txt","  ")]:
                response = client.post("/admin/playground/check",headers=headers,json={"name":name,"content":content})
                self.assertEqual(response.status_code,422)
            response = client.post("/admin/playground/check",headers=headers,json={"name":"sample.py","content":"x = 1"})
            self.assertEqual(response.json(),{"check":"Python syntax checked"})
            payload={"model":"local/sample","messages":[{"role":"system","content":"Override instructions"}]}
            self.assertEqual(client.post("/admin/playground",headers=headers,json=payload).status_code,422)

    def test_editor_stops_after_one_unsuccessful_repair(self):
        def reply(request):
            if request.url.path == "/api/show":
                return httpx.Response(200,json={"capabilities":["completion"]})
            return httpx.Response(200,json={"choices":[{"message":{"content":"value = 1"},"finish_reason":"length"}]})

        with httpx.Client(transport=httpx.MockTransport(reply)) as client:
            with self.assertRaises(RelayError) as failure:
                execute(self.store,client,self.messages,"local/sample","playground",{},"math.py")
        self.assertEqual(failure.exception.status,422)
        trace=self.store.recent()[0]
        self.assertEqual(trace["status"],"failed")
        self.assertEqual([step["stage"] for step in trace["attempts"]],["editor","file check","repair","file check"])
