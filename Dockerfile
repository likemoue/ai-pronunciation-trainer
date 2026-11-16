# AI Pronunciation Trainer, English edition (Flask + Whisper + Piper), CPU only.
#
#   docker build --build-arg GIT_SHA=$(git rev-parse --short HEAD) -t ai-pronunciation-trainer .
#
# deploy/deploy.sh builds, smoke-tests and rolls out the image (deploy/RUNBOOK.md).
# The models (model_pins.py) and the Python packages (requirements.lock) are
# built in stages of their own. In the image, the layers that change least come
# first: models, packages, system packages (refreshed when Debian publishes an
# update), then the code, so a change to the code only rebuilds the last
# layers, which hold a few MB.

# python:3.12.16-slim-trixie, pinned by the digest of its multi-platform index.
ARG PYTHON_IMAGE=python:3.12.16-slim-trixie@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b

# ------------------------------------------------------------------ Python packages
FROM ${PYTHON_IMAGE} AS deps
ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_INDEX_URL=https://pypi.org/simple
COPY requirements.lock scripts/pip_install_locked.sh /tmp/
# Every file is checked against its sha256 in the lock, the build backend too.
RUN python -m venv --without-pip /opt/venv \
    && bash /tmp/pip_install_locked.sh /opt/venv/bin/python /tmp/requirements.lock

# ------------------------------------------------------------------ models
# Standard library only, so a change to requirements.lock does not download them again.
FROM ${PYTHON_IMAGE} AS models
COPY model_pins.py /tmp/build/
COPY scripts/download_models.py /tmp/build/scripts/
# The English voice to bake in (model_pins.PIPER_VOICES); empty means the default.
ARG PIPER_VOICE_EN=
RUN PIPER_VOICE_EN="${PIPER_VOICE_EN}" WHISPER_DIR=/models/faster-whisper-base PIPER_MODEL_DIR=/models/piper \
    python /tmp/build/scripts/download_models.py

# ------------------------------------------------------------------ runtime
FROM ${PYTHON_IMAGE} AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/venv/bin:$PATH

# The app runs as an unprivileged user; code, packages and models stay owned by root.
RUN useradd --system --uid 10001 --create-home --home-dir /home/app app

COPY --from=models /models /models
COPY --from=deps /opt/venv /opt/venv

# ffmpeg decodes the recordings (audioPreprocessing.py). The upgrade applies
# Debian security fixes released after the base image was built. deploy.sh and
# CI pass SYSTEM_REFRESH from scripts/system_refresh.sh: a digest of the package
# indexes that apt reads here, so this layer, and only it and the code after it,
# is rebuilt when Debian publishes an update to any of those packages (once a
# week, by the ISO week, when the archive cannot be reached). Any new value
# forces a rebuild.
ARG SYSTEM_REFRESH=
RUN echo "System packages as of ${SYSTEM_REFRESH:-this build}." \
    && apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
# Only what the app reads at run time. deploy.sh sends the build context as a
# `git archive` tar, to which .dockerignore does not apply, so the copies are
# listed here. CI builds from the directory, so a file added here must be let
# in by .dockerignore too (tests/test_build.py checks that they agree).
COPY *.py LICENSE THIRD_PARTY_NOTICES.md ./
COPY databases/data_en.csv databases/
COPY static/ static/
COPY templates/ templates/
COPY i18n/ i18n/

ARG PIPER_VOICE_EN=
# GOMP_SPINCOUNT: CTranslate2's OpenMP threads (GNU libgomp, 5 per worker) wait
# for their next task by spinning on a CPU, by default for 300,000 rounds. When
# both colours score at once during a deploy, the spinning threads of one took
# the CPUs from the other, and recordings took ten times longer. 10,000 rounds
# keep the same speed for one colour. The setting reaches GNU OpenMP only.
# OPENBLAS_NUM_THREADS: numpy's OpenBLAS started 4 helper threads per worker
# (it reads OMP_NUM_THREADS), and they spun for about 0.1 s after each small
# matrix product of the pipeline, about a tenth of a recording's CPU. One
# thread does those products in under a millisecond.
ENV HF_HUB_OFFLINE=1 \
    HF_HUB_DISABLE_TELEMETRY=1 \
    HF_HUB_DISABLE_PROGRESS_BARS=1 \
    ORT_DISABLE_TELEMETRY=1 \
    WHISPER_MODEL=/models/faster-whisper-base \
    PIPER_MODEL_DIR=/models/piper \
    PIPER_VOICE_EN=${PIPER_VOICE_EN} \
    OMP_NUM_THREADS=5 \
    GOMP_SPINCOUNT=10000 \
    OPENBLAS_NUM_THREADS=1 \
    OPEN_BROWSER=0 \
    ENABLED_LANGUAGES=en \
    PRELOAD_LANGUAGES=en \
    WEB_CONCURRENCY=2 \
    READY_DIR=/tmp/aipt-ready

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
