import os
import io
import math
import tempfile
import uuid
import logging
from pathlib import Path
from typing import Optional, List

from fastapi import FastAPI, APIRouter, UploadFile, File, Form, Header, Depends, HTTPException, Request
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from emergentintegrations.llm.openai import OpenAISpeechToText
from emergentintegrations.llm.chat import LlmChat, UserMessage
from pydub import AudioSegment


ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# API_KEY gates POST /api/transcribe (the only costly/abusable endpoint — see
# SECURITY_NOTES.md). Required at startup, same fail-fast pattern as other
# required env vars: a missing key would otherwise silently accept ALL
# requests (empty string never equals a real header value, but better to
# refuse to start than rely on that).
API_KEY = os.environ.get('API_KEY')
if not API_KEY:
    raise RuntimeError(
        "Eksik zorunlu ortam değişkeni: API_KEY. backend/.env dosyasında tanımlanmalı."
    )

# TRANSCRIPTION_BACKEND selects the transcription/diarization backend:
#   "api"   (default) — OpenAI Whisper API + Claude diarization, unchanged
#            behavior, requires EMERGENT_LLM_KEY (checked per-request below).
#   "local" — faster-whisper + pyannote.audio, fully offline after the first
#            model download, requires HF_TOKEN (checked here, fail-fast).
# See _transcribe_local/_diarize_local below and README.md "Local mode".
TRANSCRIPTION_BACKEND = os.environ.get('TRANSCRIPTION_BACKEND', 'api').strip().lower()
if TRANSCRIPTION_BACKEND not in ('api', 'local'):
    raise RuntimeError(
        f"Geçersiz TRANSCRIPTION_BACKEND: {TRANSCRIPTION_BACKEND!r}. "
        f"'api' veya 'local' olmalı."
    )

WHISPER_MODEL_SIZE = os.environ.get('WHISPER_MODEL_SIZE', 'small')
# Batch size for faster-whisper's BatchedInferencePipeline (batches the
# VAD-detected speech segments together instead of transcribing them one at a
# time — see _get_local_whisper_pipeline). Benchmarked on a ~2min multi-segment
# clip: 4/8/16 performed within noise of each other (this fixture only had ~9
# segments), 8 is a safe default that also has headroom for longer/busier
# real-world recordings without ballooning memory. See BENCHMARK.md.
WHISPER_BATCH_SIZE = int(os.environ.get('WHISPER_BATCH_SIZE', '8'))

# Per-request quality/speed trade-off for local mode (see /api/transcribe's
# quality_mode form field). "precise" always means large-v3-turbo, regardless
# of WHISPER_MODEL_SIZE — benchmarked at ~3x slower than 'small' but more
# accurate on harder/noisier audio in some cases, see BENCHMARK.md "Bulgu 4".
QUALITY_MODE_STANDARD = "standard"
QUALITY_MODE_PRECISE = "precise"
QUALITY_MODES = (QUALITY_MODE_STANDARD, QUALITY_MODE_PRECISE)
PRECISE_MODEL_SIZE = "large-v3-turbo"

HF_TOKEN = os.environ.get('HF_TOKEN')
if TRANSCRIPTION_BACKEND == 'local' and not HF_TOKEN:
    raise RuntimeError(
        "HF_TOKEN gerekli, https://huggingface.co/pyannote/speaker-diarization-3.1 "
        "şartlarını kabul edip token oluşturun"
    )

app = FastAPI()
api_router = APIRouter(prefix="/api")

# Rate limiting (slowapi, in-memory / per-process — fine for a single-instance
# MVP deploy; switch to a Redis storage backend if/when this runs behind a
# load balancer with multiple workers). Limit chosen and documented in
# SECURITY_NOTES.md — change RATE_LIMIT below and there in tandem.
RATE_LIMIT = "5/minute"
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter


async def _rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={"detail": f"Çok fazla istek gönderildi. Lütfen bir süre sonra tekrar deneyin. (limit: {RATE_LIMIT})"},
    )


app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)


async def require_api_key(x_api_key: Optional[str] = Header(default=None, alias="X-API-Key")):
    if not x_api_key or x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Geçersiz veya eksik API anahtarı (X-API-Key).")

# --- Config -----------------------------------------------------------------
# MAX_UPLOAD_SIZE is the single source of truth for the user-facing upload
# cap (frontend/src/pages/Transcriber.jsx MAX_SIZE_MB mirrors this value
# manually — the two apps don't share a package, so keep them in sync by
# hand when this changes). WHISPER_LIMIT is a separate, fixed technical
# constant (OpenAI Whisper's real per-request size cap) — never a user-facing
# setting; files above it are chunked, not rejected.
MAX_UPLOAD_SIZE = 500 * 1024 * 1024                # 500 MB accepted (source of truth, see above)
WHISPER_LIMIT = 25 * 1024 * 1024                   # OpenAI Whisper per-request limit (fixed by provider)
CHUNK_TARGET_BYTES = 20 * 1024 * 1024              # keep each chunk safely under 25 MB
# Formats natively accepted by OpenAI Whisper (no transcode needed)
WHISPER_NATIVE_EXTS = {"mp3", "wav", "m4a", "webm", "mp4", "mpeg", "mpga"}

