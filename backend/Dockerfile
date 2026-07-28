FROM python:3.11-slim

# ffmpeg is required by pydub (see server.py _prepare_chunks) for audio
# decode/transcode/chunking. pydub shells out to the ffmpeg/ffprobe
# binaries — it does not vendor them. Without this, the container starts
# fine but every non-native-format or oversized upload fails with
# "Ses dosyası çözümlenemedi" (see memory/PRD.md FLAC/OGG backlog note,
# which was verified against a *working* ffmpeg — this is that dependency).
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
# emergentintegrations isn't published on PyPI — it's served from Emergent's
# own package index. audioop-lts (also in requirements.txt) is gated to
# python_version >= "3.13" and is a no-op install on this 3.11 base image
# (3.11 still has the stdlib audioop module pydub needs).
#
# Installed in two steps on purpose: emergentintegrations pins its own
# litellm wheel (same URL as requirements.txt's own litellm line, but pip's
# resolver treats the two constraints as conflicting and refuses to install
# both in one `pip install -r requirements.txt` pass — ResolutionImpossible).
# Installing emergentintegrations first lets it pull in litellm on its own;
# then the rest of requirements.txt installs against what's already
# satisfied, skipping both lines the second time around.
RUN pip install --no-cache-dir emergentintegrations==0.2.0 \
        --extra-index-url https://d33sy5i8bnduwe.cloudfront.net/simple/ \
    && grep -viE '^emergentintegrations|^litellm' requirements.txt > requirements.rest.txt \
    && pip install --no-cache-dir -r requirements.rest.txt \
    && rm requirements.rest.txt

COPY server.py .

EXPOSE 8000

# --workers 1 is intentional, not a default left unconfigured: slowapi's
# rate limiter (see SECURITY_NOTES.md) uses in-memory, per-process storage.
# Each additional worker would keep its own separate counter, silently
# multiplying the real /api/transcribe rate limit by the worker count
# (5/min becomes N*5/min). Do not raise this without first switching slowapi
# to a Redis storage backend (storage_uri="redis://...") — see
# SECURITY_NOTES.md "Depolama" note.
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
