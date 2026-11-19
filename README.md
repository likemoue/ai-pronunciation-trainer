# AI Pronunciation Trainer, English edition

Learners (mostly Vietnamese school children) read an English sentence aloud in the browser and get a
score for the whole sentence, for every word and for every letter. The service runs at
<https://aitrainer.ism.io.vn>.

This is a modified version of [AI Pronunciation Trainer](https://github.com/Thiagohgl/ai-pronunciation-trainer)
by Thiago Lobato, under the GNU Affero General Public License v3 ([LICENSE](LICENSE)). See
[Modifications](#modifications) and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Features

- **Practice sentences** from a bank of about 9,300 English sentences from [Tatoeba](https://tatoeba.org),
  screened for school use and naming no person ("He is a student", not "Tom is a student"), in three levels
  (up to 8 words, 9-20 words, longer).
- **Your own text**: up to 300 characters or 60 words of English; the server gives its reference IPA.
- **Recording popup** with a live waveform and timer. It warns when it hears nothing, stops after 30 seconds
  and shows progress while the recording is scored. A busy server gets the same recording again by itself;
  when the connection or the server fails, or the browser is offline, the recording stays on the page to send
  again. Each microphone problem says what to do: the steps to unblock it in the browser at hand, or, inside
  Zalo, Facebook or Messenger, how to open the page in Chrome or Safari.
- **Feedback**: a score for the sentence in words (Excellent, Well done, Almost there, Keep practising, or "That
  sounds like a different sentence"), the letters heard as written in one colour and the others bold and dotted,
  a mark after each word marked Almost or Needs work, and the words to practise first. For each word: the
  reference IPA with the server's voice reading it, what was heard with that part of the recording; for a word
  heard with a typical mistake (an ending left out, "th" or "sh" said otherwise), what to fix and both words to
  listen to.
- **Reference voice**: [Piper](https://github.com/OHF-voice/piper1-gpl) with the public-domain LJ Speech voice
  (`en_US-ljspeech-medium`), synthesised on the server. Bank sentences come as MP3 files that browsers and
  Cloudflare cache; if the server has no voice, the browser's voice is used.
- **Progress**, kept in the learner's browser only: today's points (each sentence once a day, at its best attempt,
  times its level: Easy x1, Medium x1.3, Hard x1.6), the streak and the last 7 days in Vietnam time, and the words
  to review, each practised on its own. "New learner" clears it on a shared phone or computer.
- **First visit**: a three-step tour over the real controls, then a 3-second microphone check in the browser
  (nothing recorded or sent), so the browser's permission prompt comes with an explanation; both again from How
  it works.
- **In-app browsers**: in Zalo, Facebook, Messenger, Instagram, LINE and other Android WebViews, a banner gets the
  learner to a real browser: Open in Chrome on Android, the app's ••• menu on iPhone, and Copy link.
- **Privacy**: recordings and typed text are never stored on the server, and student audio is never sent to
  third-party speech services. Logs hold timings and outcomes, never the text or the audio.

## How scoring works

1. The browser records with MediaRecorder at 32 kbps (Opus in WebM or Ogg; AAC in MP4 on Safari) and sends it
   as base64.
2. One ffmpeg process decodes it to 16 kHz mono, with limits on size, length (35 s), formats, codecs, streams,
   memory and time (`audioPreprocessing.py`), single-threaded and at most 4 at a time per worker.
3. [Whisper base](https://huggingface.co/openai/whisper-base), run by
   [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (CTranslate2, int8 on CPU), transcribes it with a
   timestamp for every word. Before it, the recording is scaled by a level a single loud click cannot set (the
   99.5th percentile of its samples), so a soft phrase after a much louder tap on Record is heard, and Silero
   VAD keeps recordings without speech from Whisper. Silence gives no words, nor does a window that Whisper
   rates as probably not speech. On the evaluation set, 10 of 11 recordings of noise are refused as no speech,
   among them white noise recorded by the page, which Whisper alone heard as "I'm sorry."; noise recorded
   through Chrome's capture path, whose noise suppression shapes it, can still give words.
4. Both the sentence and the transcript are read as their words are said ("2:30" as "two thirty", "3-day" as
   "three day", "OK" and "okay" alike, and homophones and British or American spellings counted as the same word
   by the CMU dictionary), then aligned word by word (an edit-distance alignment, `WordMatching.py`: a word left
   out or added costs its own place only). Every word pair is compared letter by letter, aligned the same way.
   The score is the share of letters that match. A word heard with one of Vietnamese learners' typical mistakes
   (an ending -s, -es, -d or -ed left out, th said as t, d, s or f, sh as s) is never labelled Correct, however
   many of its letters match ("book" for "books").
5. The reference IPA comes from the CMU Pronouncing Dictionary through `eng_to_ipa`, with the dictionary held in
   memory (`RuleBasedModels.CmuIpa`, exactly eng_to_ipa's output).

The score measures how well the speech was *recognised* as the sentence, not how each sound was pronounced:
Whisper is good at guessing the intended word, so a mispronounced sound can still score well (it wrote "think"
for 12 of 14 readings of "think" said as "tink" in the evaluation set). Scoring by phoneme, with a model of its
own, is planned.

### Evaluating the scoring

[`evaluation/`](evaluation/README.md) holds 441 synthetic recordings (the app's own Piper voice; no learner's
voice) whose truth is known word by word: bank sentences read clean, slowly, fast, under noise and by a higher
voice; Vietnamese learners' typical mistakes made in the phonemes (θ→t, ð→d, ʃ→s, dropped final stops, plural
-s and past -ed); words left out, repeated or added; numbers and spellings Whisper writes otherwise; soft speech
after a loud tap; and noise, some of it recorded by Chrome as the page records. `python -m evaluation.harness`
scores them as the server does and reports how often the labels are right
([evaluation/report.md](evaluation/report.md)); every change to the scoring is judged by it.

## How it fits together

```text
browser ──HTTPS──> Cloudflare ──tunnel──> VM 202 (cloudflared) ──HTTP──> VM :3000
                                                                            │
                         Caddy (ai-pronunciation-trainer-proxy) ────────────┘
                           └─> the live colour: ai-pronunciation-trainer-blue or -green
                                 gunicorn (gunicorn.conf.py): 2 workers × 24 threads, Flask (webApp.py)
                                   ├─ /getSample, /getCustomSample   lambdaGetSample.py, validation.py
                                   ├─ /tts/<language>/<key>.mp3       piperTTS.py (Piper, ONNX Runtime; ffmpeg)
                                   ├─ /getAudioFromText               piperTTS.py
                                   └─ /GetAccuracyFromRecordedAudio   lambdaSpeechToScore.py
                                        audioPreprocessing.py → whisper_wrapper.py → pronunciationTrainer.py
```

- Cloudflare gives up on a request after 125 s (error 524). Every step is bounded well below that.
- Each gunicorn worker loads its own models and then scores a spoken warm-up sentence. It writes a readiness
  marker (`readiness.py`) only if that worked; the Docker `HEALTHCHECK` and `/readyz` count the markers.
- Scoring is serialised within a worker, and every recording waiting for the model holds a thread. So a worker
  takes at most 20 recordings (`SCORING_QUEUE_LIMIT`), and fewer when those ahead would take over 30 s; the next
  ones get 503 with `Retry-After` at once, and the page sends the recording again by itself after that time plus
  up to 2 s, at most 3 times, counting down in the popup. Speech synthesis is bounded the same way (2 texts per
  worker; the browser's voice reads a text the server turns away). That leaves at least 2 of the 24 threads free
  for the page, the samples and `/healthz` during a burst. A worker accepts no more connections than it has
  threads, so in a burst a full worker leaves new connections to the other one. The two workers have 40 places,
  but a burst does not always split evenly: in tests with 40 recordings sent at once, up to 4 were turned away
  by one worker while the other had room, and were sent again after `Retry-After`. gunicorn closes each
  connection after its response (no keep-alive behind Caddy) and waits at most 0.2 s for Caddy to close its
  side. A recording whose client gave up while it waited
  (the popup closed) is not scored: Caddy closes the connection, and the app checks it before it uses the model.
  With faster-whisper a recording holds the model for about a second on a CPU with AVX2, and for about 1.8 s on
  the production server, an Ivy Bridge Xeon without AVX2: there a class of 40 sending at once waits 21 s at the
  median and 40 s at most.
- Static files are named by version: the page asks for its stylesheets and scripts (every file under `static/css`
  and `static/javascript`, through `asset_url` in the template) with `?v=` and a hash of them all, and browsers
  and Cloudflare keep those, the fonts and the bank-sentence MP3s for a year. The page itself is checked on every
  load, and API answers are never stored. The page loads nothing from another site: its fonts
  (Inter with its Vietnamese subset, Noto Sans with its Greek subset for the IPA's θ) are served by the app, and the
  result chime is synthesised in the browser.
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

The image holds no torch since phase 2 (see the PR for its size). The build downloads Whisper and the Piper
voice once, checks every file against its
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
| `WEB_CONCURRENCY` | `2` (image) | gunicorn workers; each loads its own models |
| `GUNICORN_THREADS` | `24` | Threads per worker, and the most connections a worker accepts at once |
| `SCORING_QUEUE_LIMIT` | `GUNICORN_THREADS` - 4 | Recordings a worker holds (scored or waiting) before it answers 503 |
| `SCORING_MAX_WAIT_SECONDS` | `30` | A recording that would wait longer than this, from recent scoring times, gets 503 |
| `GUNICORN_TIMEOUT` / `GUNICORN_GRACEFUL_TIMEOUT` | `120` / `120` | Worker heartbeat timeout; time to finish the requests a stopping worker has accepted |
| `OMP_NUM_THREADS` | `5` (image) | Threads per worker for numerical libraries; the default of `WHISPER_CPU_THREADS` |
| `GOMP_SPINCOUNT` | `10000` (image) | How long an idle GNU OpenMP thread (CTranslate2's) spins before it sleeps; the default of 300,000 made the two colours of a deploy slow each other down |
| `OPENBLAS_NUM_THREADS` | `1` (image) | numpy's OpenBLAS runs on the calling thread; its helper threads spun after each matrix product |
| `LOG_LEVEL` | `INFO` | Level of the app's own logs (libraries log errors only) |
| `OPEN_BROWSER` | `1`, `0` (image) | `python webApp.py` opens a browser tab |
| `ENABLED_LANGUAGES` | `en` | Languages the API accepts |
| `PRELOAD_LANGUAGES` | `en` | Languages warmed up when a worker starts; empty: none (the worker is ready at once) |
| `READY_DIR` | `/tmp/aipt-ready` | Readiness markers of the workers |
| `WARMUP_STRICT` | unset | `1`: a failed warm-up raises (the Docker build sets it) |
| `WHISPER_MODEL` | `models/faster-whisper-base` (downloaded on first use); `/models/faster-whisper-base` (image) | Directory of the CTranslate2 Whisper model (`model_pins.py`) |
| `WHISPER_CPU_THREADS` | `OMP_NUM_THREADS`, else `4` | CTranslate2 threads per worker; workers × threads should not exceed the CPUs |
| `WHISPER_COMPUTE_TYPE` | `int8` | CTranslate2 compute type (`int8`, `float32`, …) |
| `WHISPER_MAX_NEW_TOKENS` | `160` | Longest transcript Whisper may produce (stops hallucinations on noise) |
| `VAD_THRESHOLD` | `0.5` | Silero VAD's speech probability for a 32 ms window to count as speech, in [0, 1); a recording without `VAD_MIN_WINDOWS` such windows in a row is "no speech" without Whisper. `0` turns the gate off; keep it on, since the recording level (`preprocessAudio`) was chosen with it: without it, silent takes with a tap at each end were heard as "I'm sorry." |
| `VAD_MIN_WINDOWS` | `3` | Windows of speech in a row (96 ms) the gate needs; one let long white noise through |
| `PIPER_VOICE_EN` | `en_US-ljspeech-medium` | English voice, one of `model_pins.PIPER_VOICES`; the image holds the one it was built with (build argument `PIPER_VOICE_EN`) |
| `PIPER_MODEL_DIR` | `models/piper`; `/models/piper` (image) | Where the voices are |
| `PIPER_THREADS` | `2` | ONNX Runtime threads for speech synthesis |
| `PIPER_CACHE_MAX_MB` | `64` | Memory for synthesised audio, reused for repeated texts |
| `PIPER_QUEUE_LIMIT` | `2` | Texts a worker synthesises or waits to synthesise before it answers 503 |
| `PIPER_MP3_BITRATE` | `48k` | Bitrate of the bank-sentence MP3s |
| `PIPER_MAX_PHONEMES` / `PIPER_MAX_PIECE_PHONEMES` | `900` / `300` | Longest text the voice reads; longest piece synthesised at once |
| `MAX_CUSTOM_TEXT_CHARS` / `MAX_TEXT_WORDS` | `300` / `60` | Longest practice text |
| `MAX_AUDIO_SECONDS` | `35` | Longest recording |
| `AUDIO_DECODE_TIMEOUT` | `5` | Seconds ffmpeg may take to decode a recording |
| `AUDIO_DECODE_CONCURRENCY` | `4` | Recordings a worker decodes at once (the others wait for a slot; each ffmpeg uses one thread) |
| `MAX_REQUEST_BYTES` | `4194304` | Largest request body (Flask answers 413 above it) |
| `FFMPEG_BINARY` | `ffmpeg` on the `PATH` | ffmpeg to use |
| `GIT_SHA` / `GIT_DATE` | `unknown` (set by deploy.sh) | Reported by `/version` |
| `HF_HUB_OFFLINE` | `1` (image) | Never contact the Hugging Face Hub at run time |

## HTTP API

The page is `GET /`, in English, or in Vietnamese when its `lang` cookie is `vi` (`Vary: Cookie`). The API routes
take a JSON object (`Content-Type: application/json`; anything else gets 415) and answer JSON. `language` is
optional and must be an enabled language (`en`).

| Route | Request | Response |
|---|---|---|
| `POST /getSample` | `category`: 0 any, 1 easy, 2 medium, 3 hard | `real_transcript` (a list with the sentence), `ipa_transcript`, `transcript_translation` (empty), `tts_url`, `category` (the sentence's own level as a number, 1, 2 or 3, also when 0 was asked for) |
| `POST /getCustomSample` | `text` | `real_transcript`, `ipa_transcript`, `transcript_translation`, for the user's text (no `tts_url` or `category`) |
| `POST /getAudioFromText` | `value`: the text to read | `wavBase64`: a WAV file |
| `GET /tts/<language>/<key>.mp3` | | A bank sentence read aloud (MP3); `/getSample` gives the URL as `tts_url`. The key is a hash of the voice, the MP3 bitrate and the sentence, so the file never changes and is cached for a year; any other key is 404 |
| `POST /GetAccuracyFromRecordedAudio` | `title`: the sentence, `base64Audio`: the recording (a `data:` URL or plain base64) | `pronunciation_accuracy` (at most 100, as a string; below 0 when what was heard has many more letters than the sentence, which the page shows as 0), `real_transcript` (what was heard), `ipa_transcript`, `real_transcripts` / `matched_transcripts` and their `_ipa` versions (the aligned words), `pair_accuracy_category` (per word: 0 good, 1 fair, 2 poor), `mistake_kinds` (per word, in the same order: `ending`, `th` or `sh` when the word was heard with that typical mistake, which keeps it from 0, else `-`; "Mary has written three books." heard as "Mary has written tree book." gives `- - - th ending`), `is_letter_correct_all_words` (per letter: 1 or 0), `start_time` / `end_time` (per word, seconds) |
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
| `text_bad_characters` | 400 | Control characters or lone surrogates (Windows-1252's quotes, dashes and ellipsis read as Latin-1 count as that punctuation; zero-width characters and soft hyphens are dropped) |
| `no_audio` / `bad_audio` | 400 | No recording, or one that cannot be decoded |
| `audio_too_long` | 413 | A recording over 35 s |
| `request_entity_too_large` | 413 | A body over 4 MB (over 5 MB, the proxy answers it) |
| `unsupported_media_type` | 415 | Not `application/json` |
| `no_speech` | 422 | Silence, or nothing Whisper recognised |
| `busy` | 503 | The worker holds as many recordings as it takes; `Retry-After` (also `retry_after` in the body) says when to send it again |
| `tts_busy` | 503 | The worker is synthesising as many texts as it takes; `Retry-After: 2` (the browser reads the text instead) |
| `tts_failed` | 503 | Speech synthesis failed for this text (the browser reads it instead) |
| `tts_unavailable` | 503 | The server has no voice (the browser reads every text) |
| `client_gone` | 499 | Logged only: the client closed the connection before its recording was scored |
| `scoring_failed` / `server_error` | 500 | A bug; the response has an `X-Request-ID` to look up in the logs |
| `server_unavailable` | 502-504 | The proxy could not reach the app (a restart) |

Every response from the app carries `X-Request-ID` (Cloudflare's Ray ID when there is one) and security headers
(a Content Security Policy without inline scripts or styles, `nosniff`, a microphone-only Permissions-Policy).

## Dependencies and builds

- `requirements.in` lists the direct dependencies. `requirements.lock` pins them and everything they pull in,
  each file by its sha256, for CPython 3.12 on Linux x86_64, all from PyPI. `scripts/lock.sh`
  regenerates it with [uv](https://docs.astral.sh/uv/) from releases that are at least 7 days old
  (`--upgrade` to move everything forward; `--check` in CI, which fetches every hash again).
  `requirements-dev.lock` adds pytest, ruff and pip-audit. `scripts/pip_install_locked.sh` installs the locks: it
  also builds eng-to-ipa, which has no wheel, with the locked setuptools instead of one pip would fetch unchecked.
- `model_pins.py` pins the Whisper model to a commit and every model file by sha256.
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
- Whisper only (the Silero models and their code were removed), run by faster-whisper instead of transformers
  and torch; JSON logs with request ids; readiness and version endpoints; gunicorn with threads and a bounded
  queue that answers 503 with Retry-After; the CMU dictionary in memory.
- Static files cached by content version, fonts served by the app, bank sentences read aloud as cacheable MP3s.
- Reproducible builds (lock files with hashes, pinned models and images), tests, CI, a canary, and deploys
  without downtime behind Caddy.
- An evaluation harness for the scoring, with a set of synthetic recordings labelled word by word; scoring
  judged by it: edit-distance alignment (without dtwalign), words read as they are said, a robust recording
  level, Silero VAD before Whisper, and learners' typical mistakes never labelled Correct.

The source code of the running version is linked from the small notice under the page footer, as section 13
of the AGPL requires; the same line links the original project and credits Tatoeba.

## Licences

The code is under the [GNU AGPL v3](LICENSE). The sentences come from Tatoeba (CC BY 2.0 FR), the voice is
trained on the public-domain LJ Speech recordings, and Whisper's weights are under MIT. The evaluation set's
recordings are that voice reading bank sentences (Tatoeba, CC BY 2.0 FR) and sentences written for the set. Every component
that ships in the image or the page is listed in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