# Additional audio containers we accept — ffmpeg/pydub decodes then we transcode to MP3
# NOTE: flac intentionally still excluded — see memory/PRD.md backlog (P2,
# server-side transcoding kept off, no decision to reverse it here).
# .ogg WAS excluded for the same reason (raw 500 in production, most likely
# ffmpeg/ffprobe not confirmed present) but is re-enabled here now that (a)
# infra-agent's Docker build already verified ffmpeg is present in the deploy
# image, and (b) _verify_media_stream() below independently probes real
# stream content before transcoding — the two things blocking re-enablement
# are both addressed. flac stays out; that's a separate, deliberate call, not
# revisited by this change. See CLAUDE.md "Bilinen Kritik Sorunlar".
EXTRA_AUDIO_EXTS = {
    "ogg", "oga", "opus", "aac", "wma",
    "aiff", "aif", "aifc", "amr", "ac3", "au", "caf",
    "3ga", "voc", "ra", "mka", "dts", "wv", "mp2",
}

# Video containers — audio track is extracted with ffmpeg and transcribed
VIDEO_EXTS = {
    "mov", "avi", "mkv", "wmv", "flv", "3gp", "3g2",
    "m4v", "mpg", "mpe", "vob", "ogv", "mts", "m2ts",
    "ts", "asf", "rm", "rmvb", "f4v", "divx", "xvid",
}

# DVR/security-camera recording containers — vendor-specific (Dahua and
# similar NVR/DVR systems use .dav), typically H.264 video + G.711/G.726
# audio wrapped in a non-standard container. ffmpeg/libav CAN decode most of
# these but it's genuinely best-effort, not guaranteed (unlike the other
# sets above, which are all standard containers) — hence _verify_media_stream
# gives .dav uploads a distinct, actionable error message on failure instead
# of the generic one. See CLAUDE.md "Bilinen Kritik Sorunlar".
DVR_EXTS = {"dav"}

# Readability-only line breaking for the `text` field (NOT diarization/speaker
# labeling — see _format_transcript_with_pauses below and
# _align_and_format_diarization for the separate, currently-disabled speaker
# feature). A gap between two Whisper segments longer than this is treated as
# a natural pause worth a line break. Picked as a reasoned middle ground, not
# a benchmarked value (no annotated pause dataset available): normal
# within-sentence breathing pauses in spoken audio are usually well under 1s,
# while a deliberate pause between sentences/thoughts (interview answers,
# topic changes — this app's target content) tends to run 1.5s+. 1.3s sits
# between the two so it doesn't fragment mid-sentence but still catches real
# breaks. Adjust here (not via env — see CLAUDE.md/README.md) if it over- or
# under-splits on your audio.
PAUSE_THRESHOLD_SECONDS = 1.3

ALLOWED_EXTS = WHISPER_NATIVE_EXTS | EXTRA_AUDIO_EXTS | VIDEO_EXTS | DVR_EXTS

# Whisper (whisper-1) supports natively: mp3, mp4, mpeg, mpga, m4a, wav, webm.
# Everything else is decoded via ffmpeg/pydub and re-encoded to MP3 before Whisper.

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')


def _get_ext(filename: str) -> str:
    if not filename or '.' not in filename:
        return ''
    return filename.rsplit('.', 1)[-1].lower()


def _format_transcript_with_pauses(segments: List[dict]) -> str:
    """Join segment texts, inserting a newline wherever the gap between two
    consecutive segments exceeds PAUSE_THRESHOLD_SECONDS.

    Readability-only line breaking — NOT diarization. No speaker labels
    ("1. kişi" etc.) are added here; that's a separate, currently-disabled
    feature (_align_and_format_diarization). `segments` is a chronological
    list of {"start": float, "end": float, "text": str} dicts — the same
    shape _transcribe_local's whisper_segments already uses.
    """
    if not segments:
        return ""

    lines: List[str] = []
    current_parts: List[str] = [segments[0]["text"]]
    for prev_seg, seg in zip(segments, segments[1:]):
        gap = seg["start"] - prev_seg["end"]
        if gap > PAUSE_THRESHOLD_SECONDS:
            lines.append(" ".join(current_parts).strip())
            current_parts = [seg["text"]]
        else:
            current_parts.append(seg["text"])
    lines.append(" ".join(current_parts).strip())

    return "\n".join(line for line in lines if line)


