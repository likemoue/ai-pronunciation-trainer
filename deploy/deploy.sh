#!/usr/bin/env bash
# Build, check and roll out AI Pronunciation Trainer on this host while the
# requests in flight finish (deploy/RUNBOOK.md: one sent at the very moment of a
# switch can still fail).
#
#   deploy/deploy.sh [git-ref]          build and deploy a commit on main (default: origin/main)
#   deploy/deploy.sh --rollback         make the previous release live again, without downtime
#   deploy/deploy.sh --status           show what is live
#   deploy/deploy.sh --replace-proxy    recreate the proxy from CADDY_IMAGE (downtime: see deploy/RUNBOOK.md)
#   deploy/deploy.sh --rollback-legacy  bring back the single container of earlier versions (downtime)
#
# Layout (deploy/RUNBOOK.md):
#   $APP-proxy   Caddy, the only container on PROD_PORT (3000). It forwards to
#                the live colour over the docker network $APP-net.
#   $APP-blue    the app. The live colour runs; the other one holds the
#   $APP-green   previous release, stopped, for --rollback. Each colour also
#                listens on 127.0.0.1 (BLUE_PORT, GREEN_PORT) for smoke tests.
#
# A deploy:
# 1. builds $APP:<short sha> from the commit with `git archive`, so the
#    checkout is never changed and local edits are never built. Commits that
#    do not contain OLDEST_RELEASE are refused;
# 2. starts it in the idle colour, waits until it is healthy and runs that
#    commit's deploy/smoke_test.py against it. Production is not touched if
#    anything fails, and the failed image is removed;
# 3. points Caddy at the new colour with a graceful reload and smoke-tests it
#    through the proxy; if that fails, Caddy is pointed back. Requests that
#    Caddy accepted before the reload, including those whose body is still
#    arriving, go to the old colour;
# 4. records the deploy in DEPLOY_LOG, keeps the old colour running until Caddy
#    can no longer send it a request (READ_BODY_SECONDS + DRAIN_MARGIN after the
#    reload), stops it once it has finished its requests, and keeps the images
#    of the last KEEP_IMAGES deploys. Image tags that are not in DEPLOY_LOG, or
#    that do not name a commit (for example ones made by hand), are never removed.
#
# The first run on a host that still has the single container of earlier
# versions ($APP, publishing PROD_PORT) moves it behind the proxy. It keeps
# serving until the new colour has passed its checks; then it is stopped and
# the proxy takes over its port, which interrupts service for a few seconds,
# once. It is kept, stopped, as $APP-legacy, and --rollback-legacy can bring it
# back, with downtime.
#
# Only one deploy runs at a time. An interrupted run (Ctrl-C, a dropped session,
# a closed output pipe) undoes what it started. If a run is killed (SIGKILL, a
# reboot) while it moves the single container behind the proxy, the next run
# finishes that move or undoes it.
#
# Run it so that it survives a dropped SSH session; see deploy/RUNBOOK.md.
# Needs docker, git, curl, python3, flock and setsid (util-linux); no sudo.
set -Eeuo pipefail

APP=${APP:-ai-pronunciation-trainer}
REPO_DIR=${REPO_DIR:-"$HOME/ai-pronunciation-trainer"}
PROD_PORT=${PROD_PORT:-3000}
BLUE_PORT=${BLUE_PORT:-3001}
GREEN_PORT=${GREEN_PORT:-3002}
KEEP_IMAGES=${KEEP_IMAGES:-3}
HEALTH_TIMEOUT=${HEALTH_TIMEOUT:-360}
# A stopping colour finishes the requests it has accepted within 120 s
# (gunicorn's graceful_timeout, gunicorn.conf.py); docker kills it after this.
STOP_TIMEOUT=${STOP_TIMEOUT:-130}
# Caddy's read_body: the longest a client may take to send a whole request.
# Caddy sends a request to the colour of the configuration that accepted it,
# once its body has arrived, so a colour that loses its traffic at a reload
# keeps running READ_BODY_SECONDS + DRAIN_MARGIN after that reload.
READ_BODY_SECONDS=${READ_BODY_SECONDS:-60}
DRAIN_MARGIN=${DRAIN_MARGIN:-5}
# The smoke tests on PROD_PORT run once traffic has moved, and the colour that
# took it may be busy with recordings: each quick check may take this long, and
# the page, samples, speech and scoring at least 120 s (smoke_test.py --timeout).
PROD_SMOKE_TIMEOUT=${PROD_SMOKE_TIMEOUT:-60}
# The oldest commit deploy.sh deploys (phase 0b, 4290c3e). Older commits have
# sentences unsuitable for children or a voice licensed for research only.
OLDEST_RELEASE=${OLDEST_RELEASE:-4290c3e5bb19d32bffd6e28d2d243b8950e56842}
# The key of the image's system-package layer (Dockerfile). Empty: what
# scripts/system_refresh.sh beside this script prints, else the ISO week.
SYSTEM_REFRESH=${SYSTEM_REFRESH:-}
# Caddy 2.11.9 (alpine), pinned by the digest of its multi-platform index.
CADDY_IMAGE=${CADDY_IMAGE:-caddy:2.11.9-alpine@sha256:003a97808e781aa9f7e75cc2f43d34d461099031faf5e20faefb9f61126836f0}
# One line per successful deploy: "<UTC time> <short sha> <container id>", newest last.
DEPLOY_LOG=${DEPLOY_LOG:-"$HOME/.local/state/$APP/deploys.log"}
STATE_DIR=$(dirname "$DEPLOY_LOG")
PROXY_DIR="$STATE_DIR/proxy"
# Present only while the single container is being moved behind the proxy.
MIGRATION_MARK="$STATE_DIR/migration-in-progress"

PROXY="$APP-proxy"
NETWORK="$APP-net"
BLUE="$APP-blue"
GREEN="$APP-green"
LEGACY="$APP"
LEGACY_KEPT="$APP-legacy"
# Images built by deploy.sh carry this label (value: APP), so the ones that lost
# their tag to a rebuild of the same commit can be removed. It is the build's
# only --label, so no layer cached by docker's legacy builder carries it.
BUILD_LABEL=aipt.deploy.app

# Resource limits and log rotation for the app containers.
# shellcheck disable=SC2054  # the commas belong to --tmpfs options
RUN_FLAGS=(--memory 9g --memory-swap 9g --pids-limit 512
           --cap-drop ALL --security-opt no-new-privileges
           --log-opt max-size=10m --log-opt max-file=3
           --tmpfs /tmp:rw,nosuid,size=256m)
# How the single container of earlier versions was run (deploy/RUNBOOK.md).
# shellcheck disable=SC2054
LEGACY_RUN_FLAGS=(--memory 9g --memory-swap 9g --pids-limit 512
                  --log-opt max-size=10m --log-opt max-file=3
                  --tmpfs /tmp:rw,nosuid,size=256m)
