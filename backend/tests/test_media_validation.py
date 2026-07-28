"""Unit tests for _verify_media_stream (backend/server.py) — the real
content-based check that runs on every /api/transcribe upload, on top of the
extension check, so a plausible-looking extension with undecodable content
(especially .dav DVR/security-camera recordings) fails with a clear 400
instead of a confusing crash later in _prepare_chunks/_transcribe_local.

Like test_local_mode.py, these import server.py directly rather than hitting
a live server — _verify_media_stream doesn't need a running app, a database,
or any external API.

One thing genuinely exercised for real (not mocked): a valid, minimal Ogg/
Vorbis file is synthesized on the fly with PyAV's own encoder (no system
ffmpeg needed, same reason _decode_waveform_for_pyannote uses PyAV — see
server.py) to prove _verify_media_stream actually accepts real audio content,
not just that it rejects garbage. A real .dav fixture wasn't practical to
create/find (no accessible sample DVR recording, and PyAV has no encoder for
whatever proprietary codec a given DVR vendor uses) — the .dav-specific
error-message branch is tested with deliberately-undecodable bytes instead;
see README.md "Desteklenen formatlar" for the acknowledged best-effort caveat.
"""
import io
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture(autouse=True)
def _isolated_dotenv(monkeypatch):
    """See test_local_mode.py's fixture of the same name — same rationale:
    don't let a real backend/.env leak into these tests."""
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: None)


def _reload_server(monkeypatch):
    monkeypatch.setenv("API_KEY", "test-key")
    monkeypatch.delenv("TRANSCRIPTION_BACKEND", raising=False)
    monkeypatch.delenv("HF_TOKEN", raising=False)
    sys.modules.pop("server", None)
    import server
    return server


def _make_real_ogg_bytes() -> bytes:
    """Synthesize a real, minimal, valid Ogg/Vorbis file (1s of silence) —
    PyAV's built-in 'vorbis' encoder, no system ffmpeg required. 'strict':
    '-2' is needed because FFmpeg's native vorbis encoder is flagged
    experimental."""
    import av
    import numpy as np

    buf = io.BytesIO()
    container = av.open(buf, mode="w", format="ogg")
    stream = container.add_stream("vorbis", rate=16000)
    stream.codec_context.options = {"strict": "-2"}
    frame = av.AudioFrame.from_ndarray(
        np.zeros((1, 16000), dtype=np.float32), format="fltp", layout="mono"
    )
    frame.sample_rate = 16000
    for packet in stream.encode(frame):
        container.mux(packet)
    for packet in stream.encode(None):
        container.mux(packet)
    container.close()
    return buf.getvalue()


class TestVerifyMediaStream:
    def test_accepts_real_ogg_audio_content(self, monkeypatch):
        server = _reload_server(monkeypatch)
        real_ogg = _make_real_ogg_bytes()
        server._verify_media_stream(real_ogg, "ogg")  # must not raise

    def test_rejects_undecodable_ogg_with_generic_message(self, monkeypatch):
        server = _reload_server(monkeypatch)
        with pytest.raises(server.HTTPException) as exc_info:
            server._verify_media_stream(b"not actually ogg content", "ogg")
        assert exc_info.value.status_code == 400
        detail = exc_info.value.detail
        assert "Desteklenmeyen" not in detail  # extension check already passed
        assert "ses akışı bulunamadı" in detail.lower()

    def test_rejects_undecodable_dav_with_dvr_specific_message(self, monkeypatch):
        server = _reload_server(monkeypatch)
        with pytest.raises(server.HTTPException) as exc_info:
            server._verify_media_stream(b"not actually a dav recording", "dav")
        assert exc_info.value.status_code == 400
        detail = exc_info.value.detail
        assert "DVR" in detail
        assert "VLC" in detail

    def test_degrades_gracefully_without_pyav(self, monkeypatch):
        """If PyAV isn't installed (it's a transitive faster-whisper
        dependency, optional the same way local mode is — see server.py
        module note), content validation should skip rather than crash "api"
        mode's core upload path."""
        server = _reload_server(monkeypatch)
        import builtins
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "av":
                raise ImportError("simulated: PyAV not installed")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        server._verify_media_stream(b"anything at all", "ogg")  # must not raise

    def test_dav_extension_allowed(self, monkeypatch):
        server = _reload_server(monkeypatch)
        assert "dav" in server.ALLOWED_EXTS
        assert "dav" in server.DVR_EXTS

    def test_ogg_extension_allowed_flac_still_rejected(self, monkeypatch):
        server = _reload_server(monkeypatch)
        assert "ogg" in server.ALLOWED_EXTS
        assert "flac" not in server.ALLOWED_EXTS
