# AI Pronunciation Trainer: English edition (aitrainer.ism.io.vn)

Students (mostly Vietnamese school children) read an English sentence aloud and get a score per word and per letter.
This is a fork of [Thiagohgl/ai-pronunciation-trainer](https://github.com/Thiagohgl/ai-pronunciation-trainer) (AGPL-3.0),
trimmed to English. `README.md` describes it for readers; this file is the short version for working on it.

## How it fits together

- `webApp.py`: Flask app, served by gunicorn (`gunicorn.conf.py`: gthread, 2 workers × 4 threads) in Docker.
  Cloudflare is in front, through a tunnel on VM 202 (172.16.10.20) to VM port 3000, where Caddy forwards to the
  live colour (blue or green). Cloudflare drops requests after 125 s (error 524). With gthread workers, gunicorn's
  `timeout` no longer interrupts a slow request, so every step bounds itself.
- API routes accept only `application/json` (others get 415). Every error is JSON `{"error", "code"}`:
  - `POST /getSample`: a sentence from the bank, `category` 0 to 3 (random, easy, medium, hard).
  - `POST /getCustomSample`: the user's own text, with its IPA.
  - `POST /getAudioFromText`: Piper TTS, returned as base64 WAV.
  - `POST /GetAccuracyFromRecordedAudio`: scores a recording.
  - `GET /healthz` (the worker answers), `/readyz` (every worker warmed up), `/version` (`GIT_SHA`, `GIT_DATE`).
- Scoring pipeline (serialised per worker by `_inference_lock`; one `scored` log line per request with timings):
  1. `audioPreprocessing.decode_audio`: one ffmpeg process, bounded by size, allocations, codecs, streams and time.
  2. Whisper base (`whisper_wrapper.py`, transformers 5), pinned to a commit in `model_pins.py`.
  3. `pronunciationTrainer.py`: word alignment with DTW in `WordMatching.py`; reference IPA from `eng_to_ipa` in `RuleBasedModels.py`.
- `piperTTS.py`: the reference voice (Piper, `en_US-ljspeech-medium`, public domain). Voice files are pinned by sha256
  in `model_pins.py`. A text over 900 phonemes is refused, and pieces over 300 phonemes are synthesised in smaller parts.
- `validation.py`: shared input limits, enforced before any model runs.
  - Text: up to 300 characters or 60 words, and at least 90% A-Z letters. The TTS route also accepts single short
    words such as "André" or "2:30". Control characters other than whitespace, and lone UTF-16 surrogates, are refused.
  - Audio: up to 35 s, in a request of up to 4 MB.
- `databases/data_en.csv`: the sentence bank, from Tatoeba (CC BY 2.0 FR, credited in the footer).
  It is screened for school use, and `tests/test_content.py` fails on blocked topics and on duplicates.
- Frontend: `templates/main.html`, `static/javascript/app.js` and `static/css/style.css`.
  The CSP forbids inline scripts and styles, and the client's `normalizeText` must stay in step with `validation.normalize_text`.
- Health: each gunicorn worker writes a marker (`readiness.py`) after a warm-up that scores a real spoken sentence; the
  warm-up starts in gunicorn's `post_worker_init`, not on import. `healthcheck.py` (the Docker `HEALTHCHECK`) and `/readyz`
  count the markers of live workers.
- Logs (`logging_setup.py`): one JSON object per line, with the request id (`rid`, Cloudflare's Ray ID). App loggers come
  from `logging_setup.get_logger(__name__)` (namespace `aipt`) and log from INFO; `print` is not used.

## Commands

```bash
# Tests. The fast suite fakes Whisper and Piper (FakeASR / FakeVoice in tests/conftest.py).
FFMPEG_BINARY=<path to ffmpeg> PYTHONUTF8=1 python -m pytest -q
python -m pytest -q -m slow     # real Whisper and Piper

OPEN_BROWSER=0 python webApp.py   # local server on :3000
docker build --build-arg GIT_SHA=$(git rev-parse --short HEAD) -t ai-pronunciation-trainer .
scripts/lock.sh [--upgrade | --check]   # requirements*.lock from requirements*.in (needs uv)
```

The Docker build runs a strict warm-up and fails if the image cannot score a spoken sentence. Its layers go from what
changes least to most (system packages, models, Python packages, code), so a code change rebuilds only a few MB.
`.dockerignore` lets in only what the app needs; add new runtime files there.

## Dependencies

- `requirements.in` lists direct dependencies; `requirements.lock` pins everything with hashes (CPython 3.12, Linux
  x86_64, torch from the PyTorch CPU index). Regenerate with `scripts/lock.sh`; CI fails if the lock does not match.
  Versions: the newest release that is at least 7 days old (uv `--exclude-newer`), unless a security fix needs newer.
- The image installs `requirements.lock` with `--require-hashes` and both indexes (see the Dockerfile).
- `model_pins.py` pins Whisper and the Piper voices; the base image and the Caddy image are pinned by digest.

## Deploying

Production is a Caddy proxy and two app colours on the VM in `deploy/RUNBOOK.md`. To deploy:
1. On the VM, check out main.
2. Run `nohup deploy/deploy.sh > ~/deploy-<date>.log 2>&1 < /dev/null &`.

`deploy.sh` does the following, without dropping requests:
1. Builds the image from `git archive` of the commit (only commits on an origin branch; the checkout is not changed).
2. Starts it in the idle colour (`127.0.0.1:3001` or `3002`), waits until healthy and runs that commit's
   `deploy/smoke_test.py`, which scores a TTS sentence end to end.
3. Switches Caddy to it with a graceful reload and smoke-tests it through port 3000; switches back on failure.
4. Records the deploy in `~/.local/state/ai-pronunciation-trainer/deploys.log`, stops the old colour (kept for
   `deploy.sh --rollback`) and keeps the images of the last 3 deploys.

On a host that still has the single container of earlier versions, the first run moves it behind the proxy (a few
seconds without service, once) and keeps it as `ai-pronunciation-trainer-legacy`. Interrupted runs undo themselves;
a run killed while moving the single container is finished or undone by the next run; one deploy runs at a time.
`deploy.sh --status` shows what is live.

Rollback: `deploy/deploy.sh --rollback` (the previous colour), or `deploy/deploy.sh <sha>` for a version from
phase 0a on. Older versions (51c9af9, kept as `ai-pronunciation-trainer:english-ui`) have no smoke test or
HEALTHCHECK; deploy.sh refuses them, and the RUNBOOK starts them by hand. Cloudflare blocks Python's urllib user
agent: check the public site in a browser, or run the smoke test with `--user-agent`.

CI (`.github/workflows/ci.yml`) checks every PR and push: ruff, shellcheck, actionlint, the lock, pip-audit,
pytest, then the image (smoke test, every test inside it, Trivy). `canary.yml` smoke-tests the public site every 15 minutes.

## Conventions

- Code, comments, commit messages and PRs are in English.
- Each roadmap phase is its own branch and PR, with tests. Merge PRs with a merge commit, then deploy with `deploy.sh`.
- Never store recordings or typed text on the server, and never log them. Student audio is never sent to third-party speech APIs.
- Configure logging before importing model code: `epitran` calls `logging.basicConfig(level=CRITICAL)` on import.
  The app logs from INFO. Libraries that log through the root logger, and transformers, log errors only: Piper warns
  once per missing phoneme, and transformers on every transcription.
- Shell scripts keep LF line endings (`.gitattributes`), and `deploy/deploy.sh` stays executable (mode 100755).
- Write files that contain backslashes with an editor, not a shell heredoc.

## Roadmap

The full plan is in the maintainer's Claude plan file. Status:
- **Phase 0** (hardening, school-safe sentences, public-domain voice): done.
- **Phase 1** (foundation): health endpoints, JSON logs, gthread workers, dependency lock with hashes, pinned models
  and images, multi-stage Dockerfile, CI and canary, blue/green deploys behind Caddy, docs. `checklist.md` lists the
  flows it touches.
- **Phase 2, performance:** IPA lookup in memory, faster-whisper int8 (drops torch, most of the image), a bounded queue
  that answers 503 with Retry-After, static caching, pre-rendered TTS for bank sentences.
- **Phase 3, scoring accuracy:** build the evaluation harness first, then Levenshtein alignment, text normalisation, VAD and IPA comparison.
- **Phase 4, frontend:** UX, mobile, accessibility, and in-app browsers such as Zalo.
- **Phases 5-7** (learning features, phoneme-level scoring, school platform): only when chosen.