# Caddy holds each request body in memory until it is complete (request_buffers,
# up to 5 MB, in a buffer that grows to about 10 MB). With 1 GB and no swap, and
# Go's garbage collector working hard from 800 MiB, it held about 110 uploads of
# 4.9 MB at once (256 MB held 40).
PROXY_FLAGS=(--memory 1g --memory-swap 1g --pids-limit 256 --read-only -e GOMEMLIMIT=800MiB
             --cap-drop ALL --cap-add NET_BIND_SERVICE --security-opt no-new-privileges
             --tmpfs /config --tmpfs /data --tmpfs /tmp
             --log-opt max-size=10m --log-opt max-file=3)

# Caddy's configuration. deploy.sh writes it on every run; upstream.caddy names
# the live colour.
read -r -d '' CADDYFILE <<'EOF' || true
# Written by deploy/deploy.sh; changes here are overwritten by the next deploy.
{
	admin 127.0.0.1:2019
	# Cloudflare terminates TLS; the tunnel connects over plain HTTP.
	auto_https off
	# Caddy's own errors only. There is no access log: the app logs every request.
	log {
		output stderr
		format json
		level WARN
	}
	# A client that sends its request slowly holds a connection here, not one of
	# the app's threads (see request_buffers below), and only for so long. After
	# a switch, deploy.sh keeps the old colour running for read_body and a margin.
	servers {
		timeouts {
			read_header 10s
			read_body @READ_BODY_SECONDS@s
		}
	}
}

