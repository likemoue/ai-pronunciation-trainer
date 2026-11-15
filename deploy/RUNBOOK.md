# Runbook: aitrainer.ism.io.vn

Production runs on the VM `172.16.17.40` as a Caddy proxy in front of two app containers, blue and green.
Cloudflare sits in front. The Cloudflare Tunnel connector runs on VM 202 (`172.16.10.20`, which also runs
Nginx Proxy Manager) and forwards to `172.16.17.40:3000`, so Cloudflare's traffic arrives from that address.
Port 3000 is open to the whole LAN, though: nothing proves that a request came through Cloudflare.

| Item | Value |
|---|---|
| SSH | `ssh -i ~/.ssh/id_ed25519 itadmin@172.16.17.40` (docker access, no sudo); off the LAN, Tailscale `100.121.247.67` |
| VM | Proxmox VM 209 on node `pve` (`172.16.9.20`): 10 vCPU with `cpu: host` (Xeon E5-2670 v2: AVX, no AVX2), 12 GB. A new CPU type takes effect only after `qm shutdown 209 && qm start 209` on `pve` (about 2 minutes without service); a reboot from inside the VM keeps the old one |
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
15 minutes, an estimate: CI has not been timed on GitHub yet). `SKIP_CI_CHECK=1` skips the question. If
`git fetch` fails, deploy.sh warns and uses the commits it fetched before. A commit that is only on another branch
is refused (for a test, `DEPLOY_ANY_BRANCH=1 deploy/deploy.sh origin/<branch>` allows any pushed branch).
deploy.sh never changes the checkout: it builds from `git archive` of the commit. The script does the following:
1. Builds the image. The build fails if the strict warm-up cannot score a test sentence. It first asks Debian's
   archive for the state of its package indexes (`scripts/system_refresh.sh`; it prints `SYSTEM_REFRESH=...`).
   If Debian cannot be reached within about a minute, it uses the ISO week instead (`week-2026-W46`).
   When Debian has published an update since the last build, the system packages are upgraded again, which
   adds a minute or two and about 460 MB. Otherwise a change to the code only rebuilds the last layers (about
   35 s); a change to `requirements.lock` or `model_pins.py` rebuilds more. The first build on a host takes about
   6-8 minutes. `SYSTEM_REFRESH=<a new value> deploy/deploy.sh` forces the system packages to be upgraded.
2. Starts the image in the idle colour, which held the previous release, waits until it is healthy (every
   worker has scored its warm-up sentence) and runs that commit's `deploy/smoke_test.py` against
   `127.0.0.1:3001` or `3002`. If anything fails, production is not touched, the new image is removed and the
   previous release goes back into the idle colour, stopped, so `--rollback` still finds it.
3. Points Caddy at the new colour and runs the smoke test again through port 3000. Since the new colour may
   already be busy with recordings there, the quick checks (health, readiness and the two rejections) get up to
   60 s each (`PROD_SMOKE_TIMEOUT`), and the page, sample, speech and scoring checks up to 120 s each. The test
   stops at the first check that gets no answer in that time, or a 502 or 504 (Caddy answers 502 once the colour
   has refused connections for 10 s), so a colour that hangs keeps the traffic for up to about 2 minutes. If the
   test fails, Caddy is pointed back. Caddy checks every new configuration before deploy.sh puts it in place:
   the pinned image (`CADDY_IMAGE`) checks it, and so does the running proxy's image when that is another one.
4. Records the deploy and keeps the old colour running for 65 s after the switch. Caddy sends a request to the
   colour that was live when the request arrived, once its whole body is in, and gives a client up to 60 s to
   send the body (`read_body`); the extra 5 s are a margin. Then it stops the old colour, which first finishes
   the requests it has, for up to 120 s (Cloudflare gives up on a request after 125 s anyway). It stays stopped
   for `--rollback`. The images of the last 3 deploys are kept, and images that lost their tag to a rebuild of
   the same commit are removed. Tags that are not in the deploy log, or that do not name a commit (for example
   ones made by hand), are never removed.

