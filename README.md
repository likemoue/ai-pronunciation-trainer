# AI Pronunciation Trainer, English edition

Learners (mostly Vietnamese school children) read an English sentence aloud in the browser and get a
score for the whole sentence, for every word and for every letter. The service runs at
<https://aitrainer.ism.io.vn>.

This is a modified version of [AI Pronunciation Trainer](https://github.com/Thiagohgl/ai-pronunciation-trainer)
by Thiago Lobato, under the GNU Affero General Public License v3 ([LICENSE](LICENSE)). See
[Modifications](#modifications) and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Features

- **Practice sentences** from a bank of about 11,000 English sentences from [Tatoeba](https://tatoeba.org),
  screened for school use, in three levels (up to 8 words, 9-20 words, longer).
- **Your own text**: up to 300 characters or 60 words of English; the server gives its reference IPA.
- **Recording popup** with a live waveform and timer. It warns when it hears nothing, stops after 30 seconds
  and shows progress while the recording is scored.
- **Feedback**: a score for the sentence, a colour for every letter, and for each word the reference IPA,
  what was heard, and both sounds to compare (with slow playback).
- **Reference voice**: [Piper](https://github.com/OHF-voice/piper1-gpl) with the public-domain LJ Speech voice
  (`en_US-ljspeech-medium`), synthesised on the server. If the server has no voice, the browser's voice is used.
- **Privacy**: recordings and typed text are never stored, and student audio is never sent to third-party
  speech services. Logs hold timings and outcomes, never the text or the audio.

## How scoring works

1. The browser records with MediaRecorder (Opus in WebM or Ogg; AAC in MP4 on Safari) and sends it as base64.
2. One ffmpeg process decodes it to 16 kHz mono, with limits on size, length (35 s), formats, codecs, streams,
   memory and time (`audioPreprocessing.py`).
3. [Whisper base](https://huggingface.co/openai/whisper-base) (through transformers, on CPU) transcribes it,
   with a timestamp for every word.
4. The transcript is aligned with the sentence word by word (dynamic time warping, `WordMatching.py`), and
   every word pair is compared letter by letter. The score is the share of letters that match.
5. The reference IPA comes from the CMU Pronouncing Dictionary (`eng_to_ipa`, `RuleBasedModels.py`).

The score measures how well the speech was *recognised* as the sentence, not how each sound was pronounced:
Whisper is good at guessing the intended word, so a mispronounced sound can still score well. Scoring by
phoneme, with a model of its own, is planned.

## How it fits together

```text
browser ──HTTPS──> Cloudflare ──tunnel──> VM 202 (cloudflared) ──HTTP──> VM :3000
                                                                            │
                         Caddy (ai-pronunciation-trainer-proxy) ────────────┘
                           └─> the live colour: ai-pronunciation-trainer-blue or -green
                                 gunicorn (gunicorn.conf.py): 2 workers × 4 threads, Flask (webApp.py)
                                   ├─ /getSample, /getCustomSample   lambdaGetSample.py, validation.py
                                   ├─ /getAudioFromText               piperTTS.py (Piper, ONNX Runtime)
                                   └─ /GetAccuracyFromRecordedAudio   lambdaSpeechToScore.py
                                        audioPreprocessing.py → whisper_wrapper.py → pronunciationTrainer.py
```

- Cloudflare gives up on a request after 125 s (error 524). Every step is bounded well below that.
- Each gunicorn worker loads its own models and then scores a spoken warm-up sentence. It writes a readiness
  marker (`readiness.py`) only if that worked; the Docker `HEALTHCHECK` and `/readyz` count the markers.
- Scoring is serialised within a worker, and its other threads serve the page, samples and speech meanwhile, as
  long as fewer than four recordings (the one being scored included) are on that worker. A worker keeps
  accepting recordings while it scores one, so recordings that arrive together can queue on one worker while the
  other is idle. Under a burst (a class sending their recordings at once), every thread of a worker can be
  waiting for its model, and then the page, samples and speech wait too: up to 34 s, measured with 24 recordings
  sent at once. Phase 2 replaces this with one shared model and a bounded queue.
- Caddy receives each request in full before the app sees it, so a slow or stalled upload holds no app thread.
  It holds the bodies in up to 1 GB of memory, which held about 110 uploads of 4.9 MB at once in a test. More
  than that at once can make the kernel kill Caddy, which cuts every request in flight until docker has
  restarted it. Nothing on the server limits requests per client yet.
- `deploy/deploy.sh` deploys a new release next to the live one and switches Caddy to it once it has passed
  its checks. Requests in flight finish on the old release, uploads still arriving included
  ([deploy/RUNBOOK.md](deploy/RUNBOOK.md) gives the exception: a request sent at the very moment of the switch,
  on an idle connection or, rarely, on a new one).

## Running it

### Docker

```bash
docker build --build-arg GIT_SHA=$(git rev-parse --short HEAD) -t ai-pronunciation-trainer .
docker run -d --name aipt -p 3000:3000 --memory 9g --tmpfs /tmp:rw,nosuid,size=256m ai-pronunciation-trainer
docker ps --filter name=aipt   # (healthy) after about 30-60 s; then open http://localhost:3000
```

Unpacked, the image is about 2.9 GB: torch takes 0.8 GB, the other Python packages 1.1 GB, ffmpeg and its
libraries 0.45 GB, the models 0.35 GB and the base image 0.13 GB (`docker images` shows about 3.9 GB, as it also
counts the compressed layers). The build downloads Whisper and the Piper voice once, checks every file against its
pinned sha256, and then scores a spoken sentence: it fails if the image cannot score. At run time the app opens no
connection to the internet: Hugging Face is offline, and the telemetry of Hugging Face and ONNX Runtime is off.

### Local development

Needs Python 3.12 and [ffmpeg](https://ffmpeg.org/download.html) on the `PATH` (or `FFMPEG_BINARY`).

```bash
python -m venv .venv && . .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt                  # unpinned; the image and CI use requirements.lock
python -m pytest -q                              # fast suite: Whisper and Piper are faked
python -m pytest -q -m slow                      # the real models (downloaded on first use)
OPEN_BROWSER=0 python webApp.py                  # http://localhost:3000
```

The fast suite replaces Whisper and Piper with `FakeASR` and `FakeVoice` (`tests/conftest.py`). On Windows,
set `PYTHONUTF8=1`. The German pipeline from upstream is kept but disabled: install `epitran`, set
`ENABLED_LANGUAGES=en,de` and run `pytest -m de`.

## Configuration

Environment variables, with their defaults. The Docker image sets the ones marked *image*.

| Variable | Default | Purpose |
|---|---|---|
| `PORT` | `3000` | Port of `python webApp.py` |
| `BIND` | `0.0.0.0:3000` | Address gunicorn listens on |
| `WEB_CONCURRENCY` | `2` (image) | gunicorn workers; each loads its own models (about 0.5 GB) |
| `GUNICORN_THREADS` | `4` | Threads per worker |
| `GUNICORN_TIMEOUT` / `GUNICORN_GRACEFUL_TIMEOUT` | `120` / `120` | Worker heartbeat timeout; time to finish the requests a stopping worker has accepted |
| `OMP_NUM_THREADS` | `5` (image) | Threads per worker for torch (Whisper) |
| `LOG_LEVEL` | `INFO` | Level of the app's own logs (libraries log errors only) |
| `OPEN_BROWSER` | `1`, `0` (image) | `python webApp.py` opens a browser tab |
| `ENABLED_LANGUAGES` | `en` | Languages the API accepts |
| `PRELOAD_LANGUAGES` | `en` | Languages warmed up when a worker starts; empty: none (the worker is ready at once) |
| `READY_DIR` | `/tmp/aipt-ready` | Readiness markers of the workers |
| `WARMUP_STRICT` | unset | `1`: a failed warm-up raises (the Docker build sets it) |
| `WHISPER_MODEL` | `openai/whisper-base` at the commit in `model_pins.py`; `/models/whisper-base` (image) | Whisper checkpoint: a Hugging Face repo id or a directory |
| `WHISPER_MAX_NEW_TOKENS` | `160` | Longest transcript Whisper may produce (stops hallucinations on noise) |
| `PIPER_VOICE_EN` | `en_US-ljspeech-medium` | English voice, one of `model_pins.PIPER_VOICES`; the image holds the one it was built with (build argument `PIPER_VOICE_EN`) |
| `PIPER_MODEL_DIR` | `models/piper`; `/models/piper` (image) | Where the voices are |
| `PIPER_THREADS` | `2` | ONNX Runtime threads for speech synthesis |
| `PIPER_CACHE_MAX_MB` | `64` | Memory for synthesised audio, reused for repeated texts |
| `PIPER_MAX_PHONEMES` / `PIPER_MAX_PIECE_PHONEMES` | `900` / `300` | Longest text the voice reads; longest piece synthesised at once |
| `MAX_CUSTOM_TEXT_CHARS` / `MAX_TEXT_WORDS` | `300` / `60` | Longest practice text |
| `MAX_AUDIO_SECONDS` | `35` | Longest recording |
| `AUDIO_DECODE_TIMEOUT` | `5` | Seconds ffmpeg may take to decode a recording |
| `MAX_REQUEST_BYTES` | `4194304` | Largest request body (Flask answers 413 above it) |
| `FFMPEG_BINARY` | `ffmpeg` on the `PATH` | ffmpeg to use |
| `GIT_SHA` / `GIT_DATE` | `unknown` (set by deploy.sh) | Reported by `/version` |
| `HF_HUB_OFFLINE` | `1` (image) | Never contact the Hugging Face Hub at run time |

## HTTP API

The page is `GET /`. The API routes take a JSON object (`Content-Type: application/json`; anything else gets
415) and answer JSON. `language` is optional and must be an enabled language (`en`).

| Route | Request | Response |
|---|---|---|
| `POST /getSample` | `category`: 0 any, 1 easy, 2 medium, 3 hard | `real_transcript` (a list with the sentence), `ipa_transcript`, `transcript_translation` (empty) |
| `POST /getCustomSample` | `text` | the same, for the user's text |
| `POST /getAudioFromText` | `value`: the text to read | `wavBase64`: a WAV file |
| `POST /GetAccuracyFromRecordedAudio` | `title`: the sentence, `base64Audio`: the recording (a `data:` URL or plain base64) | `pronunciation_accuracy` (at most 100, as a string; below 0 when what was heard has many more letters than the sentence, which the page shows as 0), `real_transcript` (what was heard), `ipa_transcript`, `real_transcripts` / `matched_transcripts` and their `_ipa` versions (the aligned words), `pair_accuracy_category` (per word: 0 good, 1 fair, 2 poor), `is_letter_correct_all_words` (per letter: 1 or 0), `start_time` / `end_time` (per word, seconds) |
| `GET /healthz` | | `{"status": "ok", "uptime_s": …}`: the worker answers HTTP |
| `GET /readyz` | | 200 once every worker has warmed up, else 503: `ready_workers`, `expected_workers` |
| `GET /version` | | `git_sha`, `git_date` |

Errors are JSON too: `{"error": "<message for the user>", "code": "<code>"}`, with a status that fits.

| Code | Status | Meaning |
|---|---|---|
| `invalid_request` | 400 | Not a JSON object, an unreadable body, or no text |
| `bad_language` | 400 | `language` is not enabled |
| `bad_category` | 400 | `category` is not 0-3 |
| `text_too_long` | 400 | More than 300 characters or 60 words, or too long to read aloud |
| `text_not_english` | 400 | Less than 90% Latin letters |
| `text_bad_characters` | 400 | Control characters or lone surrogates |
| `no_audio` / `bad_audio` | 400 | No recording, or one that cannot be decoded |
| `audio_too_long` | 413 | A recording over 35 s |
| `request_entity_too_large` | 413 | A body over 4 MB (over 5 MB, the proxy answers it) |
| `unsupported_media_type` | 415 | Not `application/json` |
| `no_speech` | 422 | Silence, or nothing Whisper recognised |
| `tts_failed` | 503 | Speech synthesis failed for this text (the browser reads it instead) |
| `tts_unavailable` | 503 | The server has no voice (the browser reads every text) |
| `scoring_failed` / `server_error` | 500 | A bug; the response has an `X-Request-ID` to look up in the logs |
| `server_unavailable` | 502-504 | The proxy could not reach the app (a restart) |

Every response from the app carries `X-Request-ID` (Cloudflare's Ray ID when there is one) and security headers
(a Content Security Policy without inline scripts or styles, `nosniff`, a microphone-only Permissions-Policy).

## Dependencies and builds

- `requirements.in` lists the direct dependencies. `requirements.lock` pins them and everything they pull in,
  each file by its sha256, for CPython 3.12 on Linux x86_64; torch is the CPU build. `scripts/lock.sh`
  regenerates it with [uv](https://docs.astral.sh/uv/) from releases that are at least 7 days old
  (`--upgrade` to move everything forward; `--check` in CI, which fetches every hash again).
  `requirements-dev.lock` adds pytest, ruff and pip-audit. `scripts/pip_install_locked.sh` installs the locks: it
  also builds eng-to-ipa, which has no wheel, with the locked setuptools instead of one pip would fetch unchecked.
- `model_pins.py` pins the Whisper checkpoint to a commit and every model file by sha256.
- The `Dockerfile` pins its base image by digest. The Python packages and the models are built in stages of their
  own; the image's layers go from what changes least to what changes most: models, Python packages, system
  packages, code. The system packages are upgraded again whenever Debian publishes an update for the base image's
  release: `scripts/system_refresh.sh` derives the build argument `SYSTEM_REFRESH` from Debian's package indexes
  (the ISO week when Debian cannot be reached within about a minute), and deploy.sh and CI pass it. A rebuild
  after a code change, while Debian has published nothing new, reuses everything else (about 35 s, most of it the
  warm-up check), so such a release adds about 2 MB on the host; one built after a Debian update adds about 460 MB.
- CI (`.github/workflows/ci.yml`) runs ruff, shellcheck, actionlint, the lock check and pip-audit; the test
  suite; and builds the image, smoke-tests it, runs the tests inside it against the image's own copy of the app,
  without network (real ffmpeg, Whisper and Piper), and scans it with Trivy. A manual run with the input
  `system_refresh` forces the system packages to be upgraded again. `deploy-test.yml` runs deploy.sh's fault-injection harness
  (`deploy/test/`) when `deploy/` changes. Actions, the BuildKit daemon and tool images are pinned by commit SHA
  or digest.

## Operations

[deploy/RUNBOOK.md](deploy/RUNBOOK.md) covers the server: deploys without downtime (`deploy/deploy.sh`, which
deploys commits of main, refuses one whose CI run failed, was cancelled or has not finished, and only warns when
it cannot ask GitHub or the commit has no run), rollback, logs, health checks and the canary that smoke-tests the
public site every 15 minutes (`.github/workflows/canary.yml`).

## Modifications

As section 5(a) of the AGPL requires, this notes that the edition was changed from the upstream project (last
upstream commit 2025-08-16): it includes the changes of upstream pull request 28 (2026-08-24, Piper and
refactoring) and changes made for this edition from 2026-11-12 on. The main changes:
- English only, with a redesigned interface, practice of your own text and a recording popup.
- Hardened API: JSON only, input limits, safe audio decoding with ffmpeg, bounded speech synthesis, security
  headers, JSON errors.
- A sentence bank screened for school use; the public-domain LJ Speech voice for Piper.
- Whisper only (the Silero models and their code were removed); JSON logs with request ids; readiness and
  version endpoints; gunicorn with threads.
- Reproducible builds (lock files with hashes, pinned models and images), tests, CI, a canary, and deploys
  without downtime behind Caddy.

The source code of the running version is linked from the page footer, as section 13 of the AGPL requires.

## Licences

The code is under the [GNU AGPL v3](LICENSE). The sentences come from Tatoeba (CC BY 2.0 FR), the voice is
trained on the public-domain LJ Speech recordings, and Whisper's weights are under Apache-2.0. Every component
that ships in the image or the page is listed in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