:3000 {
	request_body {
		max_size 5MB
	}
	reverse_proxy {
		import upstream.caddy
		# The app gets each request only once its body has arrived in full.
		request_buffers 5MB
		# If the live colour does not accept connections (a restart), keep
		# trying for a while before answering 502.
		lb_try_duration 10s
		lb_try_interval 250ms
		transport http {
			response_header_timeout 125s
			# Close idle connections before gunicorn does (its keepalive is
			# 5 s), so a request never goes out on one gunicorn is closing.
			keepalive 4s
		}
	}
	# Errors the proxy answers itself get the app's JSON shape.
	handle_errors 413 {
		header Content-Type application/json
		header X-Content-Type-Options nosniff
		respond `{"error": "The request is too large.", "code": "request_entity_too_large"}` 413
	}
	handle_errors 502 503 504 {
		header Content-Type application/json
		header X-Content-Type-Options nosniff
		respond `{"error": "The server is restarting. Please try again in a moment.", "code": "server_unavailable"}` {err.status_code}
	}
}
EOF
CADDYFILE=${CADDYFILE//@READ_BODY_SECONDS@/$READ_BODY_SECONDS}

log() { printf '\n==> %s\n' "$*"; }
say() { printf '%s\n' "$*" >&2; }
die() { say "$1"; exit "${2:-1}"; }
now() { date -u +%Y-%m-%dT%H:%M:%SZ; }

# `docker inspect NAME` would also match an image called NAME:latest.
container_exists() { docker container inspect "$1" >/dev/null 2>&1; }
container_running() { [[ "$(docker container inspect -f '{{.State.Running}}' "$1" 2>/dev/null)" == "true" ]]; }
container_id() { docker container inspect -f '{{.Id}}' "$1" 2>/dev/null || true; }
container_image() { docker container inspect -f '{{.Config.Image}}' "$1" 2>/dev/null || true; }
container_image_id() { docker container inspect -f '{{.Image}}' "$1" 2>/dev/null || true; }
image_id() { docker image inspect -f '{{.Id}}' "$1" 2>/dev/null || true; }
deployed_before() { [[ -f "$DEPLOY_LOG" ]] && awk -v sha="$1" '$2 == sha { found = 1 } END { exit !found }' "$DEPLOY_LOG"; }
# The newest distinct releases in DEPLOY_LOG, on one line.
recent_deploys() { { awk '{print $2}' "$DEPLOY_LOG" | tac | awk '!seen[$0]++' | head -n 4 | paste -sd ' ' -; } 2>/dev/null || true; }

# The commit a container runs: its image's revision label (the Dockerfile sets
# it from phase 1 on; a container recreated from a bare image id has no tag),
# else the tag of its image.
release_of() {  # release_of <container>
    local revision image
    revision=$(docker container inspect -f '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$1" 2>/dev/null || true)
    if [[ $revision =~ ^[0-9a-f]{7,40}$ ]]; then
        echo "$revision"
    else
        image=$(container_image "$1")
        echo "${image##*:}"
    fi
}
# True if the container publishes port 3000 as host port PROD_PORT.
publishes_prod_port() { docker port "$1" 3000/tcp 2>/dev/null | grep -qE ":$PROD_PORT\$"; }
port_of() { if [[ $1 == "$BLUE" ]]; then echo "$BLUE_PORT"; else echo "$GREEN_PORT"; fi; }
other_colour() { if [[ $1 == "$BLUE" ]]; then echo "$GREEN"; else echo "$BLUE"; fi; }
http_ok() { curl -fsS -o /dev/null -m "${2:-5}" "$1" 2>/dev/null; }

# The colour Caddy sends traffic to (empty if there is no proxy): what its
# running configuration says while it runs, else the file it starts from. The
# two differ if a run was killed between writing the file and the reload.
live_colour() {
    local target=
    container_exists "$PROXY" || return 0
    if container_running "$PROXY"; then
        target=$(running_upstream)
    fi
    [[ -n "$target" ]] || target=$(file_upstream)
    [[ $target == "$BLUE" || $target == "$GREEN" ]] && echo "$target" || true
}

# The upstream named in upstream.caddy.
file_upstream() {
    awk '$1 == "to" { sub(/:3000$/, "", $2); print $2 }' "$PROXY_DIR/upstream.caddy" 2>/dev/null || true
}

# The upstream in Caddy's running configuration, from its admin API.
running_upstream() {
    # -T: BusyBox wget would otherwise wait 900 s for an admin API that accepts and never answers.
    { docker exec "$PROXY" wget -T 3 -qO- http://127.0.0.1:2019/config/apps/http/servers 2>/dev/null || true; } \
        | grep -oE '"dial":"[^"]+:3000"' | head -n 1 | sed -E 's/^"dial":"(.*):3000"$/\1/' || true
}
# The same, tried for a few seconds while the proxy runs: empty if it cannot be read.
running_upstream_patiently() {
    local try upstream=
    for try in 1 2 3 4 5; do
        upstream=$(running_upstream)
        [[ -n "$upstream" ]] && break
        container_running "$PROXY" || break
        sleep 1
    done
    echo "$upstream"
}

wait_healthy() {
    local name=$1 deadline=$((SECONDS + HEALTH_TIMEOUT)) status
    while (( SECONDS < deadline )); do
        if ! container_running "$name"; then
            say "$name is not running."
            return 1
        fi
        status=$(docker container inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$name" 2>/dev/null || true)
        case "$status" in
            healthy) echo "$name is healthy after $((HEALTH_TIMEOUT - deadline + SECONDS)) s"; return 0 ;;
            unhealthy) say "$name is unhealthy."; return 1 ;;
            none) say "$name has no health check (its image has no HEALTHCHECK)."; return 1 ;;
        esac
        sleep 3
    done
    say "$name did not become healthy within $HEALTH_TIMEOUT s."
    return 1
}

wait_http() {  # wait_http <url> <seconds>
    local deadline=$((SECONDS + $2))
    until http_ok "$1" 3; do
        (( SECONDS < deadline )) || return 1
        sleep 0.2
    done
}

# smoke <base url> [seconds]: the smoke test of the commit being deployed, with
# that long for each quick check (smoke_test.py --timeout; smoke tests from before
# phase 1 do not have the option and keep their 10 s).
smoke() {
    local options=()
    if [[ -n "${2:-}" ]] && grep -q -- '--timeout' "$WORK/smoke_test.py"; then
        options=(--timeout "$2")
    fi
    python3 "$WORK/smoke_test.py" "$1" "${options[@]}"
}

# The docker CLI gives up at once on SIGINT, SIGTERM or SIGHUP while the daemon
# carries on with what it was asked. setsid -w keeps the commands that change a
# colour away from the terminal's signals, so bash runs its trap only once they
# have returned, and on_abort finds the colour as they left it.
remove_container() {
    container_exists "$1" || return 0
    container_running "$1" && setsid -w docker stop -t "$STOP_TIMEOUT" "$1" >/dev/null
    setsid -w docker rm -f "$1" >/dev/null
}

ensure_network() {
    docker network inspect "$NETWORK" >/dev/null 2>&1 || docker network create "$NETWORK" >/dev/null
}

# Write the proxy's configuration for <colour>. Caddy checks it first: a file it
# refuses would stop the proxy at its next start (a reboot), so it is never put
# in place. CADDY_IMAGE checks it and, unless a new proxy will read it ("new"),
# so does the image of the existing proxy when it is another one (see --status).
write_proxy_config() {  # write_proxy_config <colour> [new]
    local next="$PROXY_DIR/next" images=("$CADDY_IMAGE") image running
    if [[ "${2:-}" != new ]] && container_exists "$PROXY" && [[ "$(container_image "$PROXY")" != "$CADDY_IMAGE" ]]; then
        running=$(container_image_id "$PROXY")
        [[ -z "$running" ]] || images+=("$running")
    fi
    mkdir -p "$next"
    printf '%s\n' "$CADDYFILE" > "$next/Caddyfile"
    printf 'to %s:3000\n' "$1" > "$next/upstream.caddy"
    for image in "${images[@]}"; do
        if ! docker run --rm --network none -v "$next:/etc/caddy:ro" "$image" \
                caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile >"$next/validate.log" 2>&1; then
            tail -n 5 "$next/validate.log" >&2
            say "!! Caddy refuses the new configuration ($next); the files in $PROXY_DIR are unchanged."
            if [[ "$image" != "$CADDY_IMAGE" ]]; then
                say "   $PROXY runs $(container_image "$PROXY"), which refuses it; $CADDY_IMAGE accepts it."
                say "   Recreate the proxy from $CADDY_IMAGE with deploy/deploy.sh --replace-proxy (deploy/RUNBOOK.md)."
            fi
            return 1
        fi
    done
    # Replace the files, never edit them in place: the proxy reads them through
    # a mount of the directory.
    mv -f "$next/Caddyfile" "$PROXY_DIR/Caddyfile"
    mv -f "$next/upstream.caddy" "$PROXY_DIR/upstream.caddy"
}

reload_proxy() {
    # The status is caddy reload's: a terminal that has gone away (tail cannot
    # write) does not undo a reload that Caddy applied.
    docker exec "$PROXY" caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile 2>&1 \
        | { tail -n 3 >&2 || true; }
}

# True if Caddy's running configuration sends traffic to <colour>.
proxy_sends_to() { [[ -n "$1" && "$(running_upstream)" == "$1" ]]; }

# Start the proxy and check that it publishes PROD_PORT. docker releases a
# stopped container's port a moment after `docker stop` returns, and a
# container whose start failed on a taken port may later start without
# publishing it, so each new attempt uses a new container.
start_proxy() {
    local try error=
    for try in 1 2 3 4 5 6; do
        if error=$(docker start "$PROXY" 2>&1 >/dev/null) && publishes_prod_port "$PROXY"; then
            return 0
        fi
        docker rm -f "$PROXY" >/dev/null 2>&1
        create_proxy || return 1
        sleep 0.5
    done
    say "Could not start $PROXY on port $PROD_PORT. The last docker start said: ${error:-nothing, but the port was not published}"
    say "Check what holds port $PROD_PORT with: docker ps --filter publish=$PROD_PORT"
    return 1
}

create_proxy() {
    docker create --name "$PROXY" --network "$NETWORK" --restart unless-stopped \
        -p "$PROD_PORT:3000" -v "$PROXY_DIR:/etc/caddy:ro" "${PROXY_FLAGS[@]}" \
        "$CADDY_IMAGE" caddy run --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null
}

# Start a stopped container. Once a start has failed because the port was
# taken, Docker may never publish that container's port again (later starts
# "succeed" without it), so check the port and recreate the container from its
# image if needed. Only for the single container of earlier versions.
start_legacy() {
    local image try
    image=$(container_image_id "$LEGACY") || return 1
    docker start "$LEGACY" >/dev/null 2>&1
    publishes_prod_port "$LEGACY" && return 0
    for try in 1 2 3 4 5 6; do
        docker rm -f "$LEGACY" >/dev/null 2>&1
        if docker run -d --name "$LEGACY" --restart unless-stopped -p "$PROD_PORT:3000" \
                "${LEGACY_RUN_FLAGS[@]}" "$image" >/dev/null; then
            say "Recreated $LEGACY from its image."
            return 0
        fi
        say "Could not recreate $LEGACY (attempt $try of 6); retrying in 10 s."
        sleep 10
    done
    return 1
}

# Start a new proxy in front of <colour>. PROD_PORT must be free.
proxy_in_front_of() {  # proxy_in_front_of <colour>
    write_proxy_config "$1" new || return 1
    recreate_proxy
}

# Replace the proxy container with a new one from CADDY_IMAGE, which reads the
# files in PROXY_DIR, and wait until it answers.
recreate_proxy() {
    docker rm -f "$PROXY" >/dev/null 2>&1
    create_proxy && start_proxy && wait_http "http://127.0.0.1:$PROD_PORT/" 30
}

# When the single container cannot be put back, serve the new release instead.
fall_forward() {  # fall_forward <colour>
    if proxy_in_front_of "$1"; then
        say "!! Could not put $LEGACY back, so the proxy now serves $1, which passed its own checks."
        say "   Check the site (deploy/RUNBOOK.md); the next deploy.sh run finishes the move."
    else
        say "!! The proxy does not serve $1 either. Production is DOWN; see deploy/RUNBOOK.md."
    fi
}

# Put the single container back on PROD_PORT after a failed or interrupted move
# behind the proxy. Called with traps and errexit off.
restore_legacy() {
    say "Putting $LEGACY back on port $PROD_PORT."
    docker rm -f "$PROXY" >/dev/null 2>&1
    if ! container_exists "$LEGACY" && container_exists "$LEGACY_KEPT"; then
        docker rename "$LEGACY_KEPT" "$LEGACY"
    fi
    # Already serving (it was never stopped, or someone started it by hand).
    if container_running "$LEGACY" && publishes_prod_port "$LEGACY" && http_ok "http://127.0.0.1:$PROD_PORT/" 10; then
        rm -f "$MIGRATION_MARK"
        say "$LEGACY serves port $PROD_PORT."
        return 0
    fi
    if container_exists "$LEGACY"; then
        # A stop that is still in progress would undo the start; wait for it.
        docker stop -t "$STOP_TIMEOUT" "$LEGACY" >/dev/null 2>&1
        if start_legacy; then
            rm -f "$MIGRATION_MARK"
            say "$LEGACY is serving port $PROD_PORT again."
            return 0
        fi
    fi
    say "!! Could not start $LEGACY. Production is DOWN; see deploy/RUNBOOK.md."
    return 1
}

remove_failed_image() {
    # An image that failed is never used again, unless a container uses it or
    # an earlier deploy did (then it is a rollback candidate).
    local failed_id name
    failed_id=$(image_id "$IMAGE")
    [[ -n "$failed_id" ]] || return 0
    for name in "$BLUE" "$GREEN" "$LEGACY" "$LEGACY_KEPT"; do
        [[ "$(container_image_id "$name")" == "$failed_id" ]] && return 0
    done
    deployed_before "$SHA" && return 0
    docker rmi "$IMAGE" >/dev/null 2>&1 && echo "Removed the failed image $IMAGE." || true
}

prune_images() {
    # Keep the images of the last KEEP_IMAGES distinct deploys; docker refuses
    # to remove an image a container (running or stopped) still uses. Only the
    # entries that name a commit are tags of this script: a release switched to
    # by hand (deploy/RUNBOOK.md) is logged under its own tag, which stays.
    local keep sha
    keep=$(awk '{print $2}' "$DEPLOY_LOG" | tac | awk -v n="$KEEP_IMAGES" '!seen[$0]++ { if (count++ < n) print }')
    for sha in $(awk '$2 ~ /^[0-9a-f]+$/ && length($2) >= 7 && length($2) <= 40 { print $2 }' "$DEPLOY_LOG" | sort -u); do
        grep -qx "$sha" <<<"$keep" && continue
        [[ -n "$(image_id "$APP:$sha")" ]] || continue
        docker rmi "$APP:$sha" >/dev/null 2>&1 && echo "removed $APP:$sha" || true
    done
    # Images that lost their tag to a rebuild of the same commit (a new
    # SYSTEM_REFRESH) and that no container uses.
    docker image prune --force --filter "label=$BUILD_LABEL=$APP" >/dev/null 2>&1 || true
}

record_deploy() {  # record_deploy <sha> <container>
    printf '%s %s %s\n' "$(now)" "$1" "$(container_id "$2")" >> "$DEPLOY_LOG"
}

# ------------------------------------------------------------------ interruptions

PHASE=prepare   # prepare, staging, switching, migrating, live
STAGED=         # colour this run fills: set before its previous release is removed
SWITCHED_FROM=  # live colour before the switch
MIGRATED=0      # this run moved the single container behind the proxy
PREVIOUS_REF=   # image of the release that STAGED replaced (name, and id)
PREVIOUS_ID=
RELOADED_AT=    # SECONDS when a caddy reload last took the traffic off a colour

# Caddy sends a request to the colour of the configuration that accepted it,
# once its body has arrived: up to READ_BODY_SECONDS after the reload that took
# the traffic off that colour. Wait until then, and DRAIN_MARGIN more, before
# <colour> is told to stop.
drain() {  # drain <colour>
    local left
    # SECONDS counts whole seconds; one more makes the wait at least that long.
    # When the time of the reload is not known, it counts from now.
    left=$((${RELOADED_AT:-$SECONDS} + READ_BODY_SECONDS + DRAIN_MARGIN + 1 - SECONDS))
    (( left > 0 )) || return 0
    echo "$1 gets $left s more for the requests Caddy accepted before the switch (read_body $READ_BODY_SECONDS s + $DRAIN_MARGIN s)."
    sleep "$left"
}

# After a failed deploy, the stopped previous release goes back into its slot,
# so --rollback still finds it.
restore_previous_release() {  # restore_previous_release <colour>
    local image=$PREVIOUS_ID
    [[ -n "$PREVIOUS_ID" ]] || return 0
    [[ "$(image_id "$PREVIOUS_REF")" == "$PREVIOUS_ID" ]] && image=$PREVIOUS_REF
    docker create --name "$1" --network "$NETWORK" --restart unless-stopped \
        -p "127.0.0.1:$(port_of "$1"):3000" --stop-timeout "$STOP_TIMEOUT" "${RUN_FLAGS[@]}" "$image" >/dev/null \
        && say "$1 holds the previous release again ($PREVIOUS_REF), stopped, for --rollback."
}

# Work that must not stop half-way: putting production back, or moving it.
critical_section() {
    # Finish even if interrupted again or if the output pipe is gone.
    trap '' INT TERM HUP PIPE
    trap - ERR
    set +e
    # The docker CLI handles SIGINT and SIGTERM itself even while this shell
    # ignores them, and gives up while the daemon carries on: keep it away from
    # the terminal's signals.
    docker() { setsid -w docker "$@"; }
}

on_abort() {  # on_abort <what happened>
    local upstream
    critical_section
    say ""
    say "!! $1 while $PHASE."
    case "$PHASE" in
        staging)
            if [[ -n "$STAGED" ]]; then
                # The new release's log; not the previous release's, if the run
                # was interrupted while that one was being removed.
                if [[ "$(container_image "$STAGED")" == "${IMAGE:-}" ]]; then
                    docker logs --tail 50 "$STAGED" 2>&1 | tail -n 50 >&2
                fi
                docker rm -f "$STAGED" >/dev/null 2>&1
                restore_previous_release "$STAGED"
            fi
            remove_failed_image
            say "Production was not touched." ;;
        switching)
            if [[ -n "$SWITCHED_FROM" ]] && container_running "$SWITCHED_FROM"; then
                # Even if the reload's status is lost (a signal, a closed
                # terminal), Caddy may have applied it: drain from now.
                if write_proxy_config "$SWITCHED_FROM"; then
                    reload_proxy || true
                    RELOADED_AT=$SECONDS
                fi
            fi
            if [[ -n "$STAGED" ]]; then
                upstream=$(running_upstream_patiently)
                if [[ "$upstream" == "$STAGED" ]]; then
                    # Never stop the colour that serves.
                    say "!! The proxy still sends traffic to $STAGED, so it is left running. Check with deploy/deploy.sh --status (deploy/RUNBOOK.md)."
                    exit 2
                elif [[ -z "$upstream" ]] && container_running "$PROXY"; then
                    # Nor one that may serve: the proxy runs, but what it sends
                    # traffic to cannot be read.
                    say "!! Caddy's running configuration cannot be read, so $STAGED, which it may still send traffic to, is left running. Check with deploy/deploy.sh --status (deploy/RUNBOOK.md)."
                    exit 2
                fi
            fi
            proxy_sends_to "$SWITCHED_FROM" && say "The proxy sends traffic to $SWITCHED_FROM."
            if [[ -n "$STAGED" ]]; then
                # It still gets the requests Caddy accepted before the switch
                # back, and finishes them when it is stopped.
                drain "$STAGED"
                docker stop -t "$STOP_TIMEOUT" "$STAGED" >/dev/null 2>&1
                docker rm -f "$STAGED" >/dev/null 2>&1
                restore_previous_release "$STAGED"
            fi
            remove_failed_image ;;
        migrating)
            if ! restore_legacy; then
                # Better the new release, which passed its own checks, than nothing.
                [[ -n "$STAGED" ]] && container_running "$STAGED" && fall_forward "$STAGED"
                exit 2
            fi
            [[ -n "$STAGED" ]] && docker rm -f "$STAGED" >/dev/null 2>&1
            remove_failed_image ;;
        live)
            say "The new release is live and recorded; the previous colour may still be running." ;;
    esac
    exit 1
}

