# AI Pronunciation Trainer – English edition (Flask + Whisper + Piper), CPU only.
#
#   docker build --build-arg GIT_SHA=$(git rev-parse --short HEAD) -t ai-pronunciation-trainer .
#   docker run -d --name ai-pronunciation-trainer --restart unless-stopped -p 3000:3000 \
#       --memory 9g --tmpfs /tmp:rw,nosuid,size=256m ai-pronunciation-trainer
#
# deploy/deploy.sh builds, smoke-tests and swaps the production container.
# requirements.txt pins nothing, so torch and transformers are pinned here.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/models/huggingface \
    TORCH_HOME=/models/torch \
    OMP_NUM_THREADS=5

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN pip install --upgrade pip \
    && pip install torch==2.8.0 torchaudio==2.8.0 --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt ./
RUN pip install -r requirements.txt "transformers>=4.50,<5" gunicorn

# The app runs as an unprivileged user; code and models stay owned by root.
RUN useradd --system --uid 10001 --create-home --home-dir /home/app app

COPY . .

# Download the Whisper checkpoint and the Piper voice, then score one spoken
# sentence. WARMUP_STRICT makes the build fail if scoring does not work.
RUN WARMUP_STRICT=1 python -c "import piperTTS, lambdaSpeechToScore; piperTTS.warm_up('en'); lambdaSpeechToScore.warm_up('en')"

# Everything is baked into the image; never reach out to the Hub at runtime.
ARG GIT_SHA=unknown
ENV HF_HUB_OFFLINE=1 \
    OPEN_BROWSER=0 \
    ENABLED_LANGUAGES=en \
    PRELOAD_LANGUAGES=en \
    WEB_CONCURRENCY=2 \
    READY_DIR=/tmp/aipt-ready \
    MPLCONFIGDIR=/tmp/matplotlib \
    GIT_SHA=${GIT_SHA}

USER app
EXPOSE 3000
# Healthy once every worker has scored its warm-up sentence (about 30-60 s).
HEALTHCHECK --interval=10s --timeout=5s --start-period=240s --retries=3 CMD ["python", "/app/healthcheck.py"]
CMD ["gunicorn", "-c", "gunicorn.conf.py", "webApp:app"]
