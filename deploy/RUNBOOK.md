# Runbook: aitrainer.ism.io.vn

Production runs as one Docker container on the VM `172.16.17.40`. Cloudflare sits in front, and the
Cloudflare Tunnel connector runs on another machine in the LAN that forwards to `172.16.17.40:3000`.

| Item | Value |
|---|---|
| SSH | `ssh -i ~/.ssh/id_ed25519 itadmin@172.16.17.40` (docker access, no sudo) |
| Code | `~/ai-pronunciation-trainer` (git, origin = github.com/likemoue/ai-pronunciation-trainer) |
| Container | `ai-pronunciation-trainer`, port 3000, `--restart unless-stopped` |
| Images | `ai-pronunciation-trainer:<short git sha>`; `:latest` = what is running |
| Deploy log | `~/.local/state/ai-pronunciation-trainer/deploys.log`: one line per successful deploy (`<UTC time> <sha>`) |
| Tunnel host | *TODO: record which LAN machine runs cloudflared* |

## Deploy

```bash
cd ~/ai-pronunciation-trainer && git fetch origin && git checkout -B main origin/main
nohup deploy/deploy.sh > ~/deploy-$(date +%Y%m%d-%H%M).log 2>&1 &   # or: deploy/deploy.sh origin/<branch>
tail -f ~/deploy-*.log
```

`nohup` keeps the deploy running if the SSH session drops. The script does the following:
1. If an earlier deploy was killed half-way (the old container is still there as
   `ai-pronunciation-trainer-previous`), it puts that container back and stops. Check it, then deploy again.
2. Builds the image. The build fails if the strict warm-up cannot score a test sentence.
3. Starts a staging container on `127.0.0.1:3001`, waits until it is healthy, and runs `deploy/smoke_test.py`.
   If that fails, production is not touched and the new image is removed.
4. Replaces production. Production is unavailable for about 30–60 s while the new container warms up.
   If the new container fails its health check or smoke test, or the script is interrupted, the previous
   container is started again.
5. Adds the deploy to the deploy log and keeps the images of the last 3 deploys. Tags that are not in the
   deploy log (for example ones made by hand) are never removed.

## Rollback

To an image that is still on the host (`docker images ai-pronunciation-trainer`), deploy its commit again;
the build comes from the cache, so it only takes the staging and swap time:

```bash
deploy/deploy.sh <sha>
```

If the script itself cannot run, swap by hand:

```bash
docker stop -t 40 ai-pronunciation-trainer && docker rename ai-pronunciation-trainer ai-pronunciation-trainer-broken
docker run -d --name ai-pronunciation-trainer --restart unless-stopped -p 3000:3000 \
  --memory 9g --memory-swap 9g --pids-limit 512 --log-opt max-size=10m --log-opt max-file=3 \
  --tmpfs /tmp:rw,nosuid,size=256m ai-pronunciation-trainer:<tag>
docker rm ai-pronunciation-trainer-broken      # once the restored container is healthy
```

## Check health and logs

```bash
docker ps --filter name=ai-pronunciation-trainer       # STATUS shows (healthy) once both workers warmed up
docker logs -f --tail 100 ai-pronunciation-trainer     # one JSON access-log line per request, plus app warnings
python3 deploy/smoke_test.py http://127.0.0.1:3000
```

The container is healthy once every gunicorn worker has scored its warm-up sentence. Each worker writes
a marker file under `/tmp/aipt-ready`, and `healthcheck.py` checks for them. It does not probe over
HTTP, so a busy worker does not make the check time out.

The `rid` field in the access log is Cloudflare's Ray ID (header `CF-Ray`). It is also returned to the
browser as `X-Request-ID`. A request that did not come through Cloudflare, or whose `CF-Ray` header does
not look like a Ray ID, gets a random id instead. Each access-log line is valid JSON
(`docker logs ai-pronunciation-trainer 2>&1 | grep '^{' | jq .`).

## Testing the public site

Cloudflare blocks the default Python `urllib` user agent with a 403 error. Test
https://aitrainer.ism.io.vn/ with a browser, or with curl using a browser user agent.