# ------------------------------------------------------------------ recovery

refuse_old_leftovers() {
    local name
    for name in "$APP-previous" "$APP-staging"; do
        if container_exists "$name"; then
            die "$name exists: an earlier deploy with the single-container deploy.sh was interrupted. Check it with docker ps -a and remove it (see deploy/RUNBOOK.md), then deploy again."
        fi
    done
    [[ ! -f "$STATE_DIR/swap-in-progress" ]] \
        || die "$STATE_DIR/swap-in-progress exists: the single-container deploy.sh was interrupted. See deploy/RUNBOOK.md."
}

# A run killed while it moved the single container behind the proxy. If the
# proxy serves, finish the move; otherwise put the single container back.
recover_interrupted_migration() {
    [[ -f "$MIGRATION_MARK" ]] || return 0
    local live sha
    say "An earlier deploy was interrupted while it moved $LEGACY behind the proxy."
    live=$(live_colour)
    if [[ -n "$live" ]] && container_running "$PROXY" && publishes_prod_port "$PROXY" \
            && container_running "$live" && wait_http "http://127.0.0.1:$PROD_PORT/" 10; then
        if container_running "$LEGACY"; then
            docker stop -t "$STOP_TIMEOUT" "$LEGACY" >/dev/null
        fi
        sha=$(release_of "$live")
        record_deploy "$sha" "$live"
        rm -f "$MIGRATION_MARK"
        docker tag "$(container_image_id "$live")" "$APP:latest"
        keep_legacy "$live"
        say "The proxy serves $live; finished the move. $LEGACY is kept, stopped, as $LEGACY_KEPT."
        return 0
    fi
    critical_section
    restore_legacy || exit 2
    die "Check it (deploy/RUNBOOK.md), then deploy again."
}