def _normalize_openai_segments(raw_items, text_key: str = "text") -> List[dict]:
    """Normalize OpenAI Whisper API `verbose_json` segments or words (a list
    of dicts, or pydantic-like objects depending on the litellm/emergent-
    proxy response shape) into the plain {"start": float, "end": float,
    "text": str} shape _format_transcript_with_pauses expects. Word items use
    the key "word" instead of "text" for their text — text_key selects which."""
    normalized: List[dict] = []
    for item in raw_items or []:
        get = item.get if isinstance(item, dict) else lambda k, d=None: getattr(item, k, d)
        text = (get(text_key, "") or "").strip()
        if text:
            normalized.append({"start": get("start", 0.0), "end": get("end", 0.0), "text": text})
    return normalized


def _verify_media_stream(raw_bytes: bytes, ext: str) -> None:
    """Confirm the upload actually contains a decodable audio stream — not
    just a plausible file extension.

    A correct extension doesn't guarantee decodable content, especially for
    non-standard containers (.dav DVR/security-camera recordings above all):
    the codec inside can be unsupported even though the container "looks"
    right. Catching that here gives a clear 400 instead of a confusing crash
    later in _prepare_chunks (pydub/ffmpeg) or _transcribe_local
    (faster-whisper).

    Uses PyAV (`av`) rather than shelling out to the `ffprobe` CLI: PyAV
    bundles its own statically-linked libav — the same decoding machinery
    ffprobe is built on — so this works without requiring a system
    ffmpeg/ffprobe binary on PATH (see _decode_waveform_for_pyannote's
    docstring for the same rationale elsewhere in this file). `av` is a
    transitive dependency of faster-whisper, so it's optional the same way
    faster-whisper/pyannote.audio are: if it's not installed, this degrades
    to the previous extension-only check rather than hard-failing "api" mode.
    """
    try:
        import av  # lazy: see local-mode module note above
    except ImportError:
        logger.warning(
            "PyAV not installed — skipping media stream content validation "
            "(falling back to extension-only check) for .%s upload.", ext,
        )
        return

    try:
        container = av.open(io.BytesIO(raw_bytes))
        try:
            has_audio = len(container.streams.audio) > 0
        finally:
            container.close()
    except Exception as e:
        logger.warning("Media stream probe failed for .%s upload: %s", ext, e)
        has_audio = False

    if has_audio:
        return

    if ext in DVR_EXTS:
        raise HTTPException(
            status_code=400,
            detail="Bu DVR kaydı işlenemedi, codec desteklenmiyor olabilir — "
                   "VLC ile standart bir formata (mp4/mp3) dönüştürüp tekrar "
                   "deneyin.",
        )
    raise HTTPException(
        status_code=400,
        detail=f"Dosyada işlenebilir bir ses akışı bulunamadı (.{ext}). "
               f"Dosya bozuk olabilir veya bu codec desteklenmiyor olabilir.",
    )


def _prepare_chunks(raw_bytes: bytes, ext: str) -> List[bytes]:
    """Decode audio with pydub, downsample to mono 16 kHz MP3 (64 kbps),
    and split into ≤ CHUNK_TARGET_BYTES pieces.

    Returns a list of MP3 byte payloads ready to send to Whisper.
    """
    # pydub uses file extension hints; write to a temp file so it can detect containers
    with tempfile.NamedTemporaryFile(delete=False, suffix=f".{ext}") as tmp:
        tmp.write(raw_bytes)
        tmp_path = tmp.name
    try:
        audio: AudioSegment = AudioSegment.from_file(tmp_path)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    # Normalize for smaller size and better low-quality speech recognition
    audio = audio.set_channels(1).set_frame_rate(16000)

    duration_ms = len(audio)
    if duration_ms <= 0:
        raise HTTPException(status_code=400, detail="Ses dosyasında geçerli içerik bulunamadı.")

    # Encode once to gauge bitrate/size
    def _export_mp3(seg: AudioSegment) -> bytes:
        buf = io.BytesIO()
        seg.export(buf, format="mp3", bitrate="64k", parameters=["-ac", "1"])
        return buf.getvalue()

    full = _export_mp3(audio)
    if len(full) <= CHUNK_TARGET_BYTES:
        return [full]

    # Determine chunk duration based on encoded bitrate
    # bytes_per_ms ≈ len(full) / duration_ms
    bytes_per_ms = len(full) / duration_ms
    chunk_ms = int(CHUNK_TARGET_BYTES / bytes_per_ms * 0.95)  # 5% safety margin
    # never smaller than 30 s
    chunk_ms = max(chunk_ms, 30_000)

    chunks: List[bytes] = []
    num_chunks = math.ceil(duration_ms / chunk_ms)
    for i in range(num_chunks):
        start = i * chunk_ms
        end = min(start + chunk_ms, duration_ms)
        segment = audio[start:end]
        payload = _export_mp3(segment)
        # If somehow still too big, re-split that piece in half recursively (rare)
        if len(payload) > WHISPER_LIMIT:
            half = (end - start) // 2
            for sub in (audio[start:start + half], audio[start + half:end]):
                chunks.append(_export_mp3(sub))
        else:
            chunks.append(payload)
    return chunks