The switch is one graceful `caddy reload`. Requests that arrived before it finish on the old colour, uploads still
arriving included; new ones go to the new colour. A request can still fail at the very moment of a reload. Caddy
closes its idle keep-alive connections when it reloads, so a request that a client sends on one of them at that
moment can fail: in a controlled test over 60 reloads, 21 of 6,235 requests failed from a client that kept idle
connections open and did not notice them closing. More rarely, Caddy resets a new connection that arrives during
the reload, or closes it without an answer: 2 to 7 times per 100 reloads in tests of Caddy alone (none of the
6,206 requests on new connections in the test above), and 3 of about 70,000 requests in one run of the test
harness (deploy/test/), which opens a new connection for every request. How often Cloudflare's connector
meets either was not measured. In the harness's last full run (148 runs of deploy.sh: deploys, rollbacks, and
failed, interrupted and killed runs), none of 111,882 requests failed apart from the planned outage of the move
behind the proxy. With the real app, no request failed during a deploy and a rollback.

If the deploy is interrupted (Ctrl-C, a dropped session, a closed output pipe), it undoes what it started:
Caddy is pointed back if it had been switched (the new colour then gets the same 65 s for the requests it took,
finishes them and is removed), and the previous release goes back into its slot. The live release keeps serving
throughout. The docker commands that start or remove a colour run out of reach of the terminal's signals, so an
interruption during one of them takes effect once it has returned, and the previous release still goes back. If
a run is killed (SIGKILL, a reboot), the next run takes what Caddy actually serves as live (from Caddy's admin
API, not from `upstream.caddy`), records it if it was not recorded, and goes on. A run killed while it was
starting the new release leaves that release in the idle colour, and the previous release is gone: `--rollback`
then refuses, since that release is not in the deploy log. Deploy the previous commit by its sha instead
(`--status` lists the last deploys). A run killed during staging or during the 65 s drain also leaves the other
colour running: once `--status` shows which colour is live, stop the other one
(`docker stop ai-pronunciation-trainer-<colour>`), at least 65 s after Caddy stopped sending it traffic.

A reboot during a deploy is handled like SIGKILL, but the harness does not test it. Caddy starts from the files in
the proxy directory: if the reboot came between deploy.sh writing `upstream.caddy` and its reload, Caddy serves the
new colour, which then has not passed its smoke test through port 3000, and the next run records it as deployed.
Docker starts every container that was running, and each warms up again. After such a reboot, wait until
`deploy/deploy.sh --status` shows the live colour `(healthy)`, then run
`python3 deploy/smoke_test.py http://127.0.0.1:3000 --timeout 60`; if it fails, `deploy/deploy.sh --rollback`.
Stop the colour that is not live if it runs, as above.

When CI fails at Trivy on a Debian package that has a fix, nothing in the repository needs to change: the system
packages are keyed on Debian's package indexes, so the next build upgrades them once Debian has published the fix
(run CI again). A run of CI started by hand with the input `system_refresh` set to a new value forces the
upgrade; on the VM, `SYSTEM_REFRESH=<a new value> deploy/deploy.sh` does the same. Trivy ignores vulnerabilities
that have no fix yet.

### The first deploy with this script

A host that still runs the single container `ai-pronunciation-trainer` on port 3000 (every deploy before
phase 1) is moved behind the proxy by the first run:
1. The new release is started as blue and checked while the old container keeps serving.
2. The old container is stopped and the proxy takes over port 3000. gunicorn stops accepting connections from the
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

To an older release from phase 1 on, deploy its commit again. Its image is rebuilt from the build cache: about
35 s while Debian has published nothing new since that release was built, otherwise a minute or two more, with
the system packages upgraded (this needs the network to Debian):

```bash
deploy/deploy.sh <sha>
```

