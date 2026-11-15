# AI Pronunciation Trainer: English edition (aitrainer.ism.io.vn)

Students (mostly Vietnamese school children) read an English sentence aloud and get a score per word and per letter.
This is a fork of [Thiagohgl/ai-pronunciation-trainer](https://github.com/Thiagohgl/ai-pronunciation-trainer) (AGPL-3.0),
trimmed to English. `README.md` describes it for readers; this file is the short version for working on it.

## How it fits together

- `webApp.py`: Flask app, served by gunicorn (`gunicorn.conf.py`: gthread, 2 workers × 24 threads, a worker takes no more connections
  than it has threads, no keep-alive) in Docker.
  Cloudflare is in front, through a tunnel on VM 202 (172.16.10.20) to VM port 3000, where Caddy forwards to the
  live colour (blue or green). Cloudflare drops requests after 125 s (error 524). With gthread workers, gunicorn's
  `timeout` no longer interrupts a slow request, so every step bounds itself.
- API routes accept only `application/json` (others get 415). Every error is JSON `{"error", "code"}`:
  - `POST /getSample`: a sentence from the bank, `category` 0 to 3 (random, easy, medium, hard).
  - `POST /getCustomSample`: the user's own text, with its IPA.
  - `POST /getAudioFromText`: Piper TTS, returned as base64 WAV.
  - `GET /tts/<language>/<key>.mp3`: a bank sentence read aloud, cached for a year (the key hashes voice and sentence;
    `/getSample` returns it as `tts_url`).
  - `POST /GetAccuracyFromRecordedAudio`: scores a recording.
  - `GET /healthz` (the worker answers), `/readyz` (every worker warmed up), `/version` (`GIT_SHA`, `GIT_DATE`).
- Scoring pipeline (serialised per worker by `_inference_lock`; one `scored` log line per request with timings):
  0. `lambdaSpeechToScore.ScoringQueue`: a worker holds at most `GUNICORN_THREADS - 4` recordings (and none that would
     wait over 30 s); the next ones get 503 `busy` with `Retry-After`, and app.js sends them again (3 times at most;
     each attempt has its own 100 s), as does `deploy/smoke_test.py` (deploy.sh and the canary). The warm-up takes no
     place in the queue, and a cold pipeline's first full pass (the warm-up's or a learner's) stays out of the
     queue's estimate.
     A recording whose client left while it waited is skipped (`client_gone`, from the socket gunicorn hands Flask).
  1. `audioPreprocessing.decode_audio`: one ffmpeg process, bounded by size, allocations, codecs, streams and time,
     single-threaded, at most `AUDIO_DECODE_CONCURRENCY` (4) per worker at once (every thread counts against the
     colour's `--pids-limit 512`). It returns numpy float32 `[1, samples]`; torch is gone since phase 2.
  2. Whisper base on faster-whisper (`whisper_wrapper.py`, CTranslate2 int8, greedy, English pinned), model files
     pinned in `model_pins.py`. The transcript is Whisper's text; each of its words gets the span of the timed
     words it is made of (Whisper times "well-known" or "2:30" as two), so the two lists always line up. A window
     Whisper rates as probably not speech is skipped however sure it is of its words (`log_prob_threshold=None`):
     noise as the page sends it was transcribed. `hallucination_silence_threshold` stays off: it dropped a single
     word said before a pause.
  3. `pronunciationTrainer.py`: both sides read as said (`WordMatching.canonical`: numbers, times, hyphens, spellings;
     `same_sound`: homophones by the CMU dictionary), then words and letters aligned by edit distance (Needleman-Wunsch,
     pure Python since phase 3: dtwalign and its numba, scipy and matplotlib are gone); reference IPA from `eng_to_ipa`, with the
     CMU dictionary in memory (`RuleBasedModels.CmuIpa`; `tests/test_ipa.py` holds it to eng_to_ipa's output on the bank).
- `piperTTS.py`: the reference voice (Piper, `en_US-ljspeech-medium`, public domain). Voice files are pinned by sha256
  in `model_pins.py`. A text over 900 phonemes is refused, and pieces over 300 phonemes are synthesised in smaller parts.
  At most `PIPER_QUEUE_LIMIT` (2) texts per worker are synthesised or waiting; the next get 503 `tts_busy` and the
  browser reads them. MP3s (bank sentences) are encoded with ffmpeg.
- `validation.py`: shared input limits, enforced before any model runs.
  - Text: up to 300 characters or 60 words, and at least 90% A-Z letters. The TTS route also accepts single short
    words such as "André" or "2:30". Control characters other than whitespace, and lone UTF-16 surrogates, are refused.
  - Audio: up to 35 s, in a request of up to 4 MB.
- `databases/data_en.csv`: the sentence bank, from Tatoeba (CC BY 2.0 FR, credited in the footer).
  It is screened for school use, and `tests/test_content.py` fails on blocked topics and on duplicates. A second
  review (2026-11) read every sentence; `tests/content_removed_en.tsv` lists the 357 it removed, which must not
  come back.
- Frontend: `templates/main.html`, `static/javascript/app.js` and `static/css/style.css`.
  The CSP forbids inline scripts and styles, and the client's `normalizeText` must stay in step with `validation.normalize_text`.
  The page loads nothing from other sites: fonts are in `static/fonts` (OFL), the result chime is synthesised.
  `webApp.ASSET_VERSION` hashes style.css and app.js; only `?v=<current>` (and the fonts, and the bank MP3s) are
  cached as immutable, the page is `no-cache` and the API `no-store`.
- Health: each gunicorn worker writes a marker (`readiness.py`) after a warm-up that scores a real spoken sentence; the
  warm-up starts in gunicorn's `post_worker_init`, not on import. `healthcheck.py` (the Docker `HEALTHCHECK`) and `/readyz`
  count the markers of live workers.
- Logs (`logging_setup.py`): one JSON object per line, with the request id (`rid`, Cloudflare's Ray ID). App loggers come
  from `logging_setup.get_logger(__name__)` (namespace `aipt`) and log from INFO; `print` is not used.
- `evaluation/` (not in the image): the scoring evaluation harness of phase 3, `evaluation/README.md`. 435 synthetic
  recordings (Piper's voice; learners' mistakes made in the phonemes, noise, soft speech, Chrome-recorded noise) with
  the truth for every word, a harness that scores them as the server does, and the text simulation over the bank.
  `evaluation/report.md` is the report of `harness.REPORT['run']`; `tests/test_evaluation.py` fails when the code no
  longer gives that run's labels from what Whisper heard. A change to the scoring brings its own run and report.

## Commands

```bash
# Tests. The fast suite fakes Whisper and Piper (FakeASR / FakeVoice in tests/conftest.py).
FFMPEG_BINARY=<path to ffmpeg> PYTHONUTF8=1 python -m pytest -q
python -m pytest -q -m slow     # real Whisper and Piper

OPEN_BROWSER=0 python webApp.py   # local server on :3000
docker build --build-arg GIT_SHA=$(git rev-parse --short HEAD) -t ai-pronunciation-trainer .
scripts/lock.sh [--upgrade | --check]   # requirements*.lock from requirements*.in (needs uv)

# Scoring evaluation (evaluation/README.md): a full run belongs in the image (see there).
python -m evaluation.harness rescore evaluation/runs/phase2-1c4813c.json --out evaluation/runs/<name>.json --every 1
python -m evaluation.harness report evaluation/runs/<name>.json --against evaluation/runs/phase2-1c4813c.json
python -m evaluation.harness report --committed   # evaluation/report.md from harness.REPORT
```

The Docker build runs a strict warm-up and fails if the image cannot score a spoken sentence. The runtime stage's
layers are the models, the Python packages, the system packages and then the code, so a code change rebuilds only a
few MB. The system packages are upgraded again when `SYSTEM_REFRESH` changes: `scripts/system_refresh.sh` derives it
from Debian's package indexes, so a Debian update reaches the next build (deploy.sh and CI fall back to the ISO week
when Debian cannot be reached within about a minute). The image gets only what the Dockerfile's `COPY` lines name:
deploy.sh builds from a `git archive` tar, to which `.dockerignore` does not apply. Add a new runtime file to those
`COPY` lines and to `.dockerignore` (used by directory builds such as CI's); `tests/test_build.py` checks that the
two agree.

## Dependencies

- `requirements.in` lists direct dependencies; `requirements.lock` pins everything with hashes (CPython 3.12, Linux
  x86_64, all from PyPI). Regenerate with `scripts/lock.sh`; CI fails if the lock does not match. `setuptools` is
  listed although nothing imports it: it builds eng-to-ipa (no wheel), from the lock.
  Versions: the newest release that is at least 7 days old (uv `--exclude-newer`), unless a security fix needs newer.
- The image installs `requirements.lock` with `--require-hashes` (see the Dockerfile).
- `model_pins.py` pins Whisper and the Piper voices; the base image and the Caddy image are pinned by digest.

## Deploying

Production is a Caddy proxy and two app colours on the VM in `deploy/RUNBOOK.md`. To deploy:
1. Wait until CI has passed on main. deploy.sh asks the GitHub API and refuses a commit whose run failed, was
   cancelled or is still going. It only warns, and deploys, when GitHub cannot be asked, `origin` is not a GitHub
   URL or the commit has no run, so read its first lines. `SKIP_CI_CHECK=1` skips the check.
2. On the VM, check out main.
3. Run `nohup deploy/deploy.sh > ~/deploy-<date>.log 2>&1 < /dev/null &`.

`deploy.sh` does the following:
1. Builds the image from `git archive` of the commit (commits of main that contain 4290c3e only; the checkout is
   not changed), with `SYSTEM_REFRESH` from `scripts/system_refresh.sh`. The tar context ignores `.dockerignore`,
   so the Dockerfile lists what it copies.
2. Starts it in the idle colour (`127.0.0.1:3001` or `3002`), waits until healthy and runs that commit's
   `deploy/smoke_test.py`, which scores a TTS sentence end to end. On failure the previous release goes back
   into that colour, stopped.
3. Switches Caddy to it with a graceful reload (Caddy validates every configuration first) and smoke-tests it
   through port 3000. The new colour may already be busy, so the quick checks get up to 60 s each
   (`PROD_SMOKE_TIMEOUT`) and the page, sample, TTS and scoring checks 120 s. It switches back on failure, at the
   first check without an answer or with a 502/504. The live colour is what Caddy's admin API says, not the file.
4. Records the deploy in `~/.local/state/ai-pronunciation-trainer/deploys.log` and keeps the old colour running
   for 65 s: Caddy sends it the requests that arrived before the switch once their body is in, and gives a client
   up to 60 s (`READ_BODY_SECONDS`) to send it. Then it stops the old colour (it finishes its requests, up to
   120 s; kept for `deploy.sh --rollback`) and keeps the images of the last 3 deploys.

On a host that still has the single container of earlier versions, the first run moves it behind the proxy (a few
seconds without service, once) and keeps it as `ai-pronunciation-trainer-legacy`. Interrupted runs undo themselves;
a run killed while moving the single container is finished or undone by the next run; one deploy runs at a time.
`deploy.sh --status` shows what is live. Any change to deploy/ runs the fault-injection harness (`deploy/test/run.sh`,
also in CI as `deploy-test.yml`).

Rollback: `deploy/deploy.sh --rollback` (the previous colour, no downtime), `deploy/deploy.sh --rollback-legacy`
(the single container from before the proxy, with downtime), or `deploy/deploy.sh <sha>` for a version from
phase 0b (4290c3e) on. 4290c3e's own Dockerfile pins only torch and torchaudio and downloads the models again, so
its rebuild takes minutes and is not the image that ran; `--rollback-legacy` restores that one. deploy.sh refuses
every commit that does not contain 4290c3e (`OLDEST_RELEASE`), in a deploy and in `--rollback`: the phase 0a
commits still have the unscreened sentences or the voice licensed for research only, and older ones (51c9af9, kept
as `ai-pronunciation-trainer:english-ui`) have no smoke test or HEALTHCHECK either. Cloudflare blocks Python's
urllib user agent: check the public site in a browser, or run the smoke test with `--user-agent`.

CI (`.github/workflows/ci.yml`) checks every PR and push to main: ruff, shellcheck, actionlint, the lock (hashes
included), pip-audit, pytest, then the image (smoke test; the tests inside it, run against the image's own `/app`
without network; Trivy). A test that reads other files of the repository belongs in `tests/test_build.py`, which
runs only outside the image.
`canary.yml` smoke-tests the public site every 15 minutes.

Known limits: more recordings at once than the two workers take (40) are answered 503 and sent again by the page,
and a burst can turn a few away from one worker while the other has room;
a Caddy reload can fail a request at that instant: one sent on an idle keep-alive connection, or, rarely, a new
connection that Caddy resets; nothing on the VM limits requests per client: Caddy holds request bodies in up to 1 GB (it
held about 110 uploads of 4.9 MB at once), and beyond that the kernel can kill it, which cuts every request
through port 3000 until docker has restarted it. Noise recorded through Chrome's capture path (its noise suppression
on) can still be transcribed as a sentence (1 of 3 in the evaluation set); since phase 3, Silero VAD keeps the rest of
the noise from Whisper, which turned white noise recorded by the page into "I'm sorry.", and recordings are scaled by
a robust level, so a soft phrase after a much louder tap on the phone is heard (15 of 15, refused before). The VM (Proxmox VM 209)
runs with `cpu: host` since 2026-11-15, on a Xeon E5-2670 v2 (Ivy Bridge): AVX, but no AVX2, FMA or AVX-512
(`x86-64-v3` needs AVX2 and would not start). Whisper takes about 1.8 s per recording there, against 0.6-0.8 s on a
dev machine with AVX2, and a class of 40 at once waits up to 40 s; int8 stays faster than float32 on it (4.7 s
against 5.5 s for three clips). Before the switch (`x86-64-v2-AES`, no AVX) it was 2.2 s and 46 s.
Cloudflare turns the app's `no-cache` for an old `?v=` asset into `max-age=14400` (the zone's browser cache TTL).

## Conventions

- Code, comments, commit messages and PRs are in English.
- Each roadmap phase is its own branch and PR, with tests. Merge PRs with a merge commit, then deploy with `deploy.sh`.
- Never store recordings or typed text on the server, and never log them. Student audio is never sent to third-party speech APIs.
- Configure logging before importing model code: `epitran` calls `logging.basicConfig(level=CRITICAL)` on import.
  The app logs from INFO. Libraries that log through the root logger log errors only: Piper warns once per missing
  phoneme, and faster-whisper logs every transcription at INFO.
- ONNX Runtime's own logger writes plain text to stderr, and on a VM whose display is not a PCI device (Hyper-V, as
  on GitHub's runners) it warns as soon as it is imported. Its first import must go through
  `piperTTS.import_onnxruntime()`, which logs those lines as JSON and then keeps ONNX Runtime to errors.
  `webApp.start_warm_up` calls it while the worker still has one thread, since it points the process's stderr at a
  file for that moment. `whisper_wrapper` calls it too before importing faster_whisper, whose VAD would import it.
- Shell scripts keep LF line endings (`.gitattributes`), and `deploy/deploy.sh` stays executable (mode 100755).
- Write files that contain backslashes with an editor, not a shell heredoc.

## Roadmap

The full plan is in the maintainer's Claude plan file. Status:
- **Phase 0** (hardening, school-safe sentences, public-domain voice): done.
- **Phase 1** (foundation): health endpoints, JSON logs, gthread workers, dependency lock with hashes, pinned models
  and images, multi-stage Dockerfile, CI and canary, blue/green deploys behind Caddy, docs. Deployed 2026-11-15
  (e4a1693). `checklist.md` lists the flows it touches.
- **Phase 2, performance** (deployed 2026-11-15, eec70e3): IPA lookup in memory, faster-whisper int8 (no torch), a
  bounded queue that answers 503 with Retry-After and a client that sends again, 24 threads per worker, static
  files cached by content version, fonts served by the app, bank sentences as cacheable MP3s (rendered on first
  request, then kept by Cloudflare), 32 kbps recordings, `scripts/load_test.py`.
- **Phase 3, scoring accuracy** (branch `phase3/scoring`): the evaluation harness first (`evaluation/`, done: its report
  went to the user for a decision), then Levenshtein alignment, text normalisation, VAD and IPA comparison, each judged
  by the harness's report and merged only if it improves.
- **Phase 4, frontend:** UX, mobile, accessibility, and in-app browsers such as Zalo.
- **Phases 5-7** (learning features, phoneme-level scoring, school platform): only when chosen.
