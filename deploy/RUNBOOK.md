# Runbook: aitrainer.ism.io.vn

Production runs on the VM `172.16.17.40` as a Caddy proxy in front of two app containers, blue and green.
Cloudflare sits in front. The Cloudflare Tunnel connector runs on VM 202 (`172.16.10.20`, which also runs
Nginx Proxy Manager) and forwards to `172.16.17.40:3000`, so Cloudflare's traffic arrives from that address.
Port 3000 is open to the whole LAN, though: nothing proves that a request came through Cloudflare.

| Item | Value |
|---|---|
| SSH | `ssh -i ~/.ssh/id_ed25519 itadmin@172.16.17.40` (docker access, no sudo); off the LAN, Tailscale `100.121.247.67` |
| Code | `~/ai-pronunciation-trainer` (git, origin = github.com/likemoue/ai-pronunciation-trainer) |
| Proxy | `ai-pronunciation-trainer-proxy`: Caddy, the only container on port 3000 (`0.0.0.0:3000`). It holds each request body until the whole body has arrived, in up to 1 GB of memory |
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
nohup deploy/deploy.sh > ~/deploy-$(date +%Y%m%d-%H%M%S).log 2>&1 < /dev/null &
tail -f ~/deploy-*.log
```

`nohup` keeps the deploy running if the SSH session drops; do not pipe the output through `tee` or run it
over `ssh host deploy/deploy.sh` without a terminal.

deploy.sh deploys commits of `main` that contain `4290c3e` (see Rollback), once their run of CI
(`.github/workflows/ci.yml`) has passed. It asks the GitHub API and refuses a commit whose run failed, was
cancelled or is still going. When it cannot tell, it only warns and deploys: GitHub cannot be reached or answers
with an error (for example its limit of 60 questions an hour from one address), `origin` is not a GitHub URL, or
the commit has no CI run (a commit from before CI, or one inside a merged pull request). So read the first lines
of its output, or look at CI in the browser before you start. Right after a merge, wait for CI on `main` (about
15 minutes). `SKIP_CI_CHECK=1` skips the question. If `git fetch` fails, deploy.sh warns and uses the commits it
fetched before. A commit that is only on another branch is refused (for a test,
`DEPLOY_ANY_BRANCH=1 deploy/deploy.sh origin/<branch>` allows any pushed branch). deploy.sh never changes the
checkout: it builds from `git archive` of the commit. The script does the following:
1. Builds the image. The build fails if the strict warm-up cannot score a test sentence. It first asks Debian's
   archive for the state of its package indexes (`scripts/system_refresh.sh`; it prints `SYSTEM_REFRESH=...`).
   When Debian has published an update since the last build, the system packages are upgraded again, which
   adds a minute or two and about 460 MB. Otherwise a change to the code only rebuilds the last layers (about
   35 s); a change to `requirements.lock` or `model_pins.py` rebuilds more. The first build on a host takes about
   6-8 minutes. `SYSTEM_REFRESH=<a new value> deploy/deploy.sh` forces the system packages to be upgraded.
2. Starts the image in the idle colour, which held the previous release, waits until it is healthy (every
   worker has scored its warm-up sentence) and runs that commit's `deploy/smoke_test.py` against
   `127.0.0.1:3001` or `3002`. If anything fails, production is not touched, the new image is removed and the
   previous release goes back into the idle colour, stopped, so `--rollback` still finds it.
3. Points Caddy at the new colour and runs the smoke test again through port 3000. Each check gets up to 60 s
   there, since the new colour may already be busy with recordings; a refused connection or a 502 fails at
   once. If the test fails, Caddy is pointed back. Caddy checks every new configuration before deploy.sh puts
   it in place: the pinned image (`CADDY_IMAGE`) checks it, and so does the running proxy's image when that is
   another one.
4. Records the deploy and keeps the old colour running for 65 s after the switch. Caddy sends a request to the
   colour that was live when the request arrived, once its whole body is in, and gives a client up to 60 s to
   send the body (`read_body`); the extra 5 s are a margin. Then it stops the old colour, which first finishes
   the requests it has, for up to 120 s (Cloudflare gives up on a request after 125 s anyway). It stays stopped
   for `--rollback`. The images of the last 3 deploys are kept, and images that lost their tag to a rebuild of
   the same commit are removed. Tags that are not in the deploy log, or that do not name a commit (for example
   ones made by hand), are never removed.

The switch is one graceful `caddy reload`. Requests that arrived before it finish on the old colour, uploads still
arriving included; new ones go to the new colour. Caddy closes its idle keep-alive connections when it reloads, so
a request that a client sends on one of them at that very moment can fail. In a controlled test over 60 reloads,
21 of 6,235 requests failed from a client that kept idle connections open and did not notice them closing, and
none of 6,206 sent on new connections. How often Cloudflare's connector meets this was not measured. The test
harness (deploy/test/) opens a new connection for every request, so it does not exercise this case; in its last
full run, none of its 107,249 requests failed over 47 deploys, rollbacks and interrupted runs. With the real app,
no request failed during a deploy and a rollback.

If the deploy is interrupted (Ctrl-C, a dropped session, a closed output pipe), it undoes what it started:
Caddy is pointed back if it had been switched (the new colour then gets the same 65 s for the requests it took,
finishes them and is removed), and the previous release goes back into its slot. The live release keeps serving
throughout. If a run is killed (SIGKILL, a reboot), the next run takes what Caddy actually serves as live (from
Caddy's admin API, not from `upstream.caddy`), records it if it was not recorded, and goes on. A run killed while
it was starting the new release leaves that release in the idle colour, and the previous release is gone:
`--rollback` then refuses, since that release is not in the deploy log. Deploy the previous commit by its sha
instead (`--status` lists the last deploys).

When CI fails at Trivy on a Debian package that has a fix, nothing in the repository needs to change: the system
packages are keyed on Debian's package indexes, so the next build upgrades them once Debian has published the fix
(run CI again). A run of CI started by hand with the input `system_refresh` set to a new value forces the
upgrade; on the VM, `SYSTEM_REFRESH=<a new value> deploy/deploy.sh` does the same. Trivy ignores vulnerabilities
that have no fix yet.

### The first deploy with this script

A host that still runs the single container `ai-pronunciation-trainer` on port 3000 (every deploy before
phase 1) is moved behind the proxy by the first run:
1. The new release is started as blue and checked while the old container keeps serving.
2. The old container is stopped and the proxy takes over port 3000. gunicorn refuses new connections from the
   moment it is told to stop and finishes the requests it has, so port 3000 is unavailable for a few seconds
   (about 4 s in the test with the real app, which first finishes the recordings it is scoring); deploy.sh prints
   how long. Do it outside school hours.
3. The proxy is smoke-tested. If that fails, or the run is interrupted, the old container is started again. If the
   old container cannot be started, the proxy serves the new release instead (it passed its own checks).
4. The old container is kept, stopped, as `ai-pronunciation-trainer-legacy`.

If the run is killed in step 2 or 3 (SIGKILL, a reboot), the next run finishes the move if the proxy serves,
or puts the old container back and stops; then deploy again.

## Rollback

To the previous release (the stopped colour), with no downtime:

```bash
deploy/deploy.sh --rollback
```

It starts the stopped colour, waits until it is healthy, smoke-tests it, switches Caddy to it and, 65 s later,
stops the other one. Running it again goes back. It refuses a colour whose release is not in the deploy log
(left there by a deploy that was killed) or does not contain `4290c3e`. Right after the move behind the proxy there is no previous colour yet;
`--rollback` then says so and changes nothing. To bring back the single container from before the proxy, which
costs downtime: port 3000 refuses new connections from the moment the proxy is told to stop (it first finishes
the requests it has, for up to about 2 minutes) until the old container has started, and the first requests are
slow while it warms up (about a minute):

```bash
deploy/deploy.sh --rollback-legacy   # the next deploy moves it behind the proxy again
```

To an older release, deploy its commit again. Its image is rebuilt from the build cache: about 35 s while
Debian has published nothing new since that release was built, otherwise a minute or two more, with the
system packages upgraded (this needs the network to Debian):

```bash
deploy/deploy.sh <sha>
```

The oldest release that is safe to roll back to is `4290c3e` (phase 0b, the first release deployed with
`deploy.sh`). deploy.sh refuses every commit that does not contain it (`OLDEST_RELEASE`), in a deploy and in
`--rollback`. The phase 0a commits (`d38ecae` to `71218bf`, and `f6f247a`) still have the sentences that were
removed as unsuitable for children, or the voice licensed for research only. Commits from before deploy.sh also
have no `deploy/smoke_test.py` (and their image no `HEALTHCHECK`); the last of them is `51c9af9`, the English UI
before phase 0, kept as `ai-pronunciation-trainer:english-ui`.

> **Warning.** `:english-ui` predates every phase 0 fix: it has the sentences that were removed as unsuitable for
> children, the voice whose training data is licensed for research only, no Tatoeba credit, and none of the API
> hardening (anyone can take the site down with a crafted request). Run it only if every later release is broken.

To run it anyway, start it as the idle colour by hand and switch Caddy to it:

```bash
docker rm -f ai-pronunciation-trainer-green   # if green is the idle colour (see --status)
docker run -d --name ai-pronunciation-trainer-green --network ai-pronunciation-trainer-net --restart unless-stopped \
  -p 127.0.0.1:3002:3000 --memory 9g --memory-swap 9g --pids-limit 512 --log-opt max-size=10m --log-opt max-file=3 \
  --tmpfs /tmp:rw,nosuid,size=256m ai-pronunciation-trainer:english-ui
