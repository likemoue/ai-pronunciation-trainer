# Flows to check

Each feature adds the flows it touches. Before a release is called done, walk through them on the public site
right after the deploy (deploy.sh goes from its checks to the switch without stopping). `--rollback` undoes a
release without downtime, except the first deploy with the phase-1 deploy.sh, which leaves no previous colour:
`deploy.sh --rollback-legacy` undoes that one, with downtime. "Auto" means a test, a CI job or a deploy step
already checks it on every change.

## Phase 1: foundation (2026-11)

### Learner flows (behaviour unchanged; the stack under them changed)
- [ ] Open the page: sentence, IPA, audio button, record button; no console errors (CSP). Auto: smoke test (page + CSP header).
- [ ] New sentence in each level (easy, medium, hard, random). Auto: smoke test (one level), `tests/test_api.py`.
- [ ] Your own text: accepted, refused when too long, not English, or with hidden characters. Auto: `tests/test_api.py`.
- [ ] Listen to the reference voice (Piper) for a bank sentence and for your own text. Auto: smoke test (TTS).
- [ ] Record and score a sentence: score, letter colours, per-word IPA and playback. Auto: smoke test, warm-up at build
      and start, the slow tests in the image (CI). Checked once: the same 105 recordings scored identically with
      transformers 4.57/torch 2.8 and 5.22/2.15.
- [ ] Silence, a recording over 30 s, an unreadable file: the right message. Auto: `tests/test_api.py`, `tests/test_audio_decode.py`.
- [ ] Phone browsers (Chrome Android, Safari iOS, Zalo in-app browser): record and score once each.

### Operations
- [ ] Wait for CI on main to pass; deploy.sh refuses a commit whose CI run failed, was cancelled or is still
      going, and only warns when it cannot ask GitHub or the commit has no run (read its first lines).
- [ ] First deploy with the new deploy.sh moves the single container behind Caddy; port 3000 is unavailable for a
      few seconds, once (deploy.sh prints how long). Then `deploy/deploy.sh --status` shows the proxy and blue live.
- [ ] A normal deploy drops no request in flight, uploads still arriving at the switch included. Auto: deploy
      harness (`deploy/test/`, CI when deploy/ changes).
      Check once on the server with the public site open.
- [ ] After the second deploy behind the proxy (the first leaves no previous colour): `deploy/deploy.sh --rollback`
      and back again, then `deploy/deploy.sh <older sha>`.
- [ ] A failed release (staging or through the proxy) leaves the live colour serving and the previous release in
      place for `--rollback`. Auto: deploy harness.
- [ ] Interrupted or killed deploys (Ctrl-C, dropped SSH, SIGKILL) recover. Auto: deploy harness. A reboot during a
      deploy is not covered: Caddy restarts with the last configuration it was given. After one, run
      `deploy/deploy.sh --status` before anything else.
- [ ] `/healthz`, `/readyz`, `/version` through Cloudflare. Auto: smoke test (`/version` printed), canary.
- [ ] Logs: `docker logs ai-pronunciation-trainer-<colour>` shows JSON lines with `rid`; one `scored` line per
      recording; no text or audio in any line. Auto: `tests/test_operations.py`, the slow test that a worker start
      logs only JSON.
- [ ] The canary runs every 15 minutes in GitHub Actions and is green; a failure sends an e-mail.
- [ ] Cloudflare's 125 s limit: a long recording (30 s) still scores well under it.
- [ ] The container opens no connection to the internet (Hugging Face offline, Hugging Face and ONNX Runtime
      telemetry off). Auto, in part: `tests/test_build.py` checks the image's settings and that ONNX Runtime's
      telemetry is off before onnxruntime is first imported. Checked by hand in this phase with a DNS logger: no
      lookup while a container started and scored. The tests in the image run without network, which shows that
      the app works offline but would not notice an attempt to connect.
- [ ] Image rebuild after a code-only change reuses the dependency and model layers (`docker history`).

### Development
- [ ] `scripts/lock.sh --check` passes; `scripts/lock.sh --upgrade` moves to releases at least 7 days old.
- [ ] CI is green on the PR: lint, locks, pip-audit, tests, image (smoke test, tests inside, Trivy), deploy harness.
- [ ] `pip install -r requirements.txt` and `python -m pytest -q` on a developer machine.
