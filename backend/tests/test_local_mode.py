"""Unit tests for TRANSCRIPTION_BACKEND=local (backend/server.py local
transcription/diarization pipeline).

Unlike backend_test.py, these do NOT hit a live server — they import
server.py directly and (mostly) mock faster-whisper/pyannote.audio via
sys.modules injection, so they run without needing those heavy packages
actually installed, and without downloading any real model weights. The
one thing genuinely exercised for real is _align_and_format_diarization —
pure Python logic, no ML models involved.

Tests that need real model weights (actual transcription/diarization
quality, not just "does the code path run") are marked skip — see
TestLocalModeRealModels below and README.md "Local mode ile çalıştırma".
This was manually verified once, for real, while building this feature
(faster-whisper 'tiny' + a real HF token against test_fixtures/jfk.wav) —
see memory/PRD.md changelog for what that confirmed.
"""
import os
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

REQUIRES_REAL_MODELS = pytest.mark.skip(
    reason="Gerçek faster-whisper/pyannote.audio model indirmesi gerektirir "
           "(yüzlerce MB, ağ + zaman + gerçek bir HF_TOKEN). CI'da model "
           "indirme maliyeti nedeniyle atlanıyor — manuel doğrulama gerekli, "
           "bkz. README.md 'Local mode ile çalıştırma'."
)


@pytest.fixture(autouse=True)
def _isolated_dotenv(monkeypatch):
    """server.py calls load_dotenv(backend/.env) at import time — these
    tests fully control the environment via monkeypatch instead, so block
    that call. Otherwise a real backend/.env (with real secrets, e.g. a
    real HF_TOKEN) would leak into "missing env var" test cases and make
    them pass for the wrong reason."""
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: None)


def _reload_server():
    """server.py validates required env vars at import time — re-import
    fresh so each test's monkeypatched env actually takes effect."""
    sys.modules.pop("server", None)
    import server
    return server


def _fake_local_mode_env(monkeypatch):
    monkeypatch.setenv("API_KEY", "test-key")
    monkeypatch.setenv("TRANSCRIPTION_BACKEND", "local")
    monkeypatch.setenv("HF_TOKEN", "hf_test_token_not_real")


class TestLocalModeConfig:
    def test_default_backend_is_api_unchanged(self, monkeypatch):
        """TRANSCRIPTION_BACKEND unset → 'api', same as before this feature
        existed. The core "don't break existing behavior" guarantee."""
        monkeypatch.setenv("API_KEY", "test-key")
        monkeypatch.delenv("TRANSCRIPTION_BACKEND", raising=False)
        monkeypatch.delenv("HF_TOKEN", raising=False)
        server = _reload_server()
        assert server.TRANSCRIPTION_BACKEND == "api"

    def test_local_mode_requires_hf_token(self, monkeypatch):
        monkeypatch.setenv("API_KEY", "test-key")
        monkeypatch.setenv("TRANSCRIPTION_BACKEND", "local")
        monkeypatch.delenv("HF_TOKEN", raising=False)
        with pytest.raises(RuntimeError, match="HF_TOKEN"):
            _reload_server()

    def test_invalid_transcription_backend_rejected(self, monkeypatch):
        monkeypatch.setenv("API_KEY", "test-key")
        monkeypatch.setenv("TRANSCRIPTION_BACKEND", "not-a-real-backend")
        with pytest.raises(RuntimeError, match="Geçersiz TRANSCRIPTION_BACKEND"):
            _reload_server()

    def test_local_mode_imports_without_error(self, monkeypatch):
        """The specific check the task asked for: server.py itself must
        import cleanly in local mode. faster_whisper/pyannote.audio are
        lazy-imported inside functions (see server.py comment above
        _get_local_whisper_model) — NOT at module scope — so this must
        succeed even without those packages installed."""
        _fake_local_mode_env(monkeypatch)
        # Explicitly clear WHISPER_MODEL_SIZE: when this file runs in the same
        # xdist worker as backend_test.py, that module's load_dotenv(backend/.env)
        # call has already populated os.environ for the whole process — and
        # backend/.env may have WHISPER_MODEL_SIZE=tiny set (used for faster
        # manual local-mode testing) — which would otherwise leak in here and
        # break this test's assertion about the *default* value non-deterministically.
        monkeypatch.delenv("WHISPER_MODEL_SIZE", raising=False)
        server = _reload_server()
        assert server.TRANSCRIPTION_BACKEND == "local"
        assert server.WHISPER_MODEL_SIZE == "small"
        assert server.HF_TOKEN == "hf_test_token_not_real"