docker logs -f ai-pronunciation-trainer-green   # wait for "Warm-up done" from both workers
echo 'to ai-pronunciation-trainer-green:3000' > ~/.local/state/ai-pronunciation-trainer/proxy/upstream.caddy.new
mv ~/.local/state/ai-pronunciation-trainer/proxy/upstream.caddy.new ~/.local/state/ai-pronunciation-trainer/proxy/upstream.caddy
docker exec ai-pronunciation-trainer-proxy caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile
```

Images without a `HEALTHCHECK` (such as `:english-ui`) never show `(healthy)` in `docker ps`, and the page
answers 200 before the models are loaded: wait for the two `Warm-up done` lines. Replace `upstream.caddy`
with `mv`, as above, rather than editing it in place: the proxy sees the directory through a bind mount.

## When something is down

Start with:

```bash
deploy/deploy.sh --status
docker logs --tail 50 ai-pronunciation-trainer-proxy
```

What deploy.sh prints, and what to do:

* **`Could not start ai-pronunciation-trainer. Production is DOWN`** during the move behind the proxy: the old
  container could not be started again. deploy.sh then tries to serve the new release through the proxy and says
  whether that worked. If it did not either, free port 3000 (`docker ps --filter publish=3000` shows what holds it)
  and run `deploy/deploy.sh --replace-proxy`, which starts a proxy in front of the colour that runs. The next
  deploy.sh run finishes the move. The same message from the run after a move that was killed means that run only
  tried the old container: free port 3000 and run `--replace-proxy` the same way.
* **`The proxy still sends traffic to <colour>, so it is left running`**: a deploy failed after the switch, and
  Caddy did not take the switch back. That colour passed its own checks and serves. `deploy/deploy.sh --rollback`
  goes back to the other colour, or deploy again.
* **`Could not start ai-pronunciation-trainer-proxy`** (with Production is DOWN) or **`The new proxy does not
  serve`**: deploy.sh prints the last `docker start` error. If port 3000 is taken, `docker ps --filter publish=3000`
  shows by what (for example `ai-pronunciation-trainer-legacy`, if it was started by hand): stop it, then run
  `deploy/deploy.sh --replace-proxy`. If the new Caddy image is the problem, go back to the previous pin:
  `CADDY_IMAGE=<previous image@digest> deploy/deploy.sh --replace-proxy`. `--replace-proxy` has that image check the
  configuration first, and leaves the running proxy alone if it refuses it.
* **`Caddy refuses the new configuration`**: nothing was changed. The configuration that was refused is in
  `~/.local/state/ai-pronunciation-trainer/proxy/next/` with Caddy's message in `validate.log`. If deploy.sh adds
  that the running proxy's image refuses it, the proxy runs an older image than the pin: recreate it with
  `deploy/deploy.sh --replace-proxy` (outside school hours), then deploy again. Otherwise it is a bug in
  deploy.sh's Caddyfile.
* **`ai-pronunciation-trainer serves port 3000 but failed its checks`** after `--rollback-legacy`: the single
  container serves, and the colours are still there. Check the site, then deploy again, which moves the single
  container behind the proxy as on the first deploy. `--replace-proxy` does not help here: the single container
  holds port 3000.
* The live colour is stopped: `docker start ai-pronunciation-trainer-<colour>`. Running but unhealthy:
  `docker restart ai-pronunciation-trainer-<colour>`. Or make the other colour live with `deploy/deploy.sh --rollback`.
* A run of the single-container deploy.sh from before phase 1 was interrupted and left
  `ai-pronunciation-trainer-previous` or `-staging`, or `swap-in-progress` in the state directory: deploy.sh
  refuses to run. Do not remove anything before production serves again: `-previous` may be the only copy of the
  release that was live. Check with `curl -s http://127.0.0.1:3000/healthz` and `docker ps -a`. If nothing answers,
  start `ai-pronunciation-trainer` if it exists (`docker start ai-pronunciation-trainer`); if it does not, put the
  old release back with `docker rename ai-pronunciation-trainer-previous ai-pronunciation-trainer` and
  `docker start ai-pronunciation-trainer`. Once it is healthy, remove the leftovers
  (`docker rm -f ai-pronunciation-trainer-staging ai-pronunciation-trainer-previous`,
  `rm -f ~/.local/state/ai-pronunciation-trainer/swap-in-progress`) and deploy again.