`4290c3e`, the release from before phase 1, is built with its own Dockerfile, which pins only torch and
torchaudio and downloads Whisper and the voice from Hugging Face in its warm-up step. That step runs again,
because deploy.sh's `git archive` context does not match the cache of the build that made the image that ran:
it takes minutes and needs the network to Hugging Face. Whatever the build cache no longer holds (the base
image, the other packages) comes in today's versions, so the result is not the image that ran and may fail its
warm-up (production is not touched then). The container that ran before the move behind the proxy, with that
image, is kept stopped as `ai-pronunciation-trainer-legacy`: `--rollback-legacy` brings it back, with downtime.

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
* **`Could not start ai-pronunciation-trainer. Production is DOWN`** after `--rollback-legacy`: the single
  container could not be started on port 3000, so deploy.sh tries to put a new proxy in front of the colour that
  was live, and says whether that worked. If it did not, free port 3000 (`docker ps --filter publish=3000` shows
  what holds it) and run `deploy/deploy.sh --replace-proxy`. Production is then as before the rollback: the proxy
  serves that colour, and the other colour, if there is one, still holds the previous release, stopped. Two
  things are left over: the single container, now named `ai-pronunciation-trainer` and not running, and the mark
  of a move behind the proxy (`migration-in-progress` in the state directory). Ignore "the next deploy.sh run
  finishes the move": until both are cleared, do not deploy or run `--rollback` or `--rollback-legacy`. Such a run
  takes them for an unfinished move, finishes it and removes the other colour, so `--rollback` has nothing left
  to go back to. `--status` and `--replace-proxy` are safe. Clear them, then check:

  ```bash
  docker rename ai-pronunciation-trainer ai-pronunciation-trainer-legacy   # if it exists
  rm -f ~/.local/state/ai-pronunciation-trainer/migration-in-progress
  deploy/deploy.sh --status   # the proxy, the live colour, the other colour stopped, -legacy
  ```

  Find out what held port 3000 before you run `--rollback-legacy` again. The same applies when the run after a
  `--rollback-legacy` that was killed (SIGKILL, a reboot) reports "An earlier deploy was interrupted while it moved
  ai-pronunciation-trainer behind the proxy": clear the two leftovers as above before any other run of deploy.sh.
* **`The proxy still sends traffic to <colour>, so it is left running`**: a deploy failed after the switch, and
  Caddy did not take the switch back. That colour passed its own checks and serves. `deploy/deploy.sh --rollback`
  goes back to the other colour, or deploy again.
* **`Caddy's running configuration cannot be read, so <colour>, which it may still send traffic to, is left
  running`**: a deploy failed or was interrupted while it switched Caddy to the new colour, and after trying to
  point Caddy back, deploy.sh could not read from Caddy's admin API where it sends traffic. So it stopped neither
  colour, and the previous release did not go back into the new colour's slot.
  `curl -s http://127.0.0.1:3000/version` names the release that serves, and the images in `--status` show which
  colour holds it (while Caddy cannot be read, `--status` marks as live the colour that `upstream.caddy` names);
  `docker logs --tail 50 ai-pronunciation-trainer-proxy` may say why Caddy does not answer. If the new colour
  serves, go on as in the entry above once `--status` marks it live. If the other colour serves, stop the new one
  (`docker stop ai-pronunciation-trainer-<colour>`): it holds the release that failed. `--rollback` refuses that
  release, so until the next deploy, the way back is to deploy an older commit by its sha.
  deploy.sh reads Caddy through that admin API. While it cannot, `--status` and deploy.sh take the colour that
  `upstream.caddy` names (the previous one) as live: a deploy would then stop and replace the colour that serves.
  So do not deploy or run `--rollback` until `--status` agrees with `/version`. If the new colour serves and the
  admin API does not come back within a few minutes, run `deploy/deploy.sh --replace-proxy` (outside school
  hours if you can): it starts a proxy from the files, in front of the colour that `upstream.caddy` names. Then
  stop the new colour, at least 65 s after Caddy stopped sending it traffic.
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
* Every request through port 3000 failed at the same moment, and the proxy runs again: docker restarts the proxy
  when it dies, for example when the kernel kills it for memory. It holds each request body until it has all of
  it, in up to 1 GB, which held about 110 uploads of 4.9 MB at once in a test; more at once can exceed it.
  `docker inspect -f '{{.RestartCount}} {{.State.StartedAt}}' ai-pronunciation-trainer-proxy` shows how often
  docker has restarted it and when it last started (`.State.OOMKilled` is cleared once it runs again).
  `docker events --since 1h --until 0s --filter container=ai-pronunciation-trainer-proxy --filter event=oom`
  confirms an OOM kill, but only while the daemon still keeps that event among its latest ones.