# The proxy was stopped, for example by hand: start it.
ensure_proxy_running() {
    container_running "$PROXY" && publishes_prod_port "$PROXY" && return 0
    say "$PROXY is not running on port $PROD_PORT; starting it."
    if ! start_proxy || ! wait_http "http://127.0.0.1:$PROD_PORT/" 30; then
        die "!! Could not start $PROXY. Production is DOWN; see deploy/RUNBOOK.md." 2
    fi
}

# ------------------------------------------------------------------ steps

# deploy.sh never makes live a commit that does not contain OLDEST_RELEASE.
check_not_too_old() {  # check_not_too_old <commit> <what to call it>
    local rc=0
    git -C "$REPO_DIR" cat-file -e "$OLDEST_RELEASE^{commit}" 2>/dev/null \
        || die "OLDEST_RELEASE ($OLDEST_RELEASE) is not a commit in $REPO_DIR; fetch it, or set OLDEST_RELEASE."
    git -C "$REPO_DIR" merge-base --is-ancestor "$OLDEST_RELEASE" "$1" 2>/dev/null || rc=$?
    case $rc in
        0) ;;
        1) die "$2 does not contain ${OLDEST_RELEASE:0:7} (OLDEST_RELEASE), the oldest release that deploy.sh deploys: older commits have sentences unsuitable for children or the voice licensed for research only. See deploy/RUNBOOK.md." ;;
        *) die "$2 is not a commit in $REPO_DIR, so deploy.sh cannot tell whether it contains ${OLDEST_RELEASE:0:7} (OLDEST_RELEASE)." ;;
    esac
}

prepare_commit() {  # prepare_commit <ref>: sets COMMIT, SHA, IMAGE and WORK/smoke_test.py
    local ref=$1
    log "Fetching $ref"
    # GitHub being down must not stop a deploy, for example of an older commit.
    if ! git -C "$REPO_DIR" fetch --quiet --prune origin '+refs/heads/*:refs/remotes/origin/*'; then
        say "Warning: could not fetch origin; using the refs fetched earlier."
    fi
    COMMIT=$(git -C "$REPO_DIR" rev-parse --verify -q "$ref^{commit}" || true)
    [[ -n "$COMMIT" ]] || die "Unknown ref $ref (after the fetch, branches are origin/<name>)."
    # CI checks every pull request and every push to main.
    if [[ "${DEPLOY_ANY_BRANCH:-0}" == 1 ]]; then
        if [[ -z "$(git -C "$REPO_DIR" branch -r --contains "$COMMIT" 2>/dev/null || true)" ]]; then
            die "$ref is not on any branch of origin. Push it first."
        fi
        say "DEPLOY_ANY_BRANCH=1: deploying $ref, which need not be on main."
    elif ! git -C "$REPO_DIR" merge-base --is-ancestor "$COMMIT" origin/main 2>/dev/null; then
        die "$ref is not on main. deploy.sh deploys commits of main, which CI has checked; for a test of another pushed branch, set DEPLOY_ANY_BRANCH=1."
    fi
    check_not_too_old "$COMMIT" "$ref"
    # Versions from before deploy.sh have no smoke test, and their image no
    # health check; they are rolled back by hand, see deploy/RUNBOOK.md.
    git -C "$REPO_DIR" show "$COMMIT:deploy/smoke_test.py" > "$WORK/smoke_test.py" 2>/dev/null \
        || die "$ref has no deploy/smoke_test.py, so deploy.sh cannot deploy it. To go back to a version from before deploy.sh, see deploy/RUNBOOK.md."
    SHA=$(git -C "$REPO_DIR" rev-parse --short=7 "$COMMIT")
    IMAGE="$APP:$SHA"
}

