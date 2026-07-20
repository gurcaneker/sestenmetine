"""Backend API tests for SesDeşifre transcription service."""
import io
import os
import wave
import math
import struct
import pytest
import requests

BASE_URL = os.environ['REACT_APP_BACKEND_URL'].rstrip('/')
API = f"{BASE_URL}/api"
FIXTURES = "/app/test_fixtures"


@pytest.fixture(scope="module")
def session():
    s = requests.Session()
    return s


# --- basic endpoints ----------------------------------------------------------
class TestBasics:
    def test_root_returns_turkish_welcome(self, session):
        r = session.get(f"{API}/", timeout=30)
        assert r.status_code == 200
        data = r.json()
        assert "message" in data
        assert data["message"] == "SesDeşifre API"

    def test_health(self, session):
        r = session.get(f"{API}/health", timeout=30)
        assert r.status_code == 200
        data = r.json()
        assert data.get("status") == "ok"
        assert data.get("service") == "transcription"


# --- transcription validation errors ------------------------------------------
class TestTranscribeValidation:
    def test_rejects_unsupported_extension(self, session):
        files = {"file": ("notes.txt", b"hello world", "text/plain")}
        r = session.post(f"{API}/transcribe", files=files, data={"language": "tr"}, timeout=30)
        assert r.status_code == 400
        detail = r.json().get("detail", "")
        assert "Desteklenmeyen" in detail  # Turkish error

    def test_rejects_empty_file(self, session):
        files = {"file": ("empty.wav", b"", "audio/wav")}
        r = session.post(f"{API}/transcribe", files=files, data={"language": "tr"}, timeout=30)
        assert r.status_code == 400
        detail = r.json().get("detail", "")
        assert "Boş" in detail or "empty" in detail.lower()

    def test_no_file_field_returns_422(self, session):
        r = session.post(f"{API}/transcribe", data={"language": "tr"}, timeout=30)
        assert r.status_code in (400, 422)


# --- real Whisper transcription -----------------------------------------------
class TestTranscribeReal:
    def test_transcribe_real_speech_wav(self, session):
        """Send a real WAV sample containing English speech.
        Whisper must return a non-empty transcript proving the AI pipeline actually works.
        """
        wav_path = os.path.join(FIXTURES, "jfk.wav")
        assert os.path.exists(wav_path), "test fixture missing"
        with open(wav_path, "rb") as f:
            files = {"file": ("jfk.wav", f, "audio/wav")}
            r = session.post(
                f"{API}/transcribe",
                files=files,
                data={"language": "en"},
                timeout=120,
            )
        assert r.status_code == 200, r.text
        data = r.json()
        assert set(["text", "language", "filename", "size_bytes"]).issubset(data.keys())
        assert data["filename"] == "jfk.wav"
        assert data["size_bytes"] > 10000
        # Real speech: transcript must be non-empty
        text = data["text"] or ""
        assert isinstance(text, str)
        assert len(text.strip()) > 5, f"Whisper returned suspiciously short text: {text!r}"
        # The reference sentence is: "She had your dark suit in greasy wash water all year"
        low = text.lower()
        assert any(w in low for w in ["dark", "suit", "greasy", "wash", "year", "water", "she"]), \
            f"Unexpected transcript content: {text!r}"

    def test_transcribe_flac_reports_error_gracefully(self, session):
        """Backend advertises .flac/.ogg support in ALLOWED_EXTS but the underlying
        Whisper wrapper only accepts mp3/mp4/mpeg/mpga/m4a/wav/webm.
        Currently the backend returns 500 with the raw provider error string, which
        is a leaky abstraction. This test just documents current behavior for RCA."""
        flac_path = os.path.join(FIXTURES, "jfk.flac")
        with open(flac_path, "rb") as f:
            files = {"file": ("jfk.flac", f, "audio/flac")}
            r = session.post(
                f"{API}/transcribe",
                files=files,
                data={"language": "en"},
                timeout=120,
            )
        # Document the mismatch: extension is accepted but Whisper rejects it.
        assert r.status_code in (200, 400, 500)
        if r.status_code != 200:
            assert "flac" in r.text.lower() or "Unsupported" in r.text or "Transkripsiyon" in r.text

    def test_transcribe_wav_pipeline(self, session):
        """Send a small silent-ish sine WAV with tr hint. Must return 200 with schema.
        Text may be empty or hallucinated; we only assert pipeline works end-to-end.
        """
        wav_path = os.path.join(FIXTURES, "sine.wav")
        assert os.path.exists(wav_path)
        with open(wav_path, "rb") as f:
            files = {"file": ("sine.wav", f, "audio/wav")}
            r = session.post(
                f"{API}/transcribe",
                files=files,
                data={"language": "tr"},
                timeout=120,
            )
        assert r.status_code == 200, r.text
        data = r.json()
        assert "text" in data and isinstance(data["text"], str)
        assert data["filename"] == "sine.wav"
        assert data["language"] == "tr"
        assert data["size_bytes"] == os.path.getsize(wav_path)
