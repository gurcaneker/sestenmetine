"""Backend API tests for SesDeşifre transcription service."""
import io
import os
import wave
import math
import struct
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv

# Real Whisper/Claude calls need EMERGENT_LLM_KEY + network access to the
# provider; skipped in local/CI environments where that key isn't configured.
# Reason for the flag (not env-key auto-detect): keeps skip behavior explicit
# and deterministic regardless of what happens to be set in the shell.
REQUIRES_REAL_API = pytest.mark.skip(
    reason="Gerçek OpenAI Whisper / Anthropic Claude API çağrısı gerektirir "
           "(EMERGENT_LLM_KEY + canlı sağlayıcı erişimi). Yerel/CI test "
           "ortamında bu anahtar tanımlı değil — silme, sadece skip."
)

BASE_URL = os.environ['REACT_APP_BACKEND_URL'].rstrip('/')
API = f"{BASE_URL}/api"
FIXTURES = "/app/test_fixtures"

# Load backend/.env so tests automatically use the same API_KEY the running
# server was started with — avoids hand-duplicating the secret in a second
# place (e.g. an extra env var on the pytest command line) that could drift.
load_dotenv(Path(__file__).parent.parent / '.env')
API_KEY = os.environ.get('API_KEY')
AUTH_HEADERS = {"X-API-Key": API_KEY} if API_KEY else {}


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