# CI's verdict on the commit (.github/workflows/ci.yml, its latest run), from
# the GitHub API. A failed or unfinished run stops the deploy. A commit from
# before CI existed has no run (an old release, for a rollback): a warning.
# SKIP_CI_CHECK=1 skips the question.
check_ci() {
    local origin repo verdict
    if [[ "${SKIP_CI_CHECK:-0}" == 1 ]]; then
        say "SKIP_CI_CHECK=1: not asking GitHub whether CI passed for $SHA."
        return 0
    fi
    # Without the credentials that an https origin may carry (https://user:token@...).
    origin=$(git -C "$REPO_DIR" remote get-url origin 2>/dev/null | sed -E 's#^([a-z+]+://)[^/@]*@#\1#' || true)
    repo=$(sed -nE 's#^(https://|ssh://|git@)github\.com[:/]([^/]+/[^/]+)$#\2#p' <<<"${origin%.git}")
    if [[ -z "$repo" ]]; then
        say "Warning: origin ($origin) is not a GitHub repository; not checking CI."
        return 0
    fi
    verdict=$(curl -fsS -m 20 -H 'Accept: application/vnd.github+json' \
            "https://api.github.com/repos/$repo/actions/workflows/ci.yml/runs?head_sha=$COMMIT&per_page=10" 2>/dev/null \
        | python3 -c '
import json, sys
runs = json.load(sys.stdin).get("workflow_runs", [])
latest = max(runs, key=lambda run: run["created_at"]) if runs else None
if latest is None:
    print("none")
elif latest["status"] != "completed":
    print("pending")
else:
    print(latest["conclusion"] or "unknown")' 2>/dev/null || echo unknown)
    case "$verdict" in
        success) echo "CI passed for $SHA." ;;
        none) say "Warning: CI has no run for $SHA (a commit from before CI existed?); deploying it anyway." ;;
        unknown) say "Warning: could not ask GitHub whether CI passed for $SHA; deploying it anyway." ;;
        pending) die "CI is still running for $SHA. Wait for it (https://github.com/$repo/actions), or set SKIP_CI_CHECK=1." ;;
        # A newer push to main cancels the run that was waiting for its turn.
        cancelled) die "CI's run for $SHA was cancelled. Re-run it (https://github.com/$repo/actions), or set SKIP_CI_CHECK=1." ;;
        *) die "CI did not pass for $SHA ($verdict). Fix it first, or set SKIP_CI_CHECK=1 to deploy it anyway." ;;
    esac
}

build_image() {
    local refresh=$SYSTEM_REFRESH from=SYSTEM_REFRESH script
    log "Building $IMAGE"
    # The Debian packages are refreshed when SYSTEM_REFRESH changes: by hand, or
    # from the state of Debian's archive (scripts/system_refresh.sh beside this
    # script), or else once a week.
    script="$(dirname "${BASH_SOURCE[0]}")/../scripts/system_refresh.sh"
    if [[ -z "$refresh" && -f "$script" ]]; then
        refresh=$(timeout 60 bash "$script" | head -n 1 | tr -d '\r' || true)
        from=scripts/system_refresh.sh
    fi
    if [[ -z "$refresh" ]]; then
        # The same form as the script's own fallback.
        refresh="week-$(date -u +%G-W%V)"
        from="the ISO week"
    fi
    echo "SYSTEM_REFRESH=$refresh ($from)"
    git -C "$REPO_DIR" archive --format=tar "$COMMIT" \
        | docker build --build-arg GIT_SHA="$SHA" \
            --build-arg GIT_DATE="$(git -C "$REPO_DIR" show -s --format=%cI "$COMMIT")" \
            --build-arg SYSTEM_REFRESH="$refresh" --label "$BUILD_LABEL=$APP" \
            -t "$IMAGE" -
    # The proxy image is needed later, at a moment when a download would add to an outage.
    [[ -n "$(image_id "$CADDY_IMAGE")" ]] || docker pull --quiet "$CADDY_IMAGE" >/dev/null
}

stage() {  # stage <colour>: start IMAGE in that colour and check it
    local target=$1 port
    port=$(port_of "$target")
    log "Starting $IMAGE as $target (127.0.0.1:$port)"
    PHASE=staging
    if container_exists "$target"; then
        # The previous release, kept for --rollback. If this deploy fails or is
        # interrupted from here on, it is created again from its image.
        PREVIOUS_REF=$(container_image "$target")
        PREVIOUS_ID=$(container_image_id "$target")
        echo "Replacing $target ($PREVIOUS_REF), the previous release."
        STAGED=$target
        remove_container "$target"
    fi
    ensure_network
    STAGED=$target
    # Out of reach of the terminal's signals (see remove_container): interrupted
    # here, on_abort runs once the container exists, and removes it before it
    # puts the previous release back. Otherwise the daemon could create it just
    # after on_abort's removal and take the name the previous release needs.
    setsid -w docker run -d --name "$target" --network "$NETWORK" --restart unless-stopped \
        -p "127.0.0.1:$port:3000" --stop-timeout "$STOP_TIMEOUT" "${RUN_FLAGS[@]}" "$IMAGE" >/dev/null
    if ! wait_healthy "$target" || ! smoke "http://127.0.0.1:$port"; then
        on_abort "The new release failed its checks"
    fi
}

# Point the proxy at <target>, check through it, keep <live> as the fallback.
switch_proxy() {  # switch_proxy <live> <target>
    local live=$1 target=$2
    log "Switching the proxy: ${live:-nothing} -> $target"
    PHASE=switching
    SWITCHED_FROM=$live
    write_proxy_config "$target" || on_abort "Caddy refused the new configuration"
    reload_proxy
    RELOADED_AT=$SECONDS
    if ! proxy_sends_to "$target"; then
        on_abort "Caddy did not take the new configuration"
    fi
    if ! smoke "http://127.0.0.1:$PROD_PORT" "$PROD_SMOKE_TIMEOUT"; then
        on_abort "The smoke test through the proxy failed"
    fi
    if ! serves_release "$SHA"; then
        on_abort "The proxy does not serve $SHA"
    fi
}

# True unless /version on PROD_PORT names another commit (older releases have no /version).
serves_release() {  # serves_release <sha>
    { curl -fsS -m 5 "http://127.0.0.1:$PROD_PORT/version" 2>/dev/null || true; } | python3 -c '
import json, sys
try:
    served = json.load(sys.stdin).get("git_sha")
except ValueError:
    served = None
sys.exit(0 if served in (None, "unknown", sys.argv[1]) else 1)' "$1"
}

# Move the single container of earlier versions behind the proxy.
migrate() {  # migrate <target>
    local target=$1 stopped_at
    log "Moving $LEGACY behind the proxy (port $PROD_PORT is unavailable for a few seconds)"
    write_proxy_config "$target" new || on_abort "Caddy refused the proxy's configuration"
    # From here on, an interruption puts the single container back, and a run
    # that is killed leaves the mark for the next one.
    PHASE=migrating
    container_id "$LEGACY" > "$MIGRATION_MARK"
    docker rm -f "$PROXY" >/dev/null 2>&1 || true
    create_proxy
    # gunicorn stops accepting connections as soon as it is told to stop, and
    # then finishes the requests it has.
    stopped_at=$(date +%s.%N)
    if container_running "$LEGACY"; then
        docker stop -t "$STOP_TIMEOUT" "$LEGACY" >/dev/null
    fi
    if ! start_proxy || ! wait_http "http://127.0.0.1:$PROD_PORT/" 30; then
        on_abort "The proxy did not answer on port $PROD_PORT"
    fi
    echo "Port $PROD_PORT refused new connections for $(awk -v a="$stopped_at" -v b="$(date +%s.%N)" 'BEGIN { printf "%.1f", b - a }') s: from the stop of $LEGACY until the proxy answered."
    if ! smoke "http://127.0.0.1:$PROD_PORT" "$PROD_SMOKE_TIMEOUT"; then
        on_abort "The smoke test through the proxy failed"
    fi
    MIGRATED=1
}

