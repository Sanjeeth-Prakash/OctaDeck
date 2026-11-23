"""Use installed Windows speech engines through a local subprocess."""
import base64
import io
from pathlib import Path
import subprocess
import os
import wave

MAX_WAV_BYTES = 3_000_000

def check_audio(data):
    try:
        with wave.open(io.BytesIO(data)) as audio:
            rate = audio.getframerate()
            count = audio.getnframes()
            if audio.getnchannels() == 1 and audio.getsampwidth() == 2 and rate in (16000, 22050, 24000, 44100, 48000):
                if 0 < count <= rate * 30 and len(audio.readframes(count)) == count * 2:
                    return
    except (wave.Error, EOFError):
        pass
    raise ValueError("Use up to 30 seconds of mono, 16-bit PCM WAV.")

def speech(mode, data):
    if os.name != "nt":
        raise RuntimeError("Local voice currently requires Windows desktop speech.")
    if mode == "transcribe":
        check_audio(data)
    try:
        process = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-File",
             str(Path(__file__).with_name("speech.ps1").resolve()), "-Mode", mode],
            input=base64.b64encode(data), capture_output=True, timeout=45,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if process.returncode:
            raise RuntimeError("Windows speech failed. Check that a desktop speech language and voice are installed.")
        return base64.b64decode(process.stdout.strip(), validate=True)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("Windows speech did not respond.") from exc