async def _diarize_with_claude(raw_text: str, api_key: str) -> Optional[str]:
    """Use Claude to detect speaker turns from the raw transcript and produce
    a labeled version like "1. kişi: … / 2. kişi: …".

    Returns None if the LLM says there is only a single speaker or if the call
    fails. Never raises to the caller.
    """
    text = (raw_text or "").strip()
    if len(text) < 40:  # too short to meaningfully diarize
        return None

    system_msg = (
        "Sen bir konuşma çözümleme asistanısın. Sana Whisper tarafından "
        "üretilmiş bir Türkçe transkripsiyon veriliyor. Görevin: metindeki "
        "konuşmacı değişimlerini içerik ipuçlarından (soru-cevap, hitap, "
        "üslup, konu değişimi) tespit etmek ve konuşmayı '1. kişi:', "
        "'2. kişi:' vb. etiketlerle satır satır yeniden yazmak.\n\n"
        "Kurallar:\n"
        "- Sadece etiketli konuşmayı döndür, başka açıklama ekleme.\n"
        "- Her konuşmacı değişiminde yeni satıra geç. Aynı konuşmacı "
        "devam ediyorsa satırları birleştir.\n"
        "- Konuşmacı sayısını olduğu kadar tut; uydurma yeni konuşmacı ekleme.\n"
        "- Eğer metinde açıkça tek bir konuşmacı varsa (monolog), tam olarak "
        "şu tek kelimeyi döndür: TEK_KONUSMACI\n"
        "- Metin içeriğini değiştirme; sadece konuşmacılara göre böl ve "
        "gerekirse noktalama düzelt."
    )
    user_msg = UserMessage(text=text)

    try:
        chat = LlmChat(
            api_key=api_key,
            session_id=f"diarize-{uuid.uuid4()}",
            system_message=system_msg,
        ).with_model("anthropic", "claude-sonnet-4-6")

        reply = await chat.send_message(user_msg)
        reply_text = (reply or "").strip()
        if not reply_text or reply_text.upper().startswith("TEK_KONUSMACI"):
            return None
        return reply_text
    except Exception:
        logger.exception("Diarization failed")
        return None


# --- Local transcription/diarization backend (TRANSCRIPTION_BACKEND=local) --
# faster-whisper and pyannote.audio are heavy (pyannote alone pulls in torch)
# and entirely optional — imported lazily inside the functions below, not at
# module scope, so "api" mode (the default) keeps working even on an install
# that never ran `pip install faster-whisper pyannote.audio`. Models are
# loaded once and cached in these module-level globals (loading a Whisper/
# pyannote model takes real time — must not happen per-request).
_local_whisper_models: dict = {}     # quality_mode -> WhisperModel
_local_whisper_pipelines: dict = {}  # quality_mode -> BatchedInferencePipeline
_local_diarization_pipeline = None


def _local_cpu_threads() -> int:
    """Number of CPU threads ctranslate2 should actually use.

    Deliberately NOT os.cpu_count(): that returns the host machine's total
    core count and ignores cgroup/container CPU limits (Docker --cpus,
    a VPS's cpuset, taskset, ...). On a 4-vCPU container running on a bigger
    host, os.cpu_count() over-reports, so cpu_threads=os.cpu_count() spins up
    more OpenMP threads than are actually schedulable — verified this
    directly causes worse wall-clock time (thread oversubscription/contention)
    than passing the real, affinity-limited count. os.sched_getaffinity(0) is
    the standard cgroup/taskset-aware way to get the usable core count on
    Linux. See BENCHMARK.md for the measurement.
    """
    try:
        return len(os.sched_getaffinity(0))
    except AttributeError:
        return os.cpu_count() or 4  # sched_getaffinity is Linux-only


def _model_size_for_quality(quality_mode: str) -> str:
    """Resolve a quality_mode ("standard"/"precise") to an actual
    faster-whisper model size. "precise" is always PRECISE_MODEL_SIZE
    (large-v3-turbo), independent of WHISPER_MODEL_SIZE — see BENCHMARK.md
    "Bulgu 4"."""
    if quality_mode == QUALITY_MODE_PRECISE:
        return PRECISE_MODEL_SIZE
    return WHISPER_MODEL_SIZE


