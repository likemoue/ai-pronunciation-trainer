# Fault-injection harness for deploy.sh

Runs the real `deploy/deploy.sh` against a stand-in app, with failures and signals injected at every step and
traffic running, and checks what is left: what port 3000 serves, which containers exist, the deploy log, the
images.

```bash
deploy/test/run.sh                               # every scenario, about 25 minutes
deploy/test/run.sh 1:b1_lifecycle 2:b7_misc      # some of them
```

It needs only docker (Linux, or Git Bash with Docker Desktop). CI runs it when `deploy/` changes
(`.github/workflows/deploy-test.yml`). Results are in `deploy/test/out/`: `<scenario>.txt` lists every check,
`<scenario>.runN.log` is what deploy.sh printed and `<scenario>.runN.trace` every docker command it ran, with the
time.

## How it works

- `harness/app/` is a 60-line stand-in for the app: `GET /` answers `ok <commit>`, `/slow` answers after 1.5 s,
  and on SIGTERM it finishes the requests it has, like gunicorn. A commit can be made `bad` (never healthy) or
  `crash` (exits at once).
- Each scenario creates a fake origin repository and commits to it; deploy.sh runs from a clone of it, as on the
  server, with real docker, a real Caddy and the stand-in app.
- `harness/bin/docker` wraps the docker CLI for deploy.sh only. It can make a step fail (`FAULT_STAGING`,
  `FAULT_RELOAD`, `FAULT_PROXY_START`, `FAULT_INSPECT_FAIL`) and send a signal at a named point (`FAULT_SIG_AT`,
  see `harness/bin/fire`): to deploy.sh alone, to its whole process group (Ctrl-C), or by closing its terminal
  (a dropped SSH session, `harness/pty_run.py`).
- `harness/traffic.py` sends requests to port 3000 throughout (six threads, new connection per request, some of
  them in flight for 1.5 s). A request may fail only in the moment of a `caddy reload`, when Caddy closes its idle
  connections (deploy/RUNBOOK.md); any other failure fails the scenario.
- Three lanes use their own names, ports (3391-3399) and directories, so they run side by side.

## Scenarios

| Scenario | What it checks |
|---|---|
| `b1_lifecycle` | A fresh host: the first deploy starts the proxy; later deploys alternate colours; `--rollback` both ways; re-deploying the same commit; image pruning; `--status` |
| `b2_legacy` | A host with the single container of earlier versions: the move behind the proxy (and how long the port is unavailable); `--rollback` with no previous colour; `--rollback-legacy`; moving again |
| `b3_failures` | Releases that fail: unhealthy, crashing, a taken port, a failed `docker run`, failed smoke tests before and after the switch, a failed `caddy reload`; production keeps serving and `--rollback` still finds the previous release |
| `b4_signals` | SIGINT, SIGTERM and SIGHUP at every step of a deploy, to deploy.sh or its process group, with and without `nohup` |
| `b5_kill` | SIGKILL at every step, including right before `caddy reload`, then deploying again |
| `b6_migration` | Failures, signals and SIGKILL during the move behind the proxy, then deploying again |
| `b7_misc` | One deploy at a time; output through a `tee` that dies; leftovers of the old deploy.sh; refs that are not on main, unpushed, or have no smoke test; a stopped proxy; a hand-edited Caddyfile; `--replace-proxy`, `--status`, `--help` |
