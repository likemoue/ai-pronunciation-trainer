# AI Pronunciation Trainer, English edition (Flask + Whisper + Piper), CPU only.
#
#   docker build --build-arg GIT_SHA=$(git rev-parse --short HEAD) -t ai-pronunciation-trainer .
#
# deploy/deploy.sh builds, smoke-tests and rolls out the image (deploy/RUNBOOK.md).
# Layers that rarely change come first: system packages, the models pinned in
# model_pins.py, the Python packages pinned in requirements.lock. A change to
# the app code only rebuilds the last layers, which hold a few MB.

# python:3.12.16-slim-trixie, pinned by the digest of its multi-platform index.
ARG PYTHON_IMAGE=python:3.12.16-slim-trixie@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b

# ------------------------------------------------------------------ Python packages
FROM ${PYTHON_IMAGE} AS deps
ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
COPY requirements.lock /tmp/requirements.lock
# Every file is checked against its sha256 in the lock. torch is the CPU build
# from the PyTorch index; everything else comes from PyPI.
RUN python -m venv --without-pip /opt/venv \
    && pip --python /opt/venv/bin/python install --require-hashes -r /tmp/requirements.lock \
        --index-url https://pypi.org/simple --extra-index-url https://download.pytorch.org/whl/cpu

# ------------------------------------------------------------------ models
FROM deps AS models
COPY model_pins.py /tmp/build/
COPY scripts/download_models.py /tmp/build/scripts/
# The English voice to bake in (model_pins.PIPER_VOICES); empty means the default.
ARG PIPER_VOICE_EN=
RUN HF_HUB_DISABLE_TELEMETRY=1 PIPER_VOICE_EN="${PIPER_VOICE_EN}" \
    WHISPER_DIR=/models/whisper-base PIPER_MODEL_DIR=/models/piper \
    /opt/venv/bin/python /tmp/build/scripts/download_models.py

# ------------------------------------------------------------------ runtime
FROM ${PYTHON_IMAGE} AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/venv/bin:$PATH

# ffmpeg decodes the recordings (audioPreprocessing.py). The upgrade applies
# Debian security fixes released after the base image was built.
RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# The app runs as an unprivileged user; code, packages and models stay owned by root.
RUN useradd --system --uid 10001 --create-home --home-dir /home/app app

COPY --from=models /models /models
COPY --from=deps /opt/venv /opt/venv

WORKDIR /app
# .dockerignore lets in only what the app needs at run time.
COPY . .

ARG PIPER_VOICE_EN=
ENV HF_HUB_OFFLINE=1 \
    HF_HUB_DISABLE_TELEMETRY=1 \
    WHISPER_MODEL=/models/whisper-base \
    PIPER_MODEL_DIR=/models/piper \
    PIPER_VOICE_EN=${PIPER_VOICE_EN} \
    OMP_NUM_THREADS=5 \
    OPEN_BROWSER=0 \
    ENABLED_LANGUAGES=en \
    PRELOAD_LANGUAGES=en \
    WEB_CONCURRENCY=2 \
    READY_DIR=/tmp/aipt-ready \
    MPLCONFIGDIR=/tmp/matplotlib

USER app
# Score one spoken sentence with the models and packages as installed, so a
# broken scoring pipeline fails the build instead of shipping. Nothing it
# writes stays in the image.
RUN WARMUP_STRICT=1 python -c "import piperTTS, lambdaSpeechToScore; piperTTS.warm_up('en'); lambdaSpeechToScore.warm_up('en')" \
    && rm -rf /tmp/* /tmp/.[!.]* /home/app/.cache

# The commit and its date (deploy/deploy.sh passes both); /version reports them.
ARG GIT_SHA=unknown
ARG GIT_DATE=unknown
ENV GIT_SHA=${GIT_SHA} \
    GIT_DATE=${GIT_DATE}
LABEL org.opencontainers.image.title="AI Pronunciation Trainer (English edition)" \
      org.opencontainers.image.source="https://github.com/likemoue/ai-pronunciation-trainer" \
      org.opencontainers.image.revision="${GIT_SHA}"

EXPOSE 3000
# Healthy once every worker has scored its warm-up sentence (about 30-60 s).
HEALTHCHECK --interval=10s --timeout=5s --start-period=240s --retries=3 CMD ["python", "/app/healthcheck.py"]
CMD ["gunicorn", "-c", "gunicorn.conf.py", "webApp:app"]
