# Flows to check

Each feature adds the flows it touches. Before a release is called done, walk through them on the public site
right after the deploy (deploy.sh goes from its checks to the switch without stopping). `--rollback` undoes a
release without downtime, except the first deploy with the phase-1 deploy.sh, which leaves no previous colour:
`deploy.sh --rollback-legacy` undoes that one, with downtime. "Auto" means a test, a CI job or a deploy step
already checks it on every change.

## Bank review (2026-11)

- [x] No sentence of the bank is unsuitable for a class: a second review read all 11,028 sentences and removed 357
      (10,671 left), from "Semen is worth bottling." to stereotypes, alcohol, religion and politics.
      Auto: `tests/test_content.py` (the blocklist, now with these topics, and `tests/content_removed_en.tsv`, the
      removed sentences, which must not come back).
- [ ] New sentence in each level after the deploy; every level still has sentences. Auto: `tests/test_content.py`.

## Phase 2: performance (2026-11)

Deployed 2026-11-15 (eec70e3) and walked through the same evening (the boxes below), on the public site in the
built-in browser with a stand-in microphone that plays the server's own voice, and on the server through port 3000.
That evening the server's virtual CPU offered no AVX (`QEMU Virtual CPU version 2.5+`: SSE4.2 at most), so Whisper
took about 2.2 s per recording there, against 0.6-0.8 s on the machine the PR was measured on; the numbers below are
from that CPU. Later the same evening the VM was switched to `cpu: host` (AVX, no AVX2): 1.8 s per recording, and
40 recordings at once 20.6 s at the median, 34.1 s at the 90th percentile and 40.4 s at most (3 sent again). The
site was unavailable for about 2 minutes while the VM restarted.

### Learner flows
- [x] Record and score a sentence of each level: score, letter colours, per-word IPA and playback, with
      faster-whisper. Auto: smoke test, warm-up at build and start, slow tests in the image. Checked once on the
      parity set (Piper readings of 30 bank sentences, 239 clips): see the PR for the numbers. On the public site:
      easy and medium heard word for word, hard with two words misheard (red letters).
- [ ] Noise or silence gives "We couldn't recognise any speech", not an invented sentence. Auto: `tests/test_api.py`
      (silence), the slow tests in the image (white noise as WAV and as the page's WebM/Opus, and hum, through the
      real model; no word after a sentence; a single word before a pause is still scored). By hand, on a phone: tap
      Record and stay silent for 5-8 s. Noise shaped by the browser's noise suppression still gave words in about
      one recording in six in the tests (phase 3: voice activity detection).
      On 2026-11-15: silence never reaches the server (the page says the recording is too short). On the server,
      seeded white noise encoded by ffmpeg gave "no speech" 5 of 5 times as WAV and 4 of 5 as WebM/Opus 32 kbps,
      but white noise recorded by the page in Chromium came back as "I'm sorry." 4 of 4 times, at three levels: the
      learner sees "Keep practising" instead of "We can't hear you" (phase 3).
- [x] A class at once (30-40 recordings within a few seconds): every learner gets a score; anyone the server turns
      away sees "The server is busy - sending your recording again in N s" and gets a score without recording again.
      Auto, in part: `tests/test_queue.py` (503 with Retry-After, places given back). Load test on the server through
      port 3000 on 2026-11-15, 15:02-15:06 UTC: 40 at once, all scored, 10 sent again after a 503, median 24.2 s,
      90th percentile 41.7 s, slowest 46.1 s; 40 over 10 s, all scored, 8 sent again, 22.0 / 39.5 / 43.6 s; 20 at
      once, none sent again, slowest 24.6 s. The page and a sample answered in 0.02 s at most throughout.
- [x] Closing the popup while a recording waits: the server skips it (`"outcome": "client_gone"` in the log).
      A recording behind 8 others, abandoned after 1 s, was skipped 16.6 s later without running Whisper. One
      abandoned while it is being scored is still scored.
- [x] Listen to a bank sentence: an MP3 from `/tts/en/<key>.mp3`, from Cloudflare's cache the second time
      (`cf-cache-status: HIT`). Your own text and single words still use `/getAudioFromText`. Auto: `tests/test_bank_audio.py`.