class TestAlignAndFormatDiarization:
    """Pure Python logic (time-overlap matching + text formatting) — no ML
    models involved, so tested for real rather than mocked."""

    def test_single_speaker_returns_none(self, monkeypatch):
        _fake_local_mode_env(monkeypatch)
        server = _reload_server()
        whisper_segments = [{"start": 0.0, "end": 2.0, "text": "Merhaba"}]
        diar_segments = [{"start": 0.0, "end": 2.0, "speaker": "SPEAKER_00"}]
        assert server._align_and_format_diarization(whisper_segments, diar_segments) is None

    def test_two_speakers_formatted_and_numbered_by_first_appearance(self, monkeypatch):
        _fake_local_mode_env(monkeypatch)
        server = _reload_server()
        # SPEAKER_01 talks first (0-2s), SPEAKER_00 second (2-4s) — numbering
        # must follow appearance order (1. kişi / 2. kişi), not the raw label.
        whisper_segments = [
            {"start": 0.0, "end": 1.0, "text": "Merhaba,"},
            {"start": 1.0, "end": 2.0, "text": "nasılsın?"},
            {"start": 2.0, "end": 3.0, "text": "İyiyim,"},
            {"start": 3.0, "end": 4.0, "text": "sen nasılsın?"},
        ]
        diar_segments = [
            {"start": 0.0, "end": 2.0, "speaker": "SPEAKER_01"},
            {"start": 2.0, "end": 4.0, "speaker": "SPEAKER_00"},
        ]
        result = server._align_and_format_diarization(whisper_segments, diar_segments)
        assert result == "1. kişi: Merhaba, nasılsın?\n2. kişi: İyiyim, sen nasılsın?"

    def test_empty_inputs_return_none(self, monkeypatch):
        _fake_local_mode_env(monkeypatch)
        server = _reload_server()
        assert server._align_and_format_diarization([], []) is None
        assert server._align_and_format_diarization(
            [{"start": 0.0, "end": 1.0, "text": "x"}], []
        ) is None