The proxy image is pinned in deploy.sh (`CADDY_IMAGE`). deploy.sh rewrites the proxy configuration on every
run and reloads Caddy when it changed, but does not replace a running proxy; `--status` says when the proxy runs
another image than the pin. After a pull that changed the pin, recreate the proxy outside school hours. Port 3000
refuses new connections from the moment the old proxy is told to stop: it first finishes the requests it has, for
up to about 2 minutes, and the new proxy answers a few seconds after that.

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

Every line of the app's log is a JSON object (`docker logs ai-pronunciation-trainer-blue 2>&1 | jq -R 'fromjson? // .'`
also shows any line that is not):
* gunicorn's access log: `rid`, `m`, `path`, `status`, `bytes`, `ms`, `pid`; no client IP, query string or body;
* one `scored` line per recording, with `decode_ms`, `lock_wait_ms`, `asr_ms`, `match_ms`, `total_ms`,
  `audio_s`, `words`, `accuracy` and `outcome` (`ok`, `no_speech`, `too_long`, `bad_audio`, `error`), but never
  the text or the audio;
* app warnings and errors with the request id (`rid`), and tracebacks in `exc`;
* gunicorn's own messages (worker start and exit).

Libraries that log through Python's root logger, and transformers, log errors only, and transformers shows no
progress bars. The proxy keeps no access log; it logs its own warnings and errors. Errors that the proxy answers
itself (a body over 5 MB, a colour that does not answer) are JSON like the app's (`request_entity_too_large`,
`server_unavailable`).

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

## Testing deploy.sh

`deploy/test/` holds a fault-injection harness: a 60-line stand-in for the app, a `docker` wrapper that injects
failures and signals at every step, and scenarios for fresh hosts, the move behind the proxy, failed releases,
signals and SIGKILL at each step, concurrent runs and rollbacks, with traffic running. See `deploy/test/README.md`.
