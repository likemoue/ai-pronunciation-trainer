# Runbook: aitrainer.ism.io.vn

Production runs on the VM `172.16.17.40` as a Caddy proxy in front of two app containers, blue and green.
Cloudflare sits in front. The Cloudflare Tunnel connector runs on VM 202 (`172.16.10.20`, which also runs
Nginx Proxy Manager) and forwards to `172.16.17.40:3000`; every connection to port 3000 comes from that address.

| Item | Value |
|---|---|
| SSH | `ssh -i ~/.ssh/id_ed25519 itadmin@172.16.17.40` (docker access, no sudo); off the LAN, Tailscale `100.121.247.67` |
| Code | `~/ai-pronunciation-trainer` (git, origin = github.com/likemoue/ai-pronunciation-trainer) |
| Proxy | `ai-pronunciation-trainer-proxy`: Caddy, the only container on port 3000 (`0.0.0.0:3000`) |
| App | `ai-pronunciation-trainer-blue` (`127.0.0.1:3001`) and `ai-pronunciation-trainer-green` (`127.0.0.1:3002`). The live one runs; the other holds the previous release, stopped |
| Network | `ai-pronunciation-trainer-net`: the proxy reaches the colours by name |
| Proxy config | `~/.local/state/ai-pronunciation-trainer/proxy/`: `Caddyfile` (written by deploy.sh) and `upstream.caddy` (the live colour) |
| Images | `ai-pronunciation-trainer:<short git sha>`; `:latest` = what is live |
| Deploy log | `~/.local/state/ai-pronunciation-trainer/deploys.log`: one line per successful deploy or rollback (`<UTC time> <sha> <container id>`) |
| Deploy lock | `~/.local/state/ai-pronunciation-trainer/deploy.lock`: a second `deploy.sh` exits at once while one runs, and after a killed run while a docker command it started is still finishing (`fuser -v` on the file shows which) |
| Before phase 1 | `ai-pronunciation-trainer-legacy`: the single container of earlier versions, kept stopped after the move behind the proxy |

```bash
deploy/deploy.sh --status     # which colour is live, the containers, the last deploys, /version
```

## Deploy

```bash
cd ~/ai-pronunciation-trainer && git fetch origin && git checkout -B main origin/main
nohup deploy/deploy.sh > ~/deploy-$(date +%Y%m%d-%H%M%S).log 2>&1 < /dev/null &   # or: deploy/deploy.sh origin/<branch>
tail -f ~/deploy-*.log
```

`nohup` keeps the deploy running if the SSH session drops; do not pipe the output through `tee` or run it
over `ssh host deploy/deploy.sh` without a terminal. deploy.sh only deploys commits that are on a branch of
origin (CI has checked them), and it never changes the checkout: it builds from `git archive` of the commit.
The script does the following:
1. Builds the image. The build fails if the strict warm-up cannot score a test sentence. A change to the code
   only rebuilds the last layers; a change to `requirements.lock` or `model_pins.py` rebuilds more.
2. Starts the image in the idle colour, waits until it is healthy (every worker has scored its warm-up
   sentence) and runs that commit's `deploy/smoke_test.py` against `127.0.0.1:3001` or `3002`. If anything
   fails, production is not touched and the new image is removed. The idle colour held the release before the
   live one; it is replaced.
3. Points Caddy at the new colour (`caddy reload`: requests already in flight finish on the old colour) and
   runs the smoke test again through port 3000. If that fails, Caddy is pointed back.
4. Records the deploy, waits a few seconds, and stops the old colour, which gunicorn lets finish its requests.
   It stays stopped for `--rollback`. The images of the last 3 deploys are kept; tags that are not in the
   deploy log (for example ones made by hand) are never removed.

No request is dropped: in the test harness, 0 of more than 5,000 requests failed across deploys and rollbacks,
including requests in flight during the switch.

If the deploy is interrupted (Ctrl-C, a dropped session, a closed output pipe), it undoes what it started:
the new colour is removed and, if Caddy had been switched, it is pointed back. The live release keeps
serving throughout.

### The first deploy with this script

A host that still runs the single container `ai-pronunciation-trainer` on port 3000 (every deploy before
phase 1) is moved behind the proxy by the first run:
1. The new release is started as blue and checked while the old container keeps serving.
2. The old container is stopped (gunicorn finishes its requests) and the proxy takes over port 3000. Port 3000
   is unavailable for a few seconds; deploy.sh prints how long. Do it outside school hours.
3. The proxy is smoke-tested. If that fails, or the run is interrupted, the old container is started again.
4. The old container is kept, stopped, as `ai-pronunciation-trainer-legacy`.

If the run is killed in step 2 or 3 (SIGKILL, a reboot), the next run finishes the move if the proxy serves,
or puts the old container back and stops; then deploy again.

## Rollback

To the previous release (the stopped colour), with no downtime:

```bash
deploy/deploy.sh --rollback
```

It starts the stopped colour, waits until it is healthy, smoke-tests it, switches Caddy to it and stops the
other one. Running it again goes back. Right after the move behind the proxy, there is no previous colour
yet: `--rollback` then stops the proxy and starts `ai-pronunciation-trainer-legacy` again on port 3000
(a few seconds of downtime); the next deploy moves it behind the proxy again.

To an older release, deploy its commit again. Its image is reused from the build cache when it is still on
the host (`docker images ai-pronunciation-trainer`):

