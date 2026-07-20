import os
import io
import logging
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, APIRouter, UploadFile, File, Form, HTTPException
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient

from emergentintegrations.llm.openai import OpenAISpeechToText


ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB (kept from template, not used for MVP)
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

app = FastAPI()
api_router = APIRouter(prefix="/api")

# Config
MAX_FILE_SIZE = 25 * 1024 * 1024  # OpenAI Whisper limit: 25 MB
ALLOWED_EXTS = {"mp3", "wav", "m4a", "webm", "mp4", "mpeg", "mpga"}

# Whisper (whisper-1) supports exactly: mp3, mp4, mpeg, mpga, m4a, wav, webm.

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')


def _get_ext(filename: str) -> str:
    if not filename or '.' not in filename:
        return ''
    return filename.rsplit('.', 1)[-1].lower()


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
    """Transcribe an audio file using OpenAI Whisper.

    - Supports mp3, wav, m4a, ogg, flac, webm, mp4, mpeg, mpga
    - Max size: 25 MB
    - `language` is a hint (ISO-639-1) to improve accuracy on low-quality audio
    """
    ext = _get_ext(file.filename or "")
    if ext not in ALLOWED_EXTS:
        raise HTTPException(
            status_code=400,
            detail=f"Desteklenmeyen dosya formatı: .{ext or 'bilinmiyor'}. "
                   f"Kabul edilen: {', '.join(sorted(ALLOWED_EXTS))}",
        )

    contents = await file.read()
    size = len(contents)
    if size == 0:
        raise HTTPException(status_code=400, detail="Boş dosya yüklendi.")
    if size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"Dosya çok büyük ({size / (1024*1024):.1f} MB). Maksimum 25 MB.",
        )

    api_key = os.environ.get("EMERGENT_LLM_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="Sunucu yapılandırma hatası: LLM anahtarı yok.")

    try:
        stt = OpenAISpeechToText(api_key=api_key)
        # Wrap bytes as a file-like object with a name so OpenAI knows the format
        buffer = io.BytesIO(contents)
        buffer.name = file.filename or f"audio.{ext}"

        # A short prompt hints Whisper that audio is noisy / low quality, and asks for cleaner text
        prompt = (
            "Bu ses dosyası düşük kaliteli, gürültülü veya düşük frekanslı olabilir. "
            "Konuşmayı en doğru şekilde Türkçe metne dök."
            if (language or "").lower().startswith("tr") else
            "The audio may be low quality, noisy or low-frequency. Transcribe speech accurately."
        )

        kwargs = {
            "file": buffer,
            "model": "whisper-1",
            "response_format": "json",
            "temperature": 0.0,
            "prompt": prompt,
        }
        # Only pass language if a valid ISO-639-1 code
        if language and 2 <= len(language) <= 5:
            kwargs["language"] = language.lower()[:2]

        response = await stt.transcribe(**kwargs)
        text = getattr(response, "text", None) or ""
        return {
            "text": text.strip(),
            "language": kwargs.get("language"),
            "filename": file.filename,
            "size_bytes": size,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Transcription failed")
        raise HTTPException(status_code=500, detail=f"Transkripsiyon başarısız: {str(e)}")


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
