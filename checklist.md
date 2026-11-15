# Flows to check

Each feature adds the flows it touches. Before a release is called done, walk through them on the public site
right after the deploy (deploy.sh goes from its checks to the switch without stopping). `--rollback` undoes a
release without downtime, except the first deploy with the phase-1 deploy.sh, which leaves no previous colour:
`deploy.sh --rollback-legacy` undoes that one, with downtime. "Auto" means a test, a CI job or a deploy step
already checks it on every change.

## Phase 2: performance (2026-11)

### Learner flows
- [ ] Record and score a sentence of each level: score, letter colours, per-word IPA and playback, with
      faster-whisper. Auto: smoke test, warm-up at build and start, slow tests in the image. Checked once on the
      parity set (Piper readings of 30 bank sentences, 239 clips): see the PR for the numbers.
- [ ] Noise or silence gives "We couldn't recognise any speech", not an invented sentence. Auto: `tests/test_api.py`
      (silence), the slow tests in the image (noise and hum through the real model; no word after a sentence).
- [ ] A class at once (30-40 recordings within a few seconds): every learner gets a score; anyone the server turns
      away sees "The server is busy - sending your recording again in N s" and gets a score without recording again.
      Auto, in part: `tests/test_queue.py` (503 with Retry-After, places given back). Check once with the load test
      (`scripts/load_test.py`) on the server, outside school hours.
- [ ] Closing the popup while a recording waits: the server skips it (`"outcome": "client_gone"` in the log).
- [ ] Listen to a bank sentence: an MP3 from `/tts/en/<key>.mp3`, from Cloudflare's cache the second time
      (`cf-cache-status: HIT`). Your own text and single words still use `/getAudioFromText`. Auto: `tests/test_bank_audio.py`.
- [ ] The result chime plays (good, okay, needs work) with no sound file downloaded.
- [ ] Fonts come from the app (Network tab: no request to Google), the IPA symbols render in Noto Sans, θ included.
      Auto: `tests/test_static.py` (every IPA symbol of the bank is in a served subset).
- [ ] Phone browsers (Chrome Android, Safari iOS, Zalo in-app browser): record at 32 kbps and score once each.

### Operations
- [ ] A deploy and the canary during a class at work: the smoke test sends busy recordings again and passes.
- [ ] After a deploy, a page opened before it keeps working: its old `?v=` assets are answered with `no-cache`, the
      new page gets the new version. Auto: `tests/test_static.py`.
- [ ] `docker logs`: `scored` lines carry `queue_ahead`, `lock_wait_ms`, `asr_ms`; `busy` outcomes are rare outside a
      class burst.
- [ ] Memory per colour after warm-up and a burst (`docker stats`): far below phase 1's 1.1 GiB.
- [ ] The image is far smaller than phase 1's 3.9 GB (no torch); a code-only rebuild reuses the dependency and model
      layers.

## Phase 1: foundation (2026-11)

Walked through on the public site on 2026-11-15 after deploying e4a1693 (the boxes below), except where noted.

### Learner flows (behaviour unchanged; the stack under them changed)
- [x] Open the page: sentence, IPA, audio button, record button; no console errors (CSP). Auto: smoke test (page + CSP header).
- [x] New sentence in each level (easy, medium, hard, random). Auto: smoke test (one level), `tests/test_api.py`.
- [x] Your own text: accepted, refused when too long, not English, or with hidden characters. Auto: `tests/test_api.py`.
- [x] Listen to the reference voice (Piper) for a bank sentence and for your own text. Auto: smoke test (TTS).
- [x] Record and score a sentence: score, letter colours, per-word IPA and playback. Auto: smoke test, warm-up at build
      and start, the slow tests in the image (CI). Checked once: the same 105 recordings scored identically with
      transformers 4.57/torch 2.8 and 5.22/2.15. On 2026-11-15 scored with Piper audio through Cloudflare (no
      microphone in the browser used for the check).
- [x] Silence, a recording over 30 s, an unreadable file: the right message. Auto: `tests/test_api.py`, `tests/test_audio_decode.py`.
- [ ] Phone browsers (Chrome Android, Safari iOS, Zalo in-app browser): record and score once each.

### Operations
- [x] Wait for CI on main to pass; deploy.sh refuses a commit whose CI run failed, was cancelled or is still
      going, and only warns when it cannot ask GitHub or the commit has no run (read its first lines).
- [x] First deploy with the new deploy.sh moves the single container behind Caddy; port 3000 is unavailable for a
      few seconds, once (deploy.sh prints how long: 3.6 s on 2026-11-15). Then `deploy/deploy.sh --status` shows
      the proxy and blue live.
- [ ] A normal deploy drops no request in flight, uploads still arriving at the switch included. Auto: deploy
      harness (`deploy/test/`, CI when deploy/ changes).
      Check once on the server with the public site open (at the phase 2 deploy).
- [ ] After the second deploy behind the proxy (the first leaves no previous colour): `deploy/deploy.sh --rollback`
      and back again, then `deploy/deploy.sh <older sha>` (at the phase 2 deploy).
- [x] A failed release (staging or through the proxy) leaves the live colour serving and the previous release in
      place for `--rollback`, unless Caddy did not take the switch back or deploy.sh cannot tell whether it did
      (it then leaves both colours running and says so; deploy/RUNBOOK.md). Auto: deploy harness, except those two
      cases, which no scenario reaches.
- [x] Interrupted or killed deploys (Ctrl-C, dropped SSH, SIGKILL) recover. Auto: deploy harness. A reboot during a
      deploy is handled like SIGKILL, but the harness does not test it. Caddy then starts from the files on disk,
      and `upstream.caddy` already names the new colour if the reboot came between deploy.sh writing it and its
      reload; docker starts every colour that was running, the old one during its drain too. After a reboot, run
      `deploy/deploy.sh --status` before anything else, and stop a colour that is not live (deploy/RUNBOOK.md).
- [x] `/healthz`, `/readyz`, `/version` through Cloudflare. Auto: smoke test (`/version` printed), canary.
- [x] Logs: `docker logs ai-pronunciation-trainer-<colour>` shows JSON lines with `rid`; one `scored` line per
      recording; no text or audio in any line. Auto: `tests/test_operations.py`, the slow test that a worker start
      logs only JSON.
- [x] The canary runs every 15 minutes in GitHub Actions and is green; a failure sends an e-mail. (A manual run passed
      on 2026-11-15; GitHub starts the schedule some time after the workflow reaches main.)
- [x] Cloudflare's 125 s limit: a long recording (30 s) still scores well under it. (The longest practice text, 59
      words and 16.5 s of speech, scored in 11.8 s.)
- [x] The container opens no connection to the internet (Hugging Face offline, Hugging Face and ONNX Runtime
      telemetry off). Auto, in part: `tests/test_build.py` checks the image's settings and that ONNX Runtime's
      telemetry is off before onnxruntime is first imported. Checked by hand in this phase with a DNS logger: no
      lookup while a container started and scored. The tests in the image run without network, which shows that
      the app works offline but would not notice an attempt to connect.
- [ ] Image rebuild after a code-only change reuses the dependency and model layers (`docker history`; at the
      phase 2 deploy).

### Development
- [x] `scripts/lock.sh --check` passes; `scripts/lock.sh --upgrade` moves to releases at least 7 days old.
- [x] CI is green on the PR: lint, locks, pip-audit, tests, image (smoke test, tests inside, Trivy), deploy harness.
- [x] `pip install -r requirements.txt` and `python -m pytest -q` on a developer machine.
