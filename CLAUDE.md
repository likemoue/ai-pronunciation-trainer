# AI Pronunciation Trainer: English edition (aitrainer.ism.io.vn)

Students (mostly Vietnamese school children) read an English sentence aloud and get a score per word and per letter.
This is a fork of [Thiagohgl/ai-pronunciation-trainer](https://github.com/Thiagohgl/ai-pronunciation-trainer) (AGPL-3.0),
trimmed to English.

## How it fits together

- `webApp.py`: Flask app, served by gunicorn (`gunicorn.conf.py`) in Docker. Cloudflare is in front, through a tunnel
  from another LAN machine to VM port 3000. Cloudflare drops requests after 125 s (error 524).
- API routes accept only `application/json` (others get 415). Every error is JSON `{"error", "code"}`:
  - `POST /getSample`: a sentence from the bank, `category` 0 to 3 (random, easy, medium, hard).
  - `POST /getCustomSample`: the user's own text, with its IPA.
  - `POST /getAudioFromText`: Piper TTS, returned as base64 WAV.
  - `POST /GetAccuracyFromRecordedAudio`: scores a recording.
- Scoring pipeline:
  1. `audioPreprocessing.decode_audio`: one ffmpeg process, bounded by size, allocations, codecs, streams and time.
  2. Whisper base (`whisper_wrapper.py`, transformers).
  3. `pronunciationTrainer.py`: word alignment with DTW in `WordMatching.py`; reference IPA from `eng_to_ipa` in `RuleBasedModels.py`.
- `piperTTS.py`: the reference voice (Piper, `en_US-ljspeech`, public domain). Voice files are pinned by sha256.
  A text over 900 phonemes is refused, and pieces over 300 phonemes are synthesised in smaller parts.
- `validation.py`: shared input limits, enforced before any model runs.
  - Text: up to 300 characters or 60 words, and at least 90% A-Z letters. The TTS route also accepts single short
    words such as "André" or "2:30". Control characters other than whitespace, and lone UTF-16 surrogates, are refused.
  - Audio: up to 35 s, in a request of up to 4 MB.
- `databases/data_en.csv`: the sentence bank, from Tatoeba (CC BY 2.0 FR, credited in the footer).
  It is screened for school use, and `tests/test_content.py` fails on blocked topics and on duplicates.
- Frontend: `templates/main.html`, `static/javascript/app.js` and `static/css/style.css`.
  The CSP forbids inline scripts and styles, and the client's `normalizeText` must stay in step with `validation.normalize_text`.
- Health: each gunicorn worker writes `READY_DIR/<pid>` after a warm-up that scores a real spoken sentence.
  `healthcheck.py`, the Docker `HEALTHCHECK`, counts those markers.

## Commands

```bash
# Tests. The fast suite fakes Whisper and Piper (FakeASR / FakeVoice in tests/conftest.py).
FFMPEG_BINARY=<path to ffmpeg> PYTHONUTF8=1 python -m pytest -q
python -m pytest -q -m slow     # real Whisper and Piper

OPEN_BROWSER=0 python webApp.py   # local server on :3000
docker build --build-arg GIT_SHA=$(git rev-parse --short HEAD) -t ai-pronunciation-trainer .
```

The Docker build runs a strict warm-up and fails if the image cannot score a spoken sentence.

## Deploying

Production is one container on the VM in `deploy/RUNBOOK.md`. To deploy:
1. On the VM, check out main.
2. Run `nohup deploy/deploy.sh > ~/deploy-<date>.log 2>&1 &`.

`deploy.sh` does the following:
1. Builds the image.
2. Starts it as staging on `127.0.0.1:3001` and runs `deploy/smoke_test.py`, which scores a TTS sentence end to end.
3. Swaps production on port 3000.
4. Puts the old container back on any failure or interruption. A run killed half-way is detected by the next run,
   and only one deploy runs at a time.
5. Records successful deploys in `~/.local/state/ai-pronunciation-trainer/deploys.log` and keeps the images of the last 3 deploys.

Rollback means running `deploy/deploy.sh <sha>` for a version from phase 0a on. Older versions (51c9af9, kept as
`ai-pronunciation-trainer:english-ui`) have no smoke test or HEALTHCHECK; deploy.sh refuses them, and the RUNBOOK
swaps to them by hand. Cloudflare blocks Python's urllib user agent, so check the public site in a browser.

## Conventions

- Code, comments, commit messages and PRs are in English.
- Each roadmap phase is its own branch and PR, with tests. Merge PRs with a merge commit, then deploy with `deploy.sh`.
- Never store recordings or typed text on the server. Student audio is never sent to third-party speech APIs.
- Configure logging before importing model code: `epitran` calls `logging.basicConfig(level=CRITICAL)` on import.
  The app logs from INFO. Libraries that log through the root logger log errors only, because Piper warns once per
  missing phoneme; transformers keeps its own handler.
- On the Windows dev machine git converts line endings. `deploy/deploy.sh` must stay LF and executable (mode 100755).

## Roadmap

The full plan is in the maintainer's Claude plan file. Status:
- **Phase 0** (hardening, school-safe sentences, public-domain voice): done.
- **Phase 1** (branch `phase1/foundation`):
  - Done so far: `/healthz`, `/readyz`, `/version`, JSON logs with request ids, gthread workers, and removal of the dead Silero/German TTS code.
  - Still to do: dependency lock with hashes, multi-stage Dockerfile, GitHub Actions CI with a canary, blue/green deploy behind Caddy, docs.
- **Phase 2, performance:** IPA lookup in memory, faster-whisper int8, a bounded queue that answers 503 with Retry-After, static caching, pre-rendered TTS for bank sentences.
- **Phase 3, scoring accuracy:** build the evaluation harness first, then Levenshtein alignment, text normalisation, VAD and IPA comparison.
- **Phase 4, frontend:** UX, mobile, accessibility, and in-app browsers such as Zalo.
- **Phases 5-7** (learning features, phoneme-level scoring, school platform): only when chosen.
