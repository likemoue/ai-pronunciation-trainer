# Runbook: aitrainer.ism.io.vn

Production runs as one Docker container on the VM `172.16.17.40`. Cloudflare sits in front, and the
Cloudflare Tunnel connector runs on another machine in the LAN that forwards to `172.16.17.40:3000`.

| Item | Value |
|---|---|
| SSH | `ssh -i ~/.ssh/id_ed25519 itadmin@172.16.17.40` (docker access, no sudo) |
| Code | `~/ai-pronunciation-trainer` (git, origin = github.com/likemoue/ai-pronunciation-trainer) |
| Container | `ai-pronunciation-trainer`, port 3000, `--restart unless-stopped` |
| Images | `ai-pronunciation-trainer:<short git sha>`; `:latest` = what is running |
| Tunnel host | *TODO: record which LAN machine runs cloudflared* |

## Deploy

```bash
cd ~/ai-pronunciation-trainer && git fetch origin && git checkout -B main origin/main
deploy/deploy.sh                 # or: deploy/deploy.sh origin/<branch> to try a branch
```

The script does the following:
1. Builds the image. The build fails if the strict warm-up cannot score a test sentence.
2. Starts a staging container on `127.0.0.1:3001`, waits until it is healthy, and runs `deploy/smoke_test.py`.
3. Replaces production. Production is unavailable for about 30–60 s while the new container warms up.
4. If the new container fails its health check or smoke test, the script restarts the previous one.

It keeps the newest 3 sha-tagged images.

## Rollback

```bash
docker images ai-pronunciation-trainer          # pick a previous tag
docker stop -t 40 ai-pronunciation-trainer && docker rm ai-pronunciation-trainer
docker run -d --name ai-pronunciation-trainer --restart unless-stopped -p 3000:3000 \
  --memory 9g --memory-swap 9g --pids-limit 512 --log-opt max-size=10m --log-opt max-file=3 \
  --tmpfs /tmp:rw,nosuid,size=256m ai-pronunciation-trainer:<tag>
```

## Check health and logs

```bash
docker ps --filter name=ai-pronunciation-trainer       # STATUS shows (healthy) once both workers warmed up
docker logs -f --tail 100 ai-pronunciation-trainer     # one JSON access-log line per request
python3 deploy/smoke_test.py http://127.0.0.1:3000
```

The container is healthy once every gunicorn worker has scored its warm-up sentence. Each worker writes
a marker file under `/tmp/aipt-ready`, and `healthcheck.py` checks for them. It does not probe over
HTTP, so a busy worker does not make the check time out.

The `rid` field in the access log is Cloudflare's Ray ID (header `CF-Ray`). It is also returned to the
browser as `X-Request-ID`.

## Testing the public site

Cloudflare blocks the default Python `urllib` user agent with a 403 error. Test
https://aitrainer.ism.io.vn/ with a browser, or with curl using a browser user agent.