* A run of the single-container deploy.sh from before phase 1 was interrupted and left
  `ai-pronunciation-trainer-previous` or `-staging`, or `swap-in-progress` in the state directory: deploy.sh
  refuses to run. Do not remove `-previous` before production serves again: it may be the only copy of the
  release that was live. Recover as that deploy.sh did on its next run:
  1. Look at `docker ps -a` and at the last line of `~/.local/state/ai-pronunciation-trainer/deploys.log`
     (`<time> <sha> <container id>`).
  2. If both `ai-pronunciation-trainer` and `-previous` exist, `ai-pronunciation-trainer` is the release that the
     run was putting in place. Keep it only if it runs and its id
     (`docker container inspect -f '{{.Id}}' ai-pronunciation-trainer`) is the one on that last line. Otherwise
     remove it (`docker rm -f ai-pronunciation-trainer`; its image stays).
  3. If `-previous` exists and `ai-pronunciation-trainer` does not (or no longer does), put the old release back:
     `docker rename ai-pronunciation-trainer-previous ai-pronunciation-trainer`, then
     `docker start ai-pronunciation-trainer`. If there is no `-previous` and `ai-pronunciation-trainer` is stopped,
     start it.
  4. Wait until `docker ps` shows it `(healthy)` and
     `curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:3000/` prints 200 (releases from before phase 1
     have no `/healthz`).
  5. Remove the leftovers (`docker rm -f ai-pronunciation-trainer-staging ai-pronunciation-trainer-previous`,
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
python3 deploy/smoke_test.py http://127.0.0.1:3000 --timeout 60   # through the proxy; :3001 / :3002 for one colour
curl -s http://127.0.0.1:3000/readyz                       # 200 once every worker has warmed up
```

Every line of the app's log is a JSON object (`docker logs ai-pronunciation-trainer-blue 2>&1 | jq -R 'fromjson? // .'`
also shows any line that is not):
* gunicorn's access log: `rid`, `m`, `path`, `status`, `bytes`, `ms`, `pid`; no client IP, query string or body;
* one `scored` line per recording, with `queue_ahead` (recordings already on that worker), `decode_ms`,
  `lock_wait_ms`, `asr_ms`, `match_ms`, `total_ms`, `audio_s`, `words`, `accuracy` and `outcome` (`ok`,
  `no_speech`, `too_long`, `bad_audio`, `busy` with `retry_after_s`, `client_gone`, `error`), but never the text
  or the audio. `busy` means the worker held as many recordings as it takes and answered 503 with Retry-After
  (the page sends the recording again); many of them outside a class burst mean the server is too slow for its
  load. `client_gone` means the learner gave up while the recording waited, and it was not scored;
* app warnings and errors with the request id (`rid`), and tracebacks in `exc`;
* gunicorn's own messages (worker start and exit).

Libraries that log through Python's root logger log errors only (faster-whisper would log every transcription
at INFO). The smoke test (deploy.sh's checks and the canary) sends a recording or a text again after a 503 busy
answer, as the page does, so a class at work neither fails a deploy nor sets off the canary; it prints
`busy (503), sending it again in N s` when that happens. ONNX Runtime writes its own messages to stderr and reports errors only; what it says while it is
imported (on some virtual machines, a warning that the display is not a PCI device) is logged as a JSON line from
`aipt.piperTTS`. The proxy keeps no access log; it logs its own warnings and errors. Errors that the proxy answers
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

## Disk

deploy.sh keeps the images of the last 3 deploys but never prunes docker's build cache, which grows with every
build: each Debian update adds a system packages layer of about 460 MB. On 2026-11-15 the cache had reached 24 GB
of the 48 GB disk. Right after a deploy, this removes the cache that no build has used for an hour and keeps what
the live release was built from, so the next code-only build still comes from the cache (about 40 s):

```bash
df -h /
docker builder prune -f --filter until=1h
```

A release whose cache is gone is rebuilt in full when it is deployed again by its sha (minutes: it downloads its
packages and models again); `--rollback` uses the stopped colour and needs no build.

## Canary

`.github/workflows/canary.yml` runs `deploy/smoke_test.py` against the public site every 15 minutes from
GitHub Actions and retries once after a minute. A failed run sends GitHub's failure e-mail to the account that
last changed the workflow's schedule. GitHub delays scheduled runs at busy times, and disables the schedule
after 60 days without activity in the repository (re-enable it in the Actions tab).

## Testing the public site

Cloudflare blocks the default Python `urllib` user agent with a 403 error (error 1010). Test
https://aitrainer.ism.io.vn/ with a browser, with curl using a browser user agent, or with
`python3 deploy/smoke_test.py https://aitrainer.ism.io.vn --user-agent 'aitrainer-canary/1.0' --timeout 60` (with the
default 10 s, the quick checks fail on a site that is busy with recordings).

## Testing deploy.sh

`deploy/test/` holds a fault-injection harness: a small stand-in for the app, a `docker` wrapper that injects
failures and signals at every step, and scenarios for fresh hosts, the move behind the proxy, failed releases,
signals and SIGKILL at each step, concurrent runs and rollbacks, with traffic running. See `deploy/test/README.md`.
