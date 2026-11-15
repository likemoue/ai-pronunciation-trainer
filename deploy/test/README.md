# Fault-injection harness for deploy.sh

Runs the real `deploy/deploy.sh` against a stand-in app, with failures and signals injected at every step and
traffic running, and checks what is left: what port 3000 serves, which containers exist, the deploy log, the
images, and that no request failed.

```bash
deploy/test/run.sh                                     # every scenario, in three lanes, about 17 minutes
deploy/test/run.sh 1:b1_lifecycle 2:b6_migration,b7_misc   # some of them: <lane>:<scenario>[,<scenario>...]
```

It needs only docker (Linux, or Git Bash with Docker Desktop; the 17 minutes were measured with Docker Desktop on
16 CPUs). CI runs it when `deploy/` changes (`.github/workflows/deploy-test.yml`). Results are in
`deploy/test/out/` (or `OUT_DIR`): `<scenario>.txt` lists every check, `<scenario>.runN.log` is what deploy.sh
printed and `<scenario>.runN.trace` every docker command it ran, with the time. A run removes only the harness's
own earlier results there.

`run.sh` exits 0 only if every scenario ran to its end (its `.txt` ends with `FAILS=0`), exited 0 and made at
least as many checks as it always makes (`MIN_CHECKS` in `run.sh`); 1 otherwise; and 2, having started and
removed nothing, if an argument is not a lane 1-3 with existing scenarios or another run uses the docker daemon. The
harness uses the containers, images and networks `aipt-deploy-harness` and `aipt-bg1`..`aipt-bg3`, and
`/tmp/aipt-bg` on the daemon, and touches nothing else; one harness runs at a time per daemon (its container is
the lock; one left by a run.sh that was killed is replaced).

## How it works

- `harness/app/` is a stand-in for the app: `GET /` answers `ok <commit>`, `/slow?ms=N` answers after N ms, and
  a `POST` once it has read the body. On SIGTERM it finishes the requests it has (for up to 9 s), like gunicorn,
  but it is stricter about the rest, so it hides no request that the app would drop: it refuses new connections
  at once, and does not answer a request that comes after SIGTERM on a connection Caddy kept alive. gunicorn 26
  (gthread) answers requests on kept-alive connections while it finishes, and leaves new connections waiting in
  its backlog until the worker exits, then resets them. A commit can be made `bad` (never healthy) or `crash`
  (exits at once).
- Each scenario creates a fake origin repository, whose first commit is `OLDEST_RELEASE`, and commits to it;
  deploy.sh runs from a clone of it, as on the server, with real docker, a real Caddy and the stand-in app.
  `harness/lib.sh` sets `READ_BODY_SECONDS=3` and `DRAIN_MARGIN=1`, so a colour that loses the traffic is stopped
  4-5 s after the reload, and `SYSTEM_REFRESH=harness`.
- `harness/bin/docker` wraps the docker CLI for deploy.sh. It can make a step fail (`FAULT_STAGING`,
  `FAULT_RELOAD`, `FAULT_PROXY_START`, `FAULT_INSPECT_FAIL`) and send a signal at a named point (`FAULT_SIG_AT`,
  see `harness/bin/fire`): to deploy.sh alone, to its whole process group (Ctrl-C), or by closing its terminal
  (a dropped SSH session, `harness/pty_run.py`). `FAULT_CREATE_LAG=<seconds>` makes the daemon create the new
  colour late, as it may after the docker CLI gave up on a signal: right after deploy.sh's next `docker rm -f` of
  that colour, or that many seconds after the `docker run` if none comes. A deploy.sh that let the signal reach
  that `docker run` would then lose the previous release every time. A case whose signal was never sent (its
  deploy failed before that point) fails, as does a `b3` case that did not get as far as staging and a `b6` case
  whose move never began.
  `harness/bin/git` and `harness/bin/curl` stand in for GitHub (`FAKE_GITHUB_REPO`, `FAKE_CI`) to test the CI
  gate, and `harness/caddy-fake/` builds a Caddy that refuses the Caddyfiles that contain a given text.