```bash
deploy/deploy.sh <sha>
```

`deploy.sh` refuses commits from before it existed: they have no `deploy/smoke_test.py` (and their image no
`HEALTHCHECK`). The last of them is `51c9af9`, the English UI before phase 0, kept as
`ai-pronunciation-trainer:english-ui`. To run it, start it as the idle colour by hand and switch Caddy to it:

```bash
docker rm -f ai-pronunciation-trainer-green   # if green is the idle colour (see --status)
docker run -d --name ai-pronunciation-trainer-green --network ai-pronunciation-trainer-net --restart unless-stopped \
  -p 127.0.0.1:3002:3000 --memory 9g --memory-swap 9g --pids-limit 512 --log-opt max-size=10m --log-opt max-file=3 \
  --tmpfs /tmp:rw,nosuid,size=256m ai-pronunciation-trainer:english-ui
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:3002/   # 200 once both workers have warmed up
echo 'to ai-pronunciation-trainer-green:3000' > ~/.local/state/ai-pronunciation-trainer/proxy/upstream.caddy.new
mv ~/.local/state/ai-pronunciation-trainer/proxy/upstream.caddy.new ~/.local/state/ai-pronunciation-trainer/proxy/upstream.caddy
docker exec ai-pronunciation-trainer-proxy caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile
```

Images without a `HEALTHCHECK` (such as `:english-ui`) never show `(healthy)` in `docker ps`; wait for the
`curl` above to print 200 and `docker logs` to show `Warm-up done` for both workers. Replace
`upstream.caddy` with `mv`, as above, rather than editing it in place: the proxy sees the directory through a
bind mount.

## When something is down

`Production is DOWN` from deploy.sh, or the site does not answer:

```bash
deploy/deploy.sh --status
docker logs --tail 50 ai-pronunciation-trainer-proxy
```

* The proxy is stopped: `docker start ai-pronunciation-trainer-proxy` (deploy.sh also does this).
* The live colour is stopped or unhealthy: `docker start ai-pronunciation-trainer-<colour>`, or make the other
  colour live with `deploy/deploy.sh --rollback`.
* A run of the single-container deploy.sh from before phase 1 was interrupted and left
  `ai-pronunciation-trainer-previous` or `-staging`, or `swap-in-progress` in the state directory: deploy.sh
  refuses to run. Remove the leftover after checking it is not serving (`docker ps -a`), then deploy again.

The proxy image is pinned in deploy.sh (`CADDY_IMAGE`). deploy.sh rewrites the proxy configuration on every
run and reloads Caddy when it changed, but does not replace a running proxy; `--status` says when the proxy runs
another image than the pin. After a pull that changed the pin, recreate the proxy (port 3000 is unavailable for
about a second):

```bash
deploy/deploy.sh --replace-proxy
```

## Check health and logs

```bash
deploy/deploy.sh --status
docker logs -f --tail 100 ai-pronunciation-trainer-blue   # or -green: one JSON object per line
python3 deploy/smoke_test.py http://127.0.0.1:3000         # through the proxy; :3001 / :3002 for one colour
curl -s http://127.0.0.1:3000/readyz                       # 200 once every worker has warmed up
```

Every line of the app's log is a JSON object (`docker logs ai-pronunciation-trainer-blue 2>&1 | jq .`):
* gunicorn's access log: `rid`, `m`, `path`, `status`, `bytes`, `ms`, `pid`; no client IP, query string or body;
* one `scored` line per recording, with `decode_ms`, `lock_wait_ms`, `asr_ms`, `match_ms`, `total_ms`,
  `audio_s`, `words`, `accuracy` and `outcome` (`ok`, `no_speech`, `too_long`, `bad_audio`, `error`), but never
  the text or the audio;
* app warnings and errors with the request id (`rid`), and tracebacks in `exc`;
* gunicorn's own messages (worker start and exit).

Libraries that log through Python's root logger, and transformers, log errors only. The proxy keeps no access
log; it logs its own warnings and errors.

The container is healthy once every gunicorn worker has scored its warm-up sentence. Each worker writes a
marker file under `/tmp/aipt-ready`, and both `healthcheck.py` and `/readyz` count the markers of live workers.
The health check does not probe over HTTP, so a busy worker does not make it time out. `/healthz` only says that
a worker answers HTTP.

`rid` is Cloudflare's Ray ID (header `CF-Ray`, for example `8f3b2a1c9d4e5f60-SIN`). It is also returned to the
browser as `X-Request-ID`. A request whose `CF-Ray` header is missing or does not have that shape gets a random
16-hex-digit id instead. Port 3000 is reachable from the LAN, so a client there can still send a Ray-ID-shaped
header of its own.

## Canary

`.github/workflows/canary.yml` runs `deploy/smoke_test.py` against the public site every 15 minutes from
GitHub Actions and retries once after a minute. A failed run sends GitHub's failure e-mail to the account that
last changed the workflow's schedule. GitHub delays scheduled runs at busy times, and disables the schedule
after 60 days without activity in the repository (re-enable it in the Actions tab).

## Testing the public site

Cloudflare blocks the default Python `urllib` user agent with a 403 error (error 1010). Test
https://aitrainer.ism.io.vn/ with a browser, with curl using a browser user agent, or with
`python3 deploy/smoke_test.py https://aitrainer.ism.io.vn --user-agent 'aitrainer-canary/1.0'`.
