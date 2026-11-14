# Flows to check

Each feature adds the flows it touches. Before a release, walk through them on the staging colour
(`127.0.0.1:3001` or `3002`, through an SSH tunnel) or on the public site. "Auto" means a test or deploy step
already checks it.

## Phase 1: foundation (2026-11)

### Learner flows (behaviour unchanged; the stack under them changed)
- [ ] Open the page: sentence, IPA, audio button, record button; no console errors (CSP). Auto: smoke test (page + CSP header).
- [ ] New sentence in each level (easy, medium, hard, random). Auto: smoke test (one level), `tests/test_api.py`.
- [ ] Your own text: accepted, refused when too long, not English, or with hidden characters. Auto: `tests/test_api.py`.
- [ ] Listen to the reference voice (Piper) for a bank sentence and for your own text. Auto: smoke test (TTS).
- [ ] Record and score a sentence: score, letter colours, per-word IPA and playback. Auto: smoke test, warm-up at build
      and start, `tests/test_pipeline_slow.py` in the image; the same 105 recordings scored identically with
      transformers 4.57/torch 2.8 and 5.22/2.15.
- [ ] Silence, a recording over 30 s, an unreadable file: the right message. Auto: `tests/test_api.py`, `tests/test_audio_decode.py`.
- [ ] Phone browsers (Chrome Android, Safari iOS, Zalo in-app browser): record and score once each.

### Operations
- [ ] First deploy with the new deploy.sh moves the single container behind Caddy; port 3000 is unavailable for a
      few seconds, once (deploy.sh prints how long). Then `deploy/deploy.sh --status` shows the proxy and blue live.
- [ ] A normal deploy drops no request, including one in flight during the switch. Auto: harness (fake app) with
      traffic; check once on the server with the public site open.
- [ ] `deploy/deploy.sh --rollback` and back again; `deploy/deploy.sh <older sha>`.
- [ ] A failed release (staging or through the proxy) leaves the live colour serving. Auto: harness.
- [ ] Interrupted or killed deploys (Ctrl-C, dropped SSH, SIGKILL, a reboot during the move) recover. Auto: harness.
- [ ] `/healthz`, `/readyz`, `/version` through Cloudflare. Auto: smoke test, canary.
- [ ] Logs: `docker logs ai-pronunciation-trainer-<colour>` shows JSON lines with `rid`; one `scored` line per
      recording; no text or audio in any line.
- [ ] The canary runs every 15 minutes in GitHub Actions and is green; a failure sends an e-mail.
- [ ] Cloudflare's 125 s limit: a long recording (30 s) still scores well under it.
- [ ] Image rebuild after a code-only change reuses the dependency and model layers (`docker history`).

### Development
- [ ] `scripts/lock.sh --check` passes; `scripts/lock.sh --upgrade` moves to releases at least 7 days old.
- [ ] CI is green on the PR: lint, locks, pip-audit, tests, image (smoke test, tests inside, Trivy).
- [ ] `pip install -r requirements.txt` and `python -m pytest -q` on a developer machine.