- `harness/traffic.py` sends requests to port 3000 throughout, each on a new connection: fast ones, slow ones
  (1.5 s), long ones (8 s) and slow uploads (32 KB over 1.4 s). At every `caddy reload` (`bin/docker` traces it
  and waits 0.3 s before it reloads), it also sends an upload whose body is complete 2.2 s later (Caddy sends it
  to the colour that loses the traffic once it has all of it) and a 6.5 s request to that colour, still in flight
  when it is stopped; after a switch and after a switch back. `harness/traffic_check.py` requires, in each traffic run with
  switches, a long request in flight on a colour when it was stopped and an upload sending its body during a
  reload, and that every request succeeded, with one exception: a `caddy reload` can reset a connection that
  reaches the proxy at that instant, even a new one (3 of about 70,000 requests in one full run; with Caddy
  alone, 2 to 7 per 100 reloads). It excuses only that: a connection reset or closed without an answer, never an
  HTTP error such as 502, within 0.5 s, started during a reload that reached Caddy or up to 0.5 s after it
  (`bin/docker` traces the start and the end of each), at most two per reload. It lists every failure. The only
  other failures allowed are those of the move behind the proxy in `b2_legacy`, measured with the fast and slow
  requests only: they must all start between the `docker stop` of the single container and the moment the proxy
  answers, at most 6 s later.
- Three lanes use their own names, ports (3391-3399) and directories, so they run side by side. Their image builds
  and removals take a lock (`bin/docker`, `lib.sh`): Docker's classic builder fails ("unable to find image") when
  another lane removes an image while it looks for a cached step. A build that the daemon fails on its own in
  this way, or because another client changed images at that moment (Docker Desktop: "lease does not exist",
  "failed to export layer"), is tried again; any other failed build is deploy.sh's.

## Scenarios

| Scenario | What it checks |
|---|---|
| `b1_lifecycle` | A fresh host: the first deploy starts the proxy; later deploys alternate colours, and the old colour is stopped only after read_body and the margin; `--rollback` both ways; re-deploying the same commit; image pruning, which keeps a release logged under its own tag (`english-ui`); `--status` |
| `b2_legacy` | A host with the single container of earlier versions: the move behind the proxy (the port is unavailable for at most 6 s, and requests fail only then); `--rollback` with no previous colour; `--rollback-legacy`; moving again |
| `b3_failures` | Releases that fail: unhealthy, crashing, a taken port, a failed `docker run`, failed smoke tests before and after the switch, a failed `caddy reload`; production keeps serving, the switch back drains the new colour, and `--rollback` still finds the previous release |
| `b4_signals` | SIGINT, SIGTERM and SIGHUP at every step of a deploy, to deploy.sh or its process group, with and without `nohup`, including right after the previous release was removed, and during a `docker run` of the new colour that the daemon completes late (`*-run-lag`); the idle colour keeps the release it held |
| `b5_kill` | SIGKILL at every step, including right before `caddy reload`, then deploying again; `--rollback` refuses the release that a killed deploy left in the idle colour |
| `b6_migration` | Failures, signals and SIGKILL during the move behind the proxy. Each case must end as deploy/RUNBOOK.md says, with its exit code: the move undone (the single container serves again), finished and recorded, or, after SIGKILL, left for the next run to finish or undo. Then deploying again |
| `b7_misc` | One deploy at a time; output through a `tee` that dies; leftovers of the old deploy.sh; refs that are not on main, unpushed, or have no smoke test; a stopped proxy; a hand-edited Caddyfile; `--replace-proxy`, `--status`, `--help` |
| `b8_gates` | What stops deploy.sh before it changes anything: a `CADDY_IMAGE` that refuses the configuration (`--replace-proxy` exits 1 and the proxy goes on serving, with traffic running); a proxy on an older Caddy that refuses a new configuration; commits older than `OLDEST_RELEASE`, for a deploy and for `--rollback`; CI's verdict (failure, cancelled, pending, success, no answer). Also no deploy log while a proxy exists, and port 3000 taken while the proxy is stopped |