# After a move behind the proxy has been recorded: keep the single container,
# stopped, for --rollback-legacy.
keep_legacy() {  # keep_legacy <live colour>
    container_exists "$LEGACY" || return 0
    if container_exists "$LEGACY_KEPT"; then
        docker rm -f "$LEGACY_KEPT" >/dev/null 2>&1 || true
    fi
    docker rename "$LEGACY" "$LEGACY_KEPT" || say "Could not rename $LEGACY to $LEGACY_KEPT; it is stopped."
    # The other colour can only hold a release from before --rollback-legacy,
    # which was rolled back from: it is removed, so --rollback has no previous
    # colour until the next deploy (--rollback-legacy goes to the single container).
    docker rm -f "$(other_colour "$1")" >/dev/null 2>&1 || true
}

# First deploy on a host with neither the proxy nor the single container.
start_proxy_fresh() {  # start_proxy_fresh <target>
    local target=$1
    log "Starting the proxy on port $PROD_PORT"
    PHASE=switching
    write_proxy_config "$target" new || on_abort "Caddy refused the proxy's configuration"
    docker rm -f "$PROXY" >/dev/null 2>&1 || true
    create_proxy
    if ! start_proxy || ! wait_http "http://127.0.0.1:$PROD_PORT/" 30 || ! smoke "http://127.0.0.1:$PROD_PORT" "$PROD_SMOKE_TIMEOUT"; then
        docker rm -f "$PROXY" >/dev/null 2>&1
        on_abort "The proxy did not serve the new release"
    fi
}

# Stop the old colour once Caddy can no longer send it a request; it finishes
# the requests it has, and is kept for --rollback.
retire() {  # retire <container>
    [[ -n "$1" ]] && container_running "$1" || return 0
    log "Stopping $1 (kept for deploy/deploy.sh --rollback)"
    drain "$1"
    docker stop -t "$STOP_TIMEOUT" "$1" >/dev/null
}

finish() {  # finish <sha> <live container> <previous container>
    # Recording the deploy and treating it as live happen together: an
    # interruption before them undoes the switch, one after them does not.
    trap '' INT TERM HUP PIPE
    record_deploy "$1" "$2"
    rm -f "$MIGRATION_MARK"
    PHASE=live
    trap 'on_abort "Interrupted"' INT TERM HUP PIPE
    (( MIGRATED )) && keep_legacy "$2"
    docker tag "$(container_image_id "$2")" "$APP:latest"
    log "Deployed $(container_image "$2") as $2"
    retire "$3"
    log "Keeping the images of the last $KEEP_IMAGES deploys"
    prune_images || say "Image cleanup failed; the deploy itself succeeded."
    docker images "$APP"
}

deploy() {  # deploy <ref>
    local live target
    prepare_commit "$1"
    check_ci
    build_image
    live=$(live_colour)
    target=$BLUE
    [[ -n "$live" ]] && target=$(other_colour "$live")
    if container_exists "$PROXY"; then
        ensure_proxy_running
        stage "$target"
        switch_proxy "$live" "$target"
    elif container_exists "$LEGACY"; then
        live=
        stage "$target"
        migrate "$target"
    else
        stage "$target"
        start_proxy_fresh "$target"
    fi
    finish "$SHA" "$target" "$live"
}

# Recreate the proxy (a new CADDY_IMAGE). Port 3000 refuses new connections from
# the stop of the old proxy, which first finishes its requests, until the new one runs.
replace_proxy() {
    local live
    live=$(live_colour)
    # With no proxy at all, the colour the configuration names.
    [[ -n "$live" ]] || live=$(file_upstream)
    [[ -n "$live" ]] && container_running "$live" || die "No live colour is running; nothing to put the proxy in front of."
    log "Replacing $PROXY ($(container_image "$PROXY")) with $CADDY_IMAGE in front of $live"
    [[ -n "$(image_id "$CADDY_IMAGE")" ]] || docker pull --quiet "$CADDY_IMAGE" >/dev/null
    # The new image checks the configuration before the proxy is touched.
    write_proxy_config "$live" new || die "!! $CADDY_IMAGE refuses the configuration, so $PROXY was left as it was."
    critical_section
    # Caddy finishes the requests in flight when it is stopped.
    docker stop -t "$STOP_TIMEOUT" "$PROXY" >/dev/null 2>&1
    if ! recreate_proxy; then
        die "!! The new proxy does not serve. Production is DOWN; see deploy/RUNBOOK.md." 2
    fi
    log "$PROXY runs $CADDY_IMAGE"
}

rollback() {
    local live previous image sha
    container_exists "$PROXY" || die "There is no proxy: nothing deployed with this deploy.sh to roll back."
    ensure_proxy_running
    live=$(live_colour)
    [[ -n "$live" ]] || die "The proxy has no live colour ($PROXY_DIR/upstream.caddy)."
    previous=$(other_colour "$live")
    if container_exists "$previous"; then
        image=$(container_image "$previous")
        sha=$(release_of "$previous")
        # A deploy killed while it started its release leaves that release in
        # the idle colour, never deployed: it is not the previous release.
        deployed_before "$sha" \
            || die "$previous holds $image, which is not in $DEPLOY_LOG (a deploy that was interrupted?), so it is not the previous release. Deploy the release you want with deploy/deploy.sh <sha> (recent deploys: $(recent_deploys))."
        check_not_too_old "$sha" "$previous ($image)"
        log "Rolling back: $live ($(container_image "$live")) -> $previous ($image)"
        git -C "$REPO_DIR" show "$sha:deploy/smoke_test.py" > "$WORK/smoke_test.py" 2>/dev/null \
            || cp "$REPO_DIR/deploy/smoke_test.py" "$WORK/smoke_test.py"
        SHA=$sha
        IMAGE=$image
        PHASE=switching
        STAGED=
        docker start "$previous" >/dev/null
        if ! wait_healthy "$previous" || ! smoke "http://127.0.0.1:$(port_of "$previous")"; then
            docker stop -t "$STOP_TIMEOUT" "$previous" >/dev/null 2>&1 || true
            die "$previous failed its checks; $live is still live."
        fi
        switch_proxy "$live" "$previous"
        finish "$sha" "$previous" "$live"
        return 0
    fi
    say "There is no previous release in $previous. To go back without downtime, deploy an older commit:"
    say "  deploy/deploy.sh <sha>     (recent deploys: $(recent_deploys))"
    if container_exists "$LEGACY_KEPT"; then
        say "or bring back the single container from before the proxy ($(container_image "$LEGACY_KEPT")), with downtime (deploy/RUNBOOK.md):"
        say "  deploy/deploy.sh --rollback-legacy"
    fi
    exit 1
}