class TestLocalPipelineMocked:
    """faster-whisper / pyannote.audio injected via sys.modules — these
    tests never touch the real packages or download anything, and pass
    whether or not faster-whisper/pyannote.audio are actually installed."""

    def test_transcribe_local_calls_faster_whisper_and_shapes_output(self, monkeypatch):
        _fake_local_mode_env(monkeypatch)
        server = _reload_server()

        fake_segment = MagicMock(start=0.0, end=1.5, text=" Merhaba dünya ")
        fake_model = MagicMock()
        fake_pipeline_instance = MagicMock()
        fake_pipeline_instance.transcribe.return_value = ([fake_segment], MagicMock())
        fake_module = types.ModuleType("faster_whisper")
        fake_module.WhisperModel = MagicMock(return_value=fake_model)
        fake_module.BatchedInferencePipeline = MagicMock(return_value=fake_pipeline_instance)

        with patch.dict(sys.modules, {"faster_whisper": fake_module}):
            raw_text, segments = server._transcribe_local(b"fake audio bytes", "wav", "tr")

        fake_module.WhisperModel.assert_called_once_with(
            server.WHISPER_MODEL_SIZE, device="cpu", compute_type="int8",
            cpu_threads=server._local_cpu_threads(),
        )
        fake_module.BatchedInferencePipeline.assert_called_once_with(model=fake_model)
        fake_pipeline_instance.transcribe.assert_called_once()
        call_kwargs = fake_pipeline_instance.transcribe.call_args.kwargs
        assert call_kwargs.get("language") == "tr"
        assert call_kwargs.get("vad_filter") is True
        assert call_kwargs.get("batch_size") == server.WHISPER_BATCH_SIZE
        assert raw_text == "Merhaba dünya"
        assert segments == [{"start": 0.0, "end": 1.5, "text": "Merhaba dünya"}]

    def test_local_cpu_threads_uses_sched_affinity_not_cpu_count(self, monkeypatch):
        """Regression test for the oversubscription bug: os.cpu_count() reports
        the host's total cores and ignores cgroup/container/taskset limits,
        which caused worse wall-clock time on a CPU-limited VPS (measured in
        BENCHMARK.md) than the real, affinity-aware thread count."""
        _fake_local_mode_env(monkeypatch)
        server = _reload_server()
        monkeypatch.setattr(server.os, "sched_getaffinity", lambda pid: set(range(4)), raising=False)
        monkeypatch.setattr(server.os, "cpu_count", lambda: 64)
        assert server._local_cpu_threads() == 4

    def test_diarize_local_calls_pyannote_with_token(self, monkeypatch):
        _fake_local_mode_env(monkeypatch)
        server = _reload_server()

        # _diarize_local calls pipeline(audio_input) → a DiarizeOutput-like
        # object whose .speaker_diarization is the Annotation with
        # .itertracks() (pyannote.audio 4.x — see server.py comment).
        fake_turn = MagicMock(start=0.0, end=2.0)
        fake_pipeline_instance = MagicMock()
        fake_pipeline_instance.return_value.speaker_diarization.itertracks.return_value = [
            (fake_turn, None, "SPEAKER_00")
        ]
        fake_pipeline_cls = MagicMock()
        fake_pipeline_cls.from_pretrained = MagicMock(return_value=fake_pipeline_instance)

        fake_pyannote_pkg = types.ModuleType("pyannote")
        fake_pyannote_audio = types.ModuleType("pyannote.audio")
        fake_pyannote_audio.Pipeline = fake_pipeline_cls

        # _decode_waveform_for_pyannote (PyAV/torch/numpy) is mocked too —
        # this test is about _diarize_local's own logic (pipeline call +
        # output shaping), not audio decoding, which has no ML models
        # involved and doesn't need mocking to be fast/deterministic
        # (covered by the real end-to-end manual run — see PRD.md changelog).
        fake_waveform_dict = {"waveform": "fake-tensor", "sample_rate": 16000}
        with patch.dict(sys.modules, {
            "pyannote": fake_pyannote_pkg,
            "pyannote.audio": fake_pyannote_audio,
        }), patch.object(server, "_decode_waveform_for_pyannote", return_value=fake_waveform_dict):
            segments = server._diarize_local(b"fake audio bytes", "wav")

        fake_pipeline_cls.from_pretrained.assert_called_once_with(
            "pyannote/speaker-diarization-3.1", token=server.HF_TOKEN,
        )
        fake_pipeline_instance.assert_called_once_with(fake_waveform_dict)
        assert segments == [{"start": 0.0, "end": 2.0, "speaker": "SPEAKER_00"}]


class TestLocalModeDiarizationDisabled:
    """Diarization is currently disabled in local mode (CPU-time cost on the
    target VPS, no GPU) — /api/transcribe must not call _diarize_local and
    must always return diarized_text: None. _diarize_local /
    _align_and_format_diarization themselves are left untouched (see
    server.py comment above the commented-out call) so this is purely about
    the endpoint not invoking them — see CLAUDE.md "Bilinen Kritik Sorunlar"
    for how to re-enable."""

    def test_transcribe_endpoint_never_calls_diarize_local(self, monkeypatch):
        from fastapi.testclient import TestClient

        _fake_local_mode_env(monkeypatch)
        server = _reload_server()

        fake_whisper_segments = [{"start": 0.0, "end": 1.0, "text": "Merhaba"}]
        with patch.object(
            server, "_transcribe_local", return_value=("Merhaba", fake_whisper_segments)
        ) as mock_transcribe, patch.object(
            server, "_diarize_local"
        ) as mock_diarize, patch.object(
            server, "_align_and_format_diarization"
        ) as mock_align:
            client = TestClient(server.app)
            resp = client.post(
                "/api/transcribe",
                headers={"X-API-Key": "test-key"},
                files={"file": ("test.wav", b"fake wav bytes", "audio/wav")},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["text"] == "Merhaba"
        assert body["diarized_text"] is None
        mock_transcribe.assert_called_once()
        mock_diarize.assert_not_called()
        mock_align.assert_not_called()


@REQUIRES_REAL_MODELS
class TestLocalModeRealModels:
    """Placeholders documenting what manual verification covers — not
    meant to run in CI. See the module docstring and README.md."""

    def test_real_transcription_quality(self):
        pass

    def test_real_diarization_and_speaker_alignment(self):
        pass
