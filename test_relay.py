import tempfile
import unittest
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

import app
from routing import RelayError, choose, execute
from storage import Store

class RelayTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.store = Store(folder.name)
        self.messages = [{"role":"user","content":"Hello"}]

    def response(self, req):
        return httpx.Response(200,json={"choices":[{"message":{"content":"answer"}}],"usage":{"total_tokens":8}})

    def test_tier(self):
        self.assertEqual(choose(self.messages,"auto")[0],"fast")
        self.assertEqual(choose([{"role":"user","content":"Design the architecture"}],"auto")[0],"strong")

    def test_credentials_and_fallback(self):
        self.store.add("Cloud","https://example.org/v1","cloud-mini","fast","sample-secret")
        self.assertNotIn(b"sample-secret",self.store.providers()[1]["secret"])
        def upstream(req):
            if req.url.host=="example.org":
                self.assertEqual(req.headers["Authorization"],"Bearer sample-secret")
                return httpx.Response(429)
            self.assertNotIn("authorization",req.headers)
            return self.response(req)
        with httpx.Client(transport=httpx.MockTransport(upstream)) as client:
            execute(self.store,client,self.messages,"auto","chat",{})
        run=self.store.recent()[0]
        self.assertEqual(run["status"],"ok")
        self.assertEqual([x["outcome"] for x in run["attempts"]],["HTTP 429 · rate limited","ok"])

    def test_strong_workflow(self):
        with httpx.Client(transport=httpx.MockTransport(self.response)) as client:
            execute(self.store,client,self.messages,"strong","task",{})
        self.assertEqual([x["stage"] for x in self.store.recent()[0]["attempts"]],["planner","writer","reviewer"])

    def test_invalid_output(self):
        with httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(200,json={}))) as client:
            with self.assertRaises(RelayError):
                execute(self.store,client,self.messages,"auto","chat",{})
        self.assertEqual(self.store.recent()[0]["status"],"failed")

    def test_api_boundaries(self):
        with patch.object(app,"db",self.store), TestClient(app.app,base_url="http://localhost") as client:
            self.assertEqual(client.get("/v1/models").status_code,401)
            self.assertEqual(client.get("/admin/key").status_code,403)
            admin={"X-Relay-Admin":"dashboard"}
            self.assertEqual(client.get("/admin/key",headers={**admin,"Origin":"https://other.invalid"}).status_code,403)
            key=client.get("/admin/key",headers=admin).json()["key"]
            bearer={"Authorization":"Bearer "+key}
            self.assertEqual(client.get("/v1/models",headers=bearer).status_code,200)
            self.assertEqual(client.post("/v1/chat/completions",headers=bearer,json={"messages":self.messages,"stream":True}).status_code,422)
            provider={"label":"Test","tier":"fast","model":"test","base":"https://example.org/v1","key":"private-example"}
            with patch.object(app,"run_probe",return_value={"state":"healthy"}) as probe:
                self.assertEqual(client.post("/admin/providers",headers=admin,json=provider).status_code,200)
                probe.assert_called_once()
            data=client.get("/admin/providers",headers=admin)
            self.assertNotIn("private-example",data.text)
            self.assertEqual(client.delete("/admin/providers/"+data.json()[-1]["id"],headers=admin).status_code,200)