# Undo the move behind the proxy: the single container serves PROD_PORT again.
rollback_legacy() {
    local live sha
    container_exists "$LEGACY_KEPT" || die "There is no $LEGACY_KEPT to roll back to."
    live=$(live_colour)
    log "Rolling back to the single container from before the proxy ($(container_image "$LEGACY_KEPT"))"
    say "Port $PROD_PORT refuses new connections until the proxy has finished its requests (up to about 2 minutes) and the single container has started; the first requests are slow while it warms up."
    cp "$REPO_DIR/deploy/smoke_test.py" "$WORK/smoke_test.py"
    critical_section
    docker rename "$LEGACY_KEPT" "$LEGACY"
    container_id "$LEGACY" > "$MIGRATION_MARK"
    # Caddy finishes the requests in flight when it is stopped.
    docker stop -t "$STOP_TIMEOUT" "$PROXY" >/dev/null 2>&1
    if ! restore_legacy; then
        [[ -n "$live" ]] && container_running "$live" && fall_forward "$live"
        exit 2
    fi
    if ! wait_healthy "$LEGACY" || ! smoke "http://127.0.0.1:$PROD_PORT" "$PROD_SMOKE_TIMEOUT"; then
        say "!! $LEGACY serves port $PROD_PORT but failed its checks; the colours are still there (deploy/RUNBOOK.md)."
        exit 2
    fi
    [[ -n "$live" ]] && docker stop -t "$STOP_TIMEOUT" "$live" >/dev/null 2>&1
    sha=$(release_of "$LEGACY")
    record_deploy "$sha" "$LEGACY"
    docker tag "$(container_image_id "$LEGACY")" "$APP:latest"
    log "$LEGACY is live again. The colours are stopped; the next deploy moves it behind the proxy again."
}

status() {
    local name state live
    live=$(live_colour)
    # Without a proxy, the single container of earlier versions serves the port.
    if [[ -z "$live" ]] && container_running "$LEGACY" && publishes_prod_port "$LEGACY"; then
        live=$LEGACY
    fi
    printf '%-34s %-9s %s\n' CONTAINER STATE IMAGE
    for name in "$PROXY" "$BLUE" "$GREEN" "$LEGACY" "$LEGACY_KEPT"; do
        container_exists "$name" || continue
        state=$(docker container inspect -f '{{.State.Status}}{{if .State.Health}}/{{.State.Health.Status}}{{end}}' "$name" 2>/dev/null || true)
        printf '%-34s %-9s %s%s\n' "$name" "$state" "$(container_image "$name")" \
            "$([[ $name == "$live" ]] && echo '   <- live' || true)"
    done
    if container_exists "$PROXY" && [[ "$(container_image "$PROXY")" != "$CADDY_IMAGE" ]]; then
        echo "Note: $PROXY runs $(container_image "$PROXY"); deploy.sh pins $CADDY_IMAGE (deploy/RUNBOOK.md)."
    fi
    echo
    echo "Last deploys ($DEPLOY_LOG):"
    tail -n 5 "$DEPLOY_LOG" 2>/dev/null || echo "(none)"
    echo
    printf 'GET 127.0.0.1:%s/version -> ' "$PROD_PORT"
    curl -fsS -m 5 "http://127.0.0.1:$PROD_PORT/version" 2>/dev/null || echo "(no answer)"
    echo
}

main() {
    local arg=${1:-origin/main}
    case "$arg" in
        -h|--help) sed -n '2,/^set -E/p' "$0" | sed '$d; s/^# \{0,1\}//'; return 0 ;;
        --status) status; return 0 ;;
    esac
    [[ $READ_BODY_SECONDS =~ ^[1-9][0-9]*$ && $DRAIN_MARGIN =~ ^[0-9]+$ ]] \
        || die "READ_BODY_SECONDS ($READ_BODY_SECONDS) and DRAIN_MARGIN ($DRAIN_MARGIN) must be whole numbers of seconds."

    # One deploy at a time. Commands the script starts inherit the lock, so
    # after a run is killed, a docker command it left running keeps it until
    # that command ends.
    mkdir -p "$STATE_DIR"
    exec 9>>"$STATE_DIR/deploy.lock"
    if ! flock -n 9; then
        die "Another deploy is running, or a command left by an interrupted one is still finishing (lock: $STATE_DIR/deploy.lock). Try again in a minute."
    fi
    rm -rf "$STATE_DIR"/run.*   # left by runs that were killed
    WORK=$(mktemp -d "$STATE_DIR/run.XXXXXX")
    trap 'rm -rf "$WORK"' EXIT
    trap 'on_abort "Interrupted"' INT TERM HUP PIPE
    trap 'on_abort "A command failed (line $LINENO)"' ERR

    refuse_old_leftovers
    # A new proxy in front of the colour that runs: also the way forward when
    # production is down with no proxy (deploy/RUNBOOK.md).
    if [[ "$arg" == --replace-proxy ]]; then
        replace_proxy
        return 0
    fi
    recover_interrupted_migration
    # A proxy that was created for a move behind it but never ran, while the
    # single container still serves the port: the move did not happen.
    if container_exists "$PROXY" && ! container_running "$PROXY" \
            && container_running "$LEGACY" && publishes_prod_port "$LEGACY"; then
        say "Removing $PROXY, which a move behind the proxy created but never started."
        docker rm -f "$PROXY" >/dev/null
    fi
    if container_exists "$PROXY"; then
        local live last_id
        live=$(live_colour)
        # A run killed after the switch but before it recorded the deploy (or a
        # first deploy interrupted once the proxy had started: no DEPLOY_LOG yet).
        last_id=$(tail -n 1 "$DEPLOY_LOG" 2>/dev/null | awk '{print $3}' || true)
        if [[ -n "$live" ]] && container_running "$live" && [[ "$(container_id "$live")" != "$last_id" ]] \
                && proxy_sends_to "$live"; then
            local served
            served=$(release_of "$live")
            say "Caddy serves $live ($served), which an interrupted run did not record; recording it."
            record_deploy "$served" "$live"
            docker tag "$(container_image_id "$live")" "$APP:latest"
        fi
        # The files must say what Caddy does (a run killed before its reload
        # leaves them ahead of it), and the Caddyfile must be this script's.
        if [[ -n "$live" ]] && ! cmp -s <(printf '%s\n' "$CADDYFILE") "$PROXY_DIR/Caddyfile"; then
            write_proxy_config "$live" || die "The proxy's configuration was not changed (deploy/RUNBOOK.md)."
            container_running "$PROXY" && reload_proxy
        elif [[ -n "$live" && "$(file_upstream)" != "$live" ]]; then
            say "$PROXY_DIR/upstream.caddy named $(file_upstream), but Caddy sends traffic to $live; corrected the file."
            write_proxy_config "$live" || die "The proxy's configuration was not changed (deploy/RUNBOOK.md)."
        fi
        # A move behind the proxy that was recorded but interrupted before the
        # single container was renamed.
        if [[ -n "$live" ]] && container_exists "$LEGACY" && ! container_running "$LEGACY"; then
            keep_legacy "$live"
        fi
    fi

    case "$arg" in
        --rollback) rollback ;;
        --rollback-legacy) rollback_legacy ;;
        -*) die "Unknown option $arg; see deploy/deploy.sh --help." ;;
        *) deploy "$arg" ;;
    esac
}

# bash reads a script as it runs it. Everything happens in main, called on the
# last line together with exit, so the whole file has been read before anything
# runs and a `git pull` during a deploy cannot change what runs.
main "$@"; exit
