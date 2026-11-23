import unittest
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from app import app


class HandoffIntegrationTests(unittest.TestCase):
    def test_only_forwards_reviewed_transcript_to_local_service(self):
        with TestClient(app, base_url="http://localhost") as browser:
            url = "/admin/playground/handoff"
            headers = {"X-Relay-Admin": "dashboard"}
            payload = {"transcript": "User: Fix the receipt total."}
            self.assertEqual(browser.post(url, json=payload).status_code, 403)
            with patch("app.httpx.Client") as client:
                upstream = client.return_value.__enter__.return_value
                upstream.post.return_value = httpx.Response(200, json={"markdown": "# Brief", "usage": {}})
                result = browser.post(url, headers=headers, json=payload)
                self.assertEqual(result.json(), {"markdown": "# Brief"})
                upstream.post.assert_called_once_with("http://127.0.0.1:8512/generate", json=payload)
                self.assertFalse(client.call_args.kwargs["follow_redirects"])
                upstream.post.side_effect = httpx.ConnectError("offline")
                result = browser.post(url, headers=headers, json=payload)
                self.assertEqual(result.status_code, 503)
                self.assertIn("port 8512", result.json()["detail"])