- [x] The result chime plays (good, okay, needs work) with no sound file downloaded.
- [x] Fonts come from the app (Network tab: no request to Google), the IPA symbols render in Noto Sans, θ included.
      Auto: `tests/test_static.py` (every IPA symbol of the bank is in a served subset). The Greek subset loads for θ.
- [ ] Phone browsers (Chrome Android, Safari iOS, Zalo in-app browser): record at 32 kbps and score once each.

### Operations
- [x] A deploy and the canary during a class at work: the smoke test sends busy recordings again and passes, and
      the learners' recordings are scored while both colours score for about a minute (simulated with two classes
      on 10 CPUs: 80 of 80 scored, the slowest in 26 s; without `GOMP_SPINCOUNT`, 18 of 80 failed). On the server:
      40 recordings over 10 s while deploy.sh started the new colour; the old one scored until 24 s after the switch
      while the new one took the rest: 40 of 40 scored, 15 sent again, median 28.5 s, slowest 54.2 s; Whisper 3.0 s
      per recording instead of 2.2 s; the smoke test through port 3000 waited behind the class and passed (13.9 s).
- [x] After a deploy, a page opened before it keeps working: its old `?v=` assets are answered with `no-cache`, the
      new page gets the new version. Auto: `tests/test_static.py`. The phase 1 page, open across the deploy, took
      a new sentence and scored; it lost only its result sounds (404, phase 2 removed them). Cloudflare turns the
      app's `no-cache` for an old or unknown `?v=` into `max-age=14400` (the zone's browser cache TTL), so after a
      rollback a browser could keep a newer app.js under the old URL for up to 4 hours; a cache rule for this host
      that respects the origin's headers would end that.
- [x] `docker logs`: `scored` lines carry `queue_ahead`, `lock_wait_ms`, `asr_ms`; `busy` outcomes are rare outside a
      class burst.
- [x] Memory per colour (`docker stats`): about 1.1 GiB after warm-up, and under 2.5 GiB after class bursts (each
      waiting recording holds its decoded audio); the colour's limit is 9 GiB. Phase 1, measured the same way, used
      1.5 GiB after warm-up and up to 2.2 GiB after a burst. On the server: 1.08 GiB after warm-up, 1.64 GiB after
      two bursts of 40.
- [x] The image is far smaller than phase 1's 3.9 GB (no torch); a code-only rebuild reuses the dependency and model
      layers. 2.69 GB. A commit that changed only webApp.py, built on the server from `git archive` as deploy.sh
      builds: 36 s (28 s of warm-up); the models (211 MB), Python packages (1.12 GB) and system packages (457 MB)
      layers were the deployed image's own.

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
- [x] A normal deploy drops no request in flight, uploads still arriving at the switch included. Auto: deploy
      harness (`deploy/test/`, CI when deploy/ changes).
      Checked on 2026-11-15 with the phase 2 deploy, the public site open in a browser: across five switches (the
      deploy, two rollbacks, `deploy.sh e4a1693` and the deploy of main again), 4,677 requests through port 3000
      (health, page, sample, and recordings uploaded over 3 s each, some still arriving at a switch) and 4,940
      through Cloudflare (health and version, from before the first switch to after the last) all answered 200.
- [x] After the second deploy behind the proxy (the first leaves no previous colour): `deploy/deploy.sh --rollback`
      and back again, then `deploy/deploy.sh <older sha>` (at the phase 2 deploy). Checked on 2026-11-15: each run
      took about 2 minutes, most of it the old colour's 65 s drain; `deploy.sh e4a1693` came wholly from the build
      cache.
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
- [x] Image rebuild after a code-only change reuses the dependency and model layers (`docker history`; at the
      phase 2 deploy). See phase 2's last box.

### Development
- [x] `scripts/lock.sh --check` passes; `scripts/lock.sh --upgrade` moves to releases at least 7 days old.
- [x] CI is green on the PR: lint, locks, pip-audit, tests, image (smoke test, tests inside, Trivy), deploy harness.
- [x] `pip install -r requirements.txt` and `python -m pytest -q` on a developer machine.