def _get_local_whisper_model(quality_mode: str):
    """Lazily load (and cache) the local faster-whisper model for the given
    quality_mode, keyed separately so "standard" and "precise" don't evict
    each other — but also so a request for one mode never loads the other:
    only the mode(s) actually requested end up resident in memory at once.

    First call downloads the model into the huggingface_hub cache
    (~/.cache/huggingface by default); later calls — including after a
    process restart — reuse that cache and need no network access.
    """
    if quality_mode not in _local_whisper_models:
        from faster_whisper import WhisperModel  # lazy: see module note above

        model_size = _model_size_for_quality(quality_mode)
        logger.info(
            "Loading local Whisper model '%s' (quality_mode=%s, cpu, int8) — "
            "first run downloads it, may take a while...", model_size, quality_mode,
        )
        _local_whisper_models[quality_mode] = WhisperModel(
            model_size, device="cpu", compute_type="int8",
            cpu_threads=_local_cpu_threads(),
        )
    return _local_whisper_models[quality_mode]


def _get_local_whisper_pipeline(quality_mode: str):
    """Lazily wrap the faster-whisper model for this quality_mode in a
    BatchedInferencePipeline (cached alongside the model — same lifetime,
    same underlying weights, same per-quality_mode cache key).

    Batching groups the VAD-detected speech segments together instead of
    running the encoder/decoder once per segment sequentially — on a ~2min
    multi-segment benchmark clip this cut wall-clock time by ~7-8x on a
    4-core box (81s → 11s for the 'small' model) because a single segment's
    decode loop doesn't parallelize across cores well, while a batch of
    segments does. See BENCHMARK.md.
    """
    if quality_mode not in _local_whisper_pipelines:
        from faster_whisper import BatchedInferencePipeline  # lazy: see module note above

        _local_whisper_pipelines[quality_mode] = BatchedInferencePipeline(
            model=_get_local_whisper_model(quality_mode)
        )
    return _local_whisper_pipelines[quality_mode]


def _get_local_diarization_pipeline():
    """Lazily load (and cache) the local pyannote.audio diarization pipeline.

    HF_TOKEN presence was already validated at startup (module load) when
    TRANSCRIPTION_BACKEND=local — see top of file.
    """
    global _local_diarization_pipeline
    if _local_diarization_pipeline is None:
        from pyannote.audio import Pipeline  # lazy: see module note above

        logger.info("Loading pyannote/speaker-diarization-3.1 pipeline...")
        # pyannote.audio 4.x renamed from_pretrained's auth kwarg from
        # use_auth_token to token (matches current huggingface_hub convention).
        _local_diarization_pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1", token=HF_TOKEN,
        )
    return _local_diarization_pipeline


def _transcribe_local(raw_bytes: bytes, ext: str, lang_code: Optional[str], quality_mode: str):
    """Run faster-whisper directly on the uploaded bytes.

    quality_mode selects which cached model/pipeline to use — see
    _get_local_whisper_pipeline/_model_size_for_quality.

    Returns (raw_text, whisper_segments) where whisper_segments is a list of
    {"start": float, "end": float, "text": str} at Whisper's own (sentence/
    phrase-level) segment granularity — this is what pyannote's diarization
    output aligns against in _align_and_format_diarization(), and its shape
    is unchanged by this function.

    raw_text is NOT simply these segments joined — it's built from per-WORD
    timestamps instead (word_timestamps=True below) purely to find natural
    pauses (_format_transcript_with_pauses). This was a real, tested finding
    while building the feature: with BatchedInferencePipeline,
    VAD-separated speech chunks can get merged back into a single coarse
    Segment spanning a multi-second silence (verified: a synthetic clip with
    a 3s gap came back as ONE segment covering the whole clip) — so gaps
    between Segment.start/end are NOT a reliable pause signal here. Gaps
    between consecutive WORDS' timestamps are — they correctly exposed the
    same 3s gap in that test. See BENCHMARK.md.
    """
    pipeline = _get_local_whisper_pipeline(quality_mode)
    with tempfile.NamedTemporaryFile(delete=False, suffix=f".{ext}") as tmp:
        tmp.write(raw_bytes)
        tmp_path = tmp.name
    try:
        segments_iter, _info = pipeline.transcribe(
            tmp_path,
            language=lang_code,
            vad_filter=True,  # required by BatchedInferencePipeline — also
            # skips silence, avoiding hallucinated text on silent stretches
            # (never changes accuracy on real speech).
            batch_size=WHISPER_BATCH_SIZE,
            word_timestamps=True,  # see docstring above — needed for
            # reliable pause detection, NOT used for diarization alignment.
            # beam_size intentionally left at faster-whisper's default: this
            # is an accuracy/speed trade-off and accuracy is prioritized here.
        )
        whisper_segments: List[dict] = []
        words: List[dict] = []
        for seg in segments_iter:
            text = (seg.text or "").strip()
            if text:
                whisper_segments.append({"start": seg.start, "end": seg.end, "text": text})
            for w in (seg.words or []):
                word_text = (w.word or "").strip()
                if word_text:
                    words.append({"start": w.start, "end": w.end, "text": word_text})
        raw_text = _format_transcript_with_pauses(words or whisper_segments)
        return raw_text, whisper_segments
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def _decode_waveform_for_pyannote(raw_bytes: bytes):
    """Decode raw audio bytes into the {'waveform': torch.Tensor (1, time)
    float32 in [-1, 1], 'sample_rate': int} dict pyannote.audio accepts
    directly (see pyannote.audio.core.io.Audio.__call__).

    Decoding is done via PyAV (bundled with faster-whisper, statically
    linked — no system ffmpeg needed), NOT by handing pyannote a file path:
    pyannote.audio 4.x reads files via torchcodec, which dynamically links
    against system libavutil/libavcodec — if those aren't installed (as on
    this dev machine; they ARE installed via backend/Dockerfile's `apt-get
    install ffmpeg` in the Docker image), file-path input raises
    "torchcodec is not available". Decoding ourselves sidesteps that
    entirely, matching the workaround pyannote's own error message suggests.
    """
    import av  # lazy: bundled with faster-whisper, see module note above
    import torch
    import numpy as np

    container = av.open(io.BytesIO(raw_bytes))
    stream = container.streams.audio[0]
    resampler = av.AudioResampler(format="s16", layout="mono", rate=stream.rate)
    chunks = []
    for frame in container.decode(stream):
        for rframe in resampler.resample(frame):
            chunks.append(rframe.to_ndarray())
    container.close()

    samples = np.concatenate(chunks, axis=1) if chunks else np.zeros((1, 0), dtype=np.int16)
    waveform = torch.from_numpy(samples.astype(np.float32) / 32768.0)
    return {"waveform": waveform, "sample_rate": stream.rate}


