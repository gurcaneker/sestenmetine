import os
import io
import math
import tempfile
import uuid
import logging
from pathlib import Path
from typing import Optional, List

from fastapi import FastAPI, APIRouter, UploadFile, File, Form, HTTPException
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient

from emergentintegrations.llm.openai import OpenAISpeechToText
from emergentintegrations.llm.chat import LlmChat, UserMessage
from pydub import AudioSegment


ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB (kept from template, not used for MVP)
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

app = FastAPI()
api_router = APIRouter(prefix="/api")

# --- Config -----------------------------------------------------------------
# Hard upload cap (server-side). Users can now upload much larger files;
# we transcode/chunk down for Whisper.
MAX_UPLOAD_SIZE = 500 * 1024 * 1024                # 500 MB accepted
WHISPER_LIMIT = 25 * 1024 * 1024                   # OpenAI Whisper per-request limit
CHUNK_TARGET_BYTES = 20 * 1024 * 1024              # keep each chunk safely under 25 MB
# Formats natively accepted by OpenAI Whisper (no transcode needed)
WHISPER_NATIVE_EXTS = {"mp3", "wav", "m4a", "webm", "mp4", "mpeg", "mpga"}

# Additional audio containers we accept — ffmpeg/pydub decodes then we transcode to MP3
EXTRA_AUDIO_EXTS = {
    "flac", "ogg", "oga", "opus", "aac", "wma",
    "aiff", "aif", "aifc", "amr", "ac3", "au", "caf",
    "3ga", "voc", "ra", "mka", "dts", "wv", "mp2",
}

# Video containers — audio track is extracted with ffmpeg and transcribed
VIDEO_EXTS = {
    "mov", "avi", "mkv", "wmv", "flv", "3gp", "3g2",
    "m4v", "mpg", "mpe", "vob", "ogv", "mts", "m2ts",
    "ts", "asf", "rm", "rmvb", "f4v", "divx", "xvid",
}

ALLOWED_EXTS = WHISPER_NATIVE_EXTS | EXTRA_AUDIO_EXTS | VIDEO_EXTS

# Whisper (whisper-1) supports natively: mp3, mp4, mpeg, mpga, m4a, wav, webm.
# Everything else is decoded via ffmpeg/pydub and re-encoded to MP3 before Whisper.

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')


def _get_ext(filename: str) -> str:
    if not filename or '.' not in filename:
        return ''
    return filename.rsplit('.', 1)[-1].lower()


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


@api_router.get("/")
async def root():
    return {"message": "SesDeşifre API"}


@api_router.get("/health")
async def health():
    return {"status": "ok", "service": "transcription"}


@api_router.post("/transcribe")
async def transcribe_audio(
    file: UploadFile = File(...),
    language: Optional[str] = Form(default="tr"),
):
    """Transcribe an audio (or video) file using OpenAI Whisper.

    - Accepts most audio and video formats (mp3, wav, m4a, webm, flac, ogg, opus,
      aac, wma, aiff, amr, mov, avi, mkv, mp4, wmv, flv, 3gp, mkv, mpg, …).
      Non-native formats are transparently decoded/transcoded with ffmpeg; for
      video inputs, only the audio track is used.
    - Server accepts up to 500 MB; files that don't natively fit Whisper are
      transcoded (mono / 16 kHz / MP3 64 kbps) and chunked into ≤ 20 MB pieces
      before being sent to Whisper (per-request 25 MB limit).
    - `language` is a hint (ISO-639-1) to improve accuracy on low-quality audio.
    """
    ext = _get_ext(file.filename or "")
    if ext not in ALLOWED_EXTS:
        # Give a shorter, friendlier list in the error (natively-common formats)
        friendly = "mp3, wav, m4a, webm, mp4, flac, ogg, opus, aac, mov, avi, mkv, wmv, flv, 3gp, mkv …"
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

    api_key = os.environ.get("EMERGENT_LLM_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="Sunucu yapılandırma hatası: LLM anahtarı yok.")

    prompt = (
        "Bu ses dosyası düşük kaliteli, gürültülü veya düşük frekanslı olabilir. "
        "Konuşmayı en doğru şekilde Türkçe metne dök."
        if (language or "").lower().startswith("tr") else
        "The audio may be low quality, noisy or low-frequency. Transcribe speech accurately."
    )
    lang_code = None
    if language and 2 <= len(language) <= 5:
        lang_code = language.lower()[:2]

    # Decide whether we need to transcode/chunk
    is_video = ext in VIDEO_EXTS
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
                "response_format": "json",
                "temperature": 0.0,
                "prompt": prompt,
            }
            if lang_code:
                kwargs["language"] = lang_code

            response = await stt.transcribe(**kwargs)
            piece = (getattr(response, "text", None) or "").strip()
            if piece:
                texts.append(piece)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Transcription failed")
        raise HTTPException(status_code=500, detail=f"Transkripsiyon başarısız: {str(e)}")

    raw_text = " ".join(texts).strip()
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

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
