import tempfile
import unittest
from time import time

import httpx

from analytics import report
from health import probe_provider
from routing import execute
from storage import Store


class OperationsTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.store = Store(folder.name)

    def test_probe_models_and_preserves_safe_status(self):
        provider = self.store.add("Example", "https://example.org/v1", "exact-model", "fast", "dummy-key")
        def reply(request):
            self.assertEqual(request.url.path, "/v1/chat/completions")
            self.assertEqual(request.headers["Authorization"], "Bearer dummy-key")
            self.assertIn(b'exact-model', request.content)
            self.assertNotIn(b'dummy-key', request.content)
            return httpx.Response(429, text="raw detail")
        with httpx.Client(transport=httpx.MockTransport(reply)) as client:
            status = probe_provider(self.store, client, provider)
        self.assertEqual(status["state"], "limited")
        self.assertEqual(status["http_status"], 429)
        self.assertNotIn("raw detail", repr(status))
        self.assertEqual(self.store.providers()[-1]["checked_at"], status["checked_at"])

    def test_rejected_provider_is_skipped(self):
        provider = self.store.add("Bad key", "https://example.org/v1", "short", "fast", "wrong")
        def reply(request):
            if request.url.host == "example.org":
                return httpx.Response(401)
            return httpx.Response(200,json={"choices":[{"message":{"content":"ok"}}]})
        with httpx.Client(transport=httpx.MockTransport(reply)) as client:
            probe_provider(self.store, client, provider)
            run, _ = execute(self.store,client,[{"role":"user","content":"hi"}],"fast","chat",{})
        trace = next(row for row in self.store.recent() if row["id"] == run)
        self.assertEqual([a["provider"] for a in trace["attempts"]],["Local Ollama"])

    def test_report_counts_older_rows_beyond_display_cap(self):
        with self.store.db() as db:
            now = time()
            db.executemany("INSERT INTO runs VALUES(?,?,?,?,?,?,?)", [
                (str(i),now-3-i,"fast","fixture","ok",i+1,"chat") for i in range(120)
            ])
        provider = self.store.providers()[0]
        self.store.attempt("119","writer",provider,"ok",120,5,{"prompt_tokens":3,"completion_tokens":2})
        self.store.attempt("119","file check",provider,"invalid syntax",0,None)
        all_runs = report(self.store,"24h",trace="119")
        self.assertEqual(all_runs["summary"]["requests"],120)
        self.assertEqual(all_runs["summary"]["p95_ms"],114)
        self.assertEqual(all_runs["summary"]["input_tokens"],3)
        self.assertEqual(all_runs["summary"]["recovered"],1)
        self.assertEqual(len(all_runs["traces"]),100)
        self.assertEqual(all_runs["traces"][0]["id"],"119")
        recovered = report(self.store,"24h",outcome="recovered",model=provider["model"])
        self.assertEqual(recovered["models"][0]["calls"],1)
        self.assertEqual(len(recovered["traces"]),1)
