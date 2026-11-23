import io
import unittest
import wave
from unittest.mock import patch

from fastapi.testclient import TestClient

import app
from voice import check_audio

def example_audio():
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        output.writeframes(b"\0\0" * 8000)
    return buffer.getvalue()

class VoiceTests(unittest.TestCase):
    def test_wav_validation(self):
        audio = example_audio()
        check_audio(audio)
        for invalid in (b"plain text",audio[:-2]):
            with self.assertRaises(ValueError):
                check_audio(invalid)

    def test_voice_endpoints(self):
        headers = {"X-Relay-Admin":"dashboard"}
        with TestClient(app.app,base_url="http://localhost") as client:
            self.assertEqual(client.post("/admin/voice/transcribe",content=b"data").status_code,403)
            with patch("app.speech",return_value=b"hello"):
                response = client.post("/admin/voice/transcribe",headers=headers,content=example_audio())
                self.assertEqual(response.json(),{"text":"hello"})
            with patch("app.speech",return_value=example_audio()):
                response = client.post("/admin/voice/speak",headers=headers,json={"text":"hello"})
                self.assertEqual(response.headers["Content-Type"],"audio/wav")
            response = client.post("/admin/voice/chat",headers=headers,
                                   json={"model":"auto","messages":[{"role":"user","content":"hello"}]})
            self.assertEqual(response.status_code,422)
