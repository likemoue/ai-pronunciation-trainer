# AI Pronunciation Trainer – English edition (Flask + Whisper + Piper), CPU only.
#
#   docker build -t ai-pronunciation-trainer .
#   docker run -d --name ai-pronunciation-trainer --restart unless-stopped -p 3000:3000 ai-pronunciation-trainer
#
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

COPY . .

# Models load lazily at runtime, so download them explicitly at build time:
# the Whisper checkpoint (Hugging Face cache) and the Piper English voice.
RUN python -c "import lambdaSpeechToScore, piperTTS; lambdaSpeechToScore.warm_up('en'); piperTTS.generate_wav_base64('Hello.', 'en')"

# Everything is baked into the image; never reach out to the Hub at runtime.
ENV HF_HUB_OFFLINE=1 \
    OPEN_BROWSER=0 \
    ENABLED_LANGUAGES=en \
    PRELOAD_LANGUAGES=en

EXPOSE 3000
# Sync workers handle one request at a time; each worker warms up its own model.
CMD ["gunicorn", "--bind", "0.0.0.0:3000", "--workers", "2", "--timeout", "180", "webApp:app"]