def _diarize_local(raw_bytes: bytes, ext: str) -> List[dict]:
    """Run pyannote.audio on the uploaded bytes, return a list of
    {"start": float, "end": float, "speaker": str} turns."""
    pipeline = _get_local_diarization_pipeline()
    audio_input = _decode_waveform_for_pyannote(raw_bytes)
    output = pipeline(audio_input)
    # pyannote.audio 4.x wraps the result in a DiarizeOutput dataclass
    # instead of returning an Annotation directly (3.x behavior) —
    # .speaker_diarization is the Annotation with .itertracks().
    annotation = getattr(output, "speaker_diarization", output)
    return [
        {"start": turn.start, "end": turn.end, "speaker": speaker}
        for turn, _, speaker in annotation.itertracks(yield_label=True)
    ]


def _align_and_format_diarization(
    whisper_segments: List[dict], diar_segments: List[dict]
) -> Optional[str]:
    """Assign each Whisper segment to the pyannote speaker turn with the
    largest time overlap, then render "1. kişi: … / 2. kişi: …" blocks —
    the exact same textual format _diarize_with_claude() produces, so the
    frontend (which parses this format — see Transcriber.jsx DiarizedText)
    needs no changes regardless of which backend produced it.

    Returns None if there's nothing to align (mirrors _diarize_with_claude
    returning None for TEK_KONUSMACI / single-speaker audio) — same contract,
    same frontend handling either way.
    """
    if not whisper_segments or not diar_segments:
        return None

    speaker_order: List[str] = []  # first-appearance order → "1. kişi", "2. kişi", ...
    labeled: List[tuple] = []
    for seg in whisper_segments:
        best_speaker, best_overlap = None, 0.0
        for d in diar_segments:
            overlap = min(seg["end"], d["end"]) - max(seg["start"], d["start"])
            if overlap > best_overlap:
                best_overlap, best_speaker = overlap, d["speaker"]
        if best_speaker is None:
            continue
        if best_speaker not in speaker_order:
            speaker_order.append(best_speaker)
        labeled.append((best_speaker, seg["text"]))

    if len(speaker_order) < 2:
        return None  # single speaker (or no confident overlap match)

    speaker_number = {spk: i + 1 for i, spk in enumerate(speaker_order)}

    lines: List[str] = []
    current_speaker = None
    current_texts: List[str] = []
    for speaker, text in labeled:
        if speaker != current_speaker:
            if current_texts:
                lines.append(f"{speaker_number[current_speaker]}. kişi: {' '.join(current_texts)}")
            current_speaker = speaker
            current_texts = [text]
        else:
            current_texts.append(text)
    if current_texts:
        lines.append(f"{speaker_number[current_speaker]}. kişi: {' '.join(current_texts)}")

    return "\n".join(lines)


@api_router.get("/")
async def root():
    return {"message": "SesDeşifre API"}


@api_router.get("/health")
async def health():
    return {"status": "ok", "service": "transcription"}