# --- transcription validation + auth + rate limiting ---------------------
# Auth/rate-limit tests for /transcribe live in THIS class (not a separate
# one) on purpose: pytest-xdist's `--dist loadscope` groups by class, and two
# different classes CAN run concurrently on different workers even when both
# are tagged with the same @pytest.mark.xdist_group (verified empirically —
# it didn't merge them here). Since every authenticated /transcribe call
# shares ONE server-side rate-limit budget (5/minute per IP, in-memory), any
# concurrently-running class hitting the same endpoint races that budget and
# causes spurious 429s in tests that expect 400. Keeping everything in one
# class guarantees a single worker + strict definition-order execution.
class TestTranscribeValidation:
    def test_rejects_unsupported_extension(self, session):
        files = {"file": ("notes.txt", b"hello world", "text/plain")}
        r = session.post(f"{API}/transcribe", files=files, data={"language": "tr"}, headers=AUTH_HEADERS, timeout=30)
        assert r.status_code == 400
        detail = r.json().get("detail", "")
        assert "Desteklenmeyen" in detail  # Turkish error

    def test_rejects_empty_file(self, session):
        files = {"file": ("empty.wav", b"", "audio/wav")}
        r = session.post(f"{API}/transcribe", files=files, data={"language": "tr"}, headers=AUTH_HEADERS, timeout=30)
        assert r.status_code == 400
        detail = r.json().get("detail", "")
        assert "Boş" in detail or "empty" in detail.lower()

    def test_no_file_field_returns_422(self, session):
        r = session.post(f"{API}/transcribe", data={"language": "tr"}, headers=AUTH_HEADERS, timeout=30)
        assert r.status_code in (400, 422)

    def test_rejects_flac_with_clear_400(self, session):
        """FLAC was removed from ALLOWED_EXTS by consistency-agent: the
        Whisper wrapper doesn't accept it natively, and while pydub/ffmpeg
        CAN transcode it (verified locally with a working ffmpeg+ffprobe
        toolchain), a 500 with a raw provider error string reached users
        whenever the deploy environment lacked a working ffmpeg/ffprobe on
        PATH — a leaky, hard-to-diagnose failure mode. Until that infra
        dependency is confirmed and Option B (server-side transcoding, see
        memory/PRD.md backlog) is re-enabled, .flac must fail fast with a
        clear 400 — same as any other unsupported extension. Was
        test_transcribe_flac_reports_error_gracefully in TestTranscribeReal
        (needed a real API call); moved here because the rejection now
        happens at the extension-validation step, before any Whisper/Claude
        call is made.

        Note: .ogg used to be rejected the same way (see git history) but was
        re-enabled once _verify_media_stream() gave the backend a real,
        content-based check independent of the ffmpeg-availability concern
        above — see test_accepts_ogg_extension_but_rejects_undecodable_content."""
        files = {"file": ("jfk.flac", b"fake flac bytes - never decoded", "audio/flac")}
        r = session.post(f"{API}/transcribe", files=files, data={"language": "en"}, headers=AUTH_HEADERS, timeout=30)
        assert r.status_code == 400
        detail = r.json().get("detail", "")
        assert "Desteklenmeyen" in detail
        assert "flac" in detail.lower()

    def test_accepts_ogg_extension_but_rejects_undecodable_content(self, session):
        """.ogg is now in ALLOWED_EXTS (re-enabled, see test_rejects_flac_
        with_clear_400's note) — this fake payload isn't real Ogg content, so
        it should pass the extension check and then get caught by
        _verify_media_stream's real content probe instead, with a 400 that's
        NOT the generic "Desteklenmeyen dosya formatı" (that would mean the
        extension itself was rejected, which is the regression this guards
        against)."""
        files = {"file": ("clip.ogg", b"fake ogg bytes - never decoded", "audio/ogg")}
        r = session.post(f"{API}/transcribe", files=files, data={"language": "en"}, headers=AUTH_HEADERS, timeout=30)
        assert r.status_code == 400
        detail = r.json().get("detail", "")
        assert "Desteklenmeyen" not in detail
        assert "ses akışı bulunamadı" in detail.lower() or "işlenemedi" in detail.lower()

    def test_rejects_undecodable_dav_with_actionable_message(self, session):
        """.dav (DVR/security-camera recordings) gets its own actionable
        error message (not the generic one) when the content can't be
        decoded — see _verify_media_stream's DVR_EXTS branch."""
        files = {"file": ("recording.dav", b"fake dav bytes - never decoded", "video/x-dav")}
        r = session.post(f"{API}/transcribe", files=files, data={"language": "en"}, headers=AUTH_HEADERS, timeout=30)
        assert r.status_code == 400
        detail = r.json().get("detail", "")
        assert "DVR" in detail
        assert "VLC" in detail

    # --- auth (missing/wrong API key never consumes rate-limit budget: ---
    # --- require_api_key runs as a route dependency BEFORE the rate-  ---
    # --- limited endpoint body, see backend/server.py) ---------------
    def test_missing_api_key_returns_401(self, session):
        files = {"file": ("notes.txt", b"hello world", "text/plain")}
        r = session.post(f"{API}/transcribe", files=files, data={"language": "tr"}, timeout=30)
        assert r.status_code == 401
        detail = r.json().get("detail", "")
        assert "API" in detail

    def test_wrong_api_key_returns_401(self, session):
        files = {"file": ("notes.txt", b"hello world", "text/plain")}
        r = session.post(
            f"{API}/transcribe",
            files=files,
            data={"language": "tr"},
            headers={"X-API-Key": "definitely-not-the-real-key"},
            timeout=30,
        )
        assert r.status_code == 401

    def test_rate_limit_blocks_after_threshold(self, session):
        """Fires more requests than RATE_LIMIT (5/minute) allows and asserts
        at least one gets 429 with the app's Turkish message (not slowapi's
        default). Doesn't assert an exact trip point since every
        authenticated /transcribe call above in this class already consumed
        some of the shared per-IP budget — fires enough of its own requests
        to trip the limiter regardless of exactly how much budget remains.
        MUST stay the last test in this class (see class docstring: needs
        the whole class on one worker, in definition order, so it isn't
        racing a concurrently-running class for the same budget). Running
        this file twice within a minute against the same live server may
        make earlier tests in this class see 429s too (in-memory limiter
        state persists across pytest invocations) — restart the server to
        reset it.
        """
        if not API_KEY:
            pytest.skip("API_KEY tanımlı değil (backend/.env) — auth testleri atlandı.")
        responses = []
        for _ in range(7):
            files = {"file": ("notes.txt", b"hello world", "text/plain")}
            r = session.post(
                f"{API}/transcribe", files=files, data={"language": "tr"},
                headers=AUTH_HEADERS, timeout=30,
            )
            responses.append(r)
            if r.status_code == 429:
                break
        statuses = [r.status_code for r in responses]
        assert 429 in statuses, f"7 istekten hiçbiri rate limit'e takılmadı: {statuses}"
        limited_resp = next(r for r in responses if r.status_code == 429)
        assert "Çok fazla istek" in limited_resp.json().get("detail", "")


# --- real Whisper transcription -----------------------------------------------
class TestTranscribeReal:
    @REQUIRES_REAL_API
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
                headers=AUTH_HEADERS,
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

    # test_transcribe_flac_reports_error_gracefully moved to
    # TestTranscribeValidation.test_rejects_flac_with_clear_400 (+ new
    # test_rejects_ogg_with_clear_400) by consistency-agent: FLAC/OGG were
    # removed from ALLOWED_EXTS, so the 500-with-raw-provider-error this test
    # used to document no longer happens — rejection is now a fast, in-process
    # 400 before any Whisper call, so it no longer belongs in this
    # real-API-required class. See memory/PRD.md backlog for the Option B
    # (re-enable with verified server-side transcoding) follow-up.

    @REQUIRES_REAL_API
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
                headers=AUTH_HEADERS,
                timeout=120,
            )
        assert r.status_code == 200, r.text
        data = r.json()
        assert "text" in data and isinstance(data["text"], str)
        assert data["filename"] == "sine.wav"
        assert data["language"] == "tr"
        assert data["size_bytes"] == os.path.getsize(wav_path)
