# Runbook: aitrainer.ism.io.vn

Production runs as one Docker container on the VM `172.16.17.40`. Cloudflare sits in front, and the
Cloudflare Tunnel connector runs on another machine in the LAN that forwards to `172.16.17.40:3000`.

| Item | Value |
|---|---|
| SSH | `ssh -i ~/.ssh/id_ed25519 itadmin@172.16.17.40` (docker access, no sudo) |
| Code | `~/ai-pronunciation-trainer` (git, origin = github.com/likemoue/ai-pronunciation-trainer) |
| Container | `ai-pronunciation-trainer`, port 3000, `--restart unless-stopped` |
| Images | `ai-pronunciation-trainer:<short git sha>`; `:latest` = what is running |
| Deploy log | `~/.local/state/ai-pronunciation-trainer/deploys.log`: one line per successful deploy (`<UTC time> <sha> <container id>`) |
| Deploy lock | `~/.local/state/ai-pronunciation-trainer/deploy.lock`: a second `deploy.sh` exits at once while one runs, and after a killed run while a docker command it started is still finishing (`fuser -v` on the file shows which) |
| Tunnel host | *TODO: record which LAN machine runs cloudflared* |

## Deploy

```bash
cd ~/ai-pronunciation-trainer && git fetch origin && git checkout -B main origin/main
nohup deploy/deploy.sh > ~/deploy-$(date +%Y%m%d-%H%M%S).log 2>&1 &   # or: deploy/deploy.sh origin/<branch>
tail -f ~/deploy-*.log
```

`nohup` keeps the deploy running if the SSH session drops; do not pipe the output through `tee` or run it
over `ssh host deploy/deploy.sh` without a terminal. The script does the following:
1. If an earlier deploy was killed half-way (SIGKILL, a reboot) and left the old container stopped or renamed
   to `ai-pronunciation-trainer-previous`, it starts that container again and stops. Check it, then deploy again.
   If you already started the old container by hand, it is left running and the deploy goes on.
2. Builds the image. The build fails if the strict warm-up cannot score a test sentence.
3. Starts a staging container on `127.0.0.1:3001`, waits until it is healthy, and runs `deploy/smoke_test.py`.
   If that fails, production is not touched and the new image is removed.
4. Replaces production. Production is unavailable for about 30–60 s while the new container warms up.
   If the new container fails its health check or smoke test, or the script is interrupted (Ctrl-C, a dropped
   session, a closed output pipe), the previous container is started again and the new image is removed.
5. Adds the deploy to the deploy log and keeps the images of the last 3 deploys. Tags that are not in the
   deploy log (for example ones made by hand) are never removed.

If the script prints `Production is DOWN`, start the previous version by recreating its container (a plain
`docker start` may come up without its port published once a start has failed):

```bash
docker images ai-pronunciation-trainer          # pick the tag that was running
docker rm -f ai-pronunciation-trainer ai-pronunciation-trainer-previous
docker run -d --name ai-pronunciation-trainer --restart unless-stopped -p 3000:3000 \
  --memory 9g --memory-swap 9g --pids-limit 512 --log-opt max-size=10m --log-opt max-file=3 \
  --tmpfs /tmp:rw,nosuid,size=256m ai-pronunciation-trainer:<tag>
```

## Rollback

To a version deployed with `deploy.sh` (phase 0a or later) whose image is still on the host
(`docker images ai-pronunciation-trainer`), deploy its commit again. The build comes from the cache, so it
only takes the staging and swap time:

```bash
deploy/deploy.sh <sha>
```

`deploy.sh` refuses commits from before it existed: they have no `deploy/smoke_test.py`, and their image has no
`HEALTHCHECK`. The last of them is `51c9af9`, the English UI before phase 0, kept as
`ai-pronunciation-trainer:english-ui` (a rebuild never moves that tag). To go back to it, or if the script
itself cannot run, swap by hand:

```bash
docker stop -t 40 ai-pronunciation-trainer && docker rename ai-pronunciation-trainer ai-pronunciation-trainer-broken
docker run -d --name ai-pronunciation-trainer --restart unless-stopped -p 3000:3000 \
  --memory 9g --memory-swap 9g --pids-limit 512 --log-opt max-size=10m --log-opt max-file=3 \
  --tmpfs /tmp:rw,nosuid,size=256m ai-pronunciation-trainer:<tag>
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:3000/   # 200 once it has started
docker rm ai-pronunciation-trainer-broken
```

Images without a `HEALTHCHECK` (such as `:english-ui`) never show `(healthy)` in `docker ps`. Wait until the
`curl` above prints 200 and `docker logs` shows `Warm-up done` for both workers.

## Check health and logs

```bash
docker ps --filter name=ai-pronunciation-trainer       # STATUS shows (healthy) once both workers warmed up
docker logs -f --tail 100 ai-pronunciation-trainer     # one JSON access-log line per request, plus app warnings
python3 deploy/smoke_test.py http://127.0.0.1:3000
```

The container is healthy once every gunicorn worker has scored its warm-up sentence. Each worker writes
a marker file under `/tmp/aipt-ready`, and `healthcheck.py` checks for them. It does not probe over
HTTP, so a busy worker does not make the check time out.

The `rid` field in the access log is Cloudflare's Ray ID (header `CF-Ray`, for example
`8f3b2a1c9d4e5f60-SIN`). It is also returned to the browser as `X-Request-ID`. A request whose `CF-Ray`
header is missing or does not have that shape gets a random 16-hex-digit id instead. Port 3000 is reachable
from the LAN, so a client there can still send a Ray-ID-shaped header of its own. Each access-log line is
valid JSON (`docker logs ai-pronunciation-trainer 2>&1 | grep '^{' | jq .`).

App warnings and errors are logged with a timestamp. Libraries that log through Python's root logger only log
errors; transformers keeps its own handler and prints a few lines when a worker starts.

## Testing the public site

Cloudflare blocks the default Python `urllib` user agent with a 403 error. Test
https://aitrainer.ism.io.vn/ with a browser, or with curl using a browser user agent.