@api_router.post("/transcribe", dependencies=[Depends(require_api_key)])
@limiter.limit(RATE_LIMIT)
async def transcribe_audio(
    request: Request,  # required by @limiter.limit to key on client IP
    file: UploadFile = File(...),
    language: Optional[str] = Form(default="tr"),
    quality_mode: str = Form(default=QUALITY_MODE_STANDARD),
):
    """Transcribe an audio (or video) file using OpenAI Whisper.

    Requires a valid `X-API-Key` header (see require_api_key) and is rate
    limited to RATE_LIMIT per client IP (see SECURITY_NOTES.md).

    - Accepts most audio and video formats (mp3, wav, m4a, webm, opus, ogg,
      aac, wma, aiff, amr, mov, avi, mkv, mp4, wmv, flv, 3gp, mkv, mpg, …) plus
      DVR/security-camera recordings (.dav — best-effort, see DVR_EXTS
      comment). Non-native formats are transparently decoded/transcoded with
      ffmpeg; for video inputs, only the audio track is used. flac is NOT
      currently accepted (see EXTRA_AUDIO_EXTS comment above). Every upload's
      actual content (not just its extension) is probed for a real audio
      stream — see _verify_media_stream.
    - Server accepts up to MAX_UPLOAD_SIZE (currently 500 MB); files that
      don't natively fit Whisper are transcoded (mono / 16 kHz / MP3 64 kbps)
      and chunked into ≤ 20 MB pieces before being sent to Whisper (per-request
      25 MB limit, WHISPER_LIMIT).
    - `language` is a hint (ISO-639-1) to improve accuracy on low-quality audio.
    - `quality_mode` ("standard" default, or "precise") only affects local
      mode (TRANSCRIPTION_BACKEND=local): "standard" uses WHISPER_MODEL_SIZE,
      "precise" always uses large-v3-turbo (~3x slower, more accurate on some
      harder/noisier audio — see BENCHMARK.md "Bulgu 4"). Ignored in api mode.
    - The `text` field is broken into lines at natural pauses (gaps between
      Whisper segments longer than PAUSE_THRESHOLD_SECONDS) for readability —
      see _format_transcript_with_pauses. This is NOT diarization: no speaker
      labels are added, only line breaks. `diarized_text` (speaker-labeled,
      currently only produced in api mode) is unaffected by this.
    """
    if quality_mode not in QUALITY_MODES:
        raise HTTPException(
            status_code=400,
            detail=f"Geçersiz quality_mode: {quality_mode!r}. "
                   f"'{QUALITY_MODE_STANDARD}' veya '{QUALITY_MODE_PRECISE}' olmalı.",
        )

    ext = _get_ext(file.filename or "")
    if ext not in ALLOWED_EXTS:
        # Give a shorter, friendlier list in the error (natively-common formats)
        friendly = "mp3, wav, m4a, webm, mp4, opus, aac, mov, avi, mkv, wmv, flv, 3gp, mkv …"
        raise HTTPException(
            status_code=400,
            detail=f"Desteklenmeyen dosya formatı: .{ext or 'bilinmiyor'}. "
                   f"Örnek kabul edilen formatlar: {friendly}",
        )

    contents = await file.read()
    size = len(contents)
    if size == 0:
        raise HTTPException(status_code=400, detail="Boş dosya yüklendi.")
    if size > MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"Dosya çok büyük ({size / (1024*1024):.1f} MB). "
                   f"Maksimum {MAX_UPLOAD_SIZE // (1024*1024)} MB.",
        )

    # Extension alone doesn't guarantee decodable content — see
    # _verify_media_stream docstring (.dav DVR recordings especially).
    _verify_media_stream(contents, ext)

    lang_code = None
    if language and 2 <= len(language) <= 5:
        lang_code = language.lower()[:2]
    is_video = ext in VIDEO_EXTS

    if TRANSCRIPTION_BACKEND == "local":
        # No EMERGENT_LLM_KEY, no OpenAI-size-driven chunking (faster-whisper
        # has no 25MB per-request limit — it processes the whole file itself).
        try:
            raw_text, whisper_segments = _transcribe_local(contents, ext, lang_code, quality_mode)
        except HTTPException:
            raise
        except Exception as e:
            logger.exception("Local transcription failed")
            raise HTTPException(status_code=500, detail=f"Yerel transkripsiyon başarısız: {str(e)}")

        # Diarization (_diarize_local) is intentionally NOT called in local
        # mode: pyannote.audio adds substantial CPU time on top of Whisper
        # (no GPU on the target VPS), and the transcription-accuracy work
        # this mode exists for doesn't need speaker labels. diarized_text is
        # always None here. The pipeline code above (_diarize_local,
        # _align_and_format_diarization) is left in place, untouched, so
        # this can be re-enabled later by uncommenting the block below —
        # see CLAUDE.md / README.md "Local mode" for how to turn it back on.
        diarized_text = None
        # try:
        #     diar_segments = _diarize_local(contents, ext)
        #     diarized_text = _align_and_format_diarization(whisper_segments, diar_segments)
        # except Exception:
        #     logger.exception("Local diarization failed")

        return {
            "text": raw_text,
            "diarized_text": diarized_text,
            "language": lang_code,
            "filename": file.filename,
            "size_bytes": size,
            "chunks": 1,
            "is_video": is_video,
        }

    # --- api backend (default) — unchanged from before local mode existed ---
    api_key = os.environ.get("EMERGENT_LLM_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="Sunucu yapılandırma hatası: LLM anahtarı yok.")

    prompt = (
        "Bu ses dosyası düşük kaliteli, gürültülü veya düşük frekanslı olabilir. "
        "Konuşmayı en doğru şekilde Türkçe metne dök."
        if (language or "").lower().startswith("tr") else
        "The audio may be low quality, noisy or low-frequency. Transcribe speech accurately."
    )

    # Decide whether we need to transcode/chunk
    needs_transcode = (ext not in WHISPER_NATIVE_EXTS) or (size > WHISPER_LIMIT)

    try:
        if not needs_transcode:
            # Fast path: send original bytes untouched
            chunks: List[bytes] = [contents]
            chunk_ext = ext
        else:
            logger.info(
                "Transcoding via ffmpeg (video=%s, size=%.1f MB, ext=%s)",
                is_video, size / (1024 * 1024), ext,
            )
            chunks = _prepare_chunks(contents, ext)
            chunk_ext = "mp3"
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Chunking failed")
        raise HTTPException(status_code=400, detail=f"Ses dosyası çözümlenemedi: {str(e)}")

    stt = OpenAISpeechToText(api_key=api_key)
    texts: List[str] = []

    try:
        for idx, chunk_bytes in enumerate(chunks):
            buffer = io.BytesIO(chunk_bytes)
            if chunk_ext == ext:
                # Fast path: keep original filename so Whisper sees the same extension
                buffer.name = file.filename or f"audio.{chunk_ext}"
            elif len(chunks) == 1:
                buffer.name = f"audio.{chunk_ext}"
            else:
                buffer.name = f"chunk_{idx + 1}.{chunk_ext}"

            kwargs = {
                "file": buffer,
                "model": "whisper-1",
                # verbose_json + word-level timestamps for pause-based line
                # breaking (_format_transcript_with_pauses). Word-level, not
                # just segment-level: local mode's equivalent (faster-whisper
                # BatchedInferencePipeline) was found to merge VAD-separated
                # speech chunks back into one coarse Segment spanning a
                # multi-second silence, hiding the pause — word timestamps
                # didn't have that problem there (see _transcribe_local's
                # docstring) and using the same granularity for both modes
                # keeps this feature consistent instead of relying on
                # assumptions about whether OpenAI's hosted API has the same
                # issue (untestable here — no EMERGENT_LLM_KEY in this dev
                # env). response.segments/.text remain as fallbacks below if
                # a provider variant omits word timestamps.
                "response_format": "verbose_json",
                "timestamp_granularities": ["word"],
                "temperature": 0.0,
                "prompt": prompt,
            }
            if lang_code:
                kwargs["language"] = lang_code

            response = await stt.transcribe(**kwargs)
            chunk_words = _normalize_openai_segments(getattr(response, "words", None), text_key="word")
            if chunk_words:
                piece = _format_transcript_with_pauses(chunk_words)
            else:
                chunk_segments = _normalize_openai_segments(getattr(response, "segments", None))
                if chunk_segments:
                    piece = _format_transcript_with_pauses(chunk_segments)
                else:
                    piece = (getattr(response, "text", None) or "").strip()
            if piece:
                texts.append(piece)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Transcription failed")
        raise HTTPException(status_code=500, detail=f"Transkripsiyon başarısız: {str(e)}")

    # Chunk boundaries are hard cuts (not real pauses), so join chunk texts
    # with a newline too — same "\n" as within-chunk pause breaks, and a
    # no-op when there's only one chunk (the common case).
    raw_text = "\n".join(t for t in texts if t).strip()
    diarized_text = await _diarize_with_claude(raw_text, api_key)

    return {
        "text": raw_text,
        "diarized_text": diarized_text,
        "language": lang_code,
        "filename": file.filename,
        "size_bytes": size,
        "chunks": len(chunks),
        "is_video": is_video,
    }


app.include_router(api_router)

DEFAULT_CORS_ORIGINS = "http://localhost:3000,http://127.0.0.1:3000"
_cors_origins_raw = os.environ.get('CORS_ORIGINS', DEFAULT_CORS_ORIGINS)
cors_origins = [origin.strip() for origin in _cors_origins_raw.split(',') if origin.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)
