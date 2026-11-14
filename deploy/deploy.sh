#!/usr/bin/env bash
# Build, check and roll out AI Pronunciation Trainer on this host without
# dropping requests.
#
#   deploy/deploy.sh [git-ref]        build and deploy a commit (default: origin/main)
#   deploy/deploy.sh --rollback       make the previous release live again
#   deploy/deploy.sh --status         show what is live
#   deploy/deploy.sh --replace-proxy  recreate the proxy from CADDY_IMAGE (about 1 s of downtime)
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
#    checkout is never changed and local edits are never built;
# 2. starts it in the idle colour, waits until it is healthy and runs that
#    commit's deploy/smoke_test.py against it. Production is not touched if
#    anything fails, and the failed image is removed;
# 3. points Caddy at the new colour with a graceful reload (requests in flight
#    finish on the old colour) and smoke-tests it through the proxy; if that
#    fails, Caddy is pointed back;
# 4. records the deploy in DEPLOY_LOG, lets the old colour finish its requests,
#    stops it, and keeps the images of the last KEEP_IMAGES deploys. Image tags
#    that are not in DEPLOY_LOG (for example ones made by hand) are never removed.
#
# The first run on a host that still has the single container of earlier
# versions ($APP, publishing PROD_PORT) moves it behind the proxy. It keeps
# serving until the new colour has passed its checks; then it is stopped and
# the proxy takes over its port, which interrupts service for a few seconds,
# once. It is kept, stopped, as $APP-legacy, and --rollback can bring it back.
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
# gunicorn finishes the requests it is serving within 30 s (gunicorn.conf.py).
STOP_TIMEOUT=${STOP_TIMEOUT:-40}
# After the switch, the old colour gets this long before it is told to stop.
DRAIN_SECONDS=${DRAIN_SECONDS:-5}
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
PROXY_FLAGS=(--memory 256m --pids-limit 256 --read-only
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
}

:3000 {
	request_body {
		max_size 5MB
	}
	reverse_proxy {
		import upstream.caddy
		# If the live colour does not accept connections (a restart), keep
		# trying for a while before answering 502.
		lb_try_duration 10s
		lb_try_interval 250ms
		transport http {
			response_header_timeout 125s
		}
	}
}
EOF

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
# True if the container publishes port 3000 as host port PROD_PORT.
publishes_prod_port() { docker port "$1" 3000/tcp 2>/dev/null | grep -qE ":$PROD_PORT\$"; }
port_of() { if [[ $1 == "$BLUE" ]]; then echo "$BLUE_PORT"; else echo "$GREEN_PORT"; fi; }
other_colour() { if [[ $1 == "$BLUE" ]]; then echo "$GREEN"; else echo "$BLUE"; fi; }
http_ok() { curl -fsS -o /dev/null -m "${2:-5}" "$1" 2>/dev/null; }

# The colour Caddy is configured to send traffic to (empty if none).
live_colour() {
    local target
    target=$(awk '$1 == "to" { sub(/:3000$/, "", $2); print $2 }' "$PROXY_DIR/upstream.caddy" 2>/dev/null || true)
    [[ $target == "$BLUE" || $target == "$GREEN" ]] && echo "$target" || true
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

# smoke <base url>: the smoke test of the commit being deployed.
smoke() { python3 "$WORK/smoke_test.py" "$1"; }

remove_container() {
    container_exists "$1" || return 0
    container_running "$1" && docker stop -t "$STOP_TIMEOUT" "$1" >/dev/null
    docker rm -f "$1" >/dev/null
}

ensure_network() {
    docker network inspect "$NETWORK" >/dev/null 2>&1 || docker network create "$NETWORK" >/dev/null
}

write_proxy_config() {  # write_proxy_config <colour>
    mkdir -p "$PROXY_DIR"
    printf '%s\n' "$CADDYFILE" > "$PROXY_DIR/Caddyfile.new"
    printf 'to %s:3000\n' "$1" > "$PROXY_DIR/upstream.caddy.new"
    # Replace the files, never edit them in place: the proxy reads them through
    # a mount of the directory.
    mv -f "$PROXY_DIR/Caddyfile.new" "$PROXY_DIR/Caddyfile"
    mv -f "$PROXY_DIR/upstream.caddy.new" "$PROXY_DIR/upstream.caddy"
}

reload_proxy() {
    docker exec "$PROXY" caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile 2>&1 | tail -n 3 >&2
}

# True if Caddy's running configuration sends traffic to <colour>.
proxy_sends_to() {
    docker exec "$PROXY" wget -qO- http://127.0.0.1:2019/config/apps/http/servers 2>/dev/null \
        | grep -q "\"dial\":\"$1:3000\""
}

# docker releases a stopped container's port a moment after `docker stop` returns.
start_proxy() {
    local try
    for try in 1 2 3 4 5; do
        docker start "$PROXY" >/dev/null 2>&1 && return 0
        sleep 0.5
    done
    docker start "$PROXY" >/dev/null
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

# Put the single container back on PROD_PORT after a failed or interrupted move
# behind the proxy. Called with traps and errexit off.
restore_legacy() {
    say "Putting $LEGACY back on port $PROD_PORT."
    docker rm -f "$PROXY" >/dev/null 2>&1
    if ! container_exists "$LEGACY" && container_exists "$LEGACY_KEPT"; then
        docker rename "$LEGACY_KEPT" "$LEGACY"
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
    # to remove an image a container (running or stopped) still uses.
    local keep sha
    keep=$(awk '{print $2}' "$DEPLOY_LOG" | tac | awk -v n="$KEEP_IMAGES" '!seen[$0]++ { if (count++ < n) print }')
    for sha in $(awk '{print $2}' "$DEPLOY_LOG" | sort -u); do
        grep -qx "$sha" <<<"$keep" && continue
        [[ -n "$(image_id "$APP:$sha")" ]] || continue
        docker rmi "$APP:$sha" >/dev/null 2>&1 && echo "removed $APP:$sha" || true
    done
}

record_deploy() {  # record_deploy <sha> <container>
    printf '%s %s %s\n' "$(now)" "$1" "$(container_id "$2")" >> "$DEPLOY_LOG"
}

# ------------------------------------------------------------------ interruptions

PHASE=prepare   # prepare, staging, switching, migrating, live
STAGED=         # container started by this run
SWITCHED_FROM=  # live colour before the switch
MIGRATED=0      # this run moved the single container behind the proxy

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
    critical_section
    say ""
    say "!! $1 while $PHASE."
    case "$PHASE" in
        staging)
            [[ -n "$STAGED" ]] && { docker logs --tail 50 "$STAGED" 2>&1 | tail -n 50 >&2; docker rm -f "$STAGED" >/dev/null 2>&1; }
            remove_failed_image
            say "Production was not touched." ;;
        switching)
            if [[ -n "$SWITCHED_FROM" ]] && container_running "$SWITCHED_FROM"; then
                write_proxy_config "$SWITCHED_FROM" && reload_proxy
                say "The proxy sends traffic to $SWITCHED_FROM again."
            fi
            if [[ -n "$STAGED" ]]; then
                # Let the requests it took before the switch back finish.
                sleep "$DRAIN_SECONDS"
                docker stop -t "$STOP_TIMEOUT" "$STAGED" >/dev/null 2>&1
                docker rm -f "$STAGED" >/dev/null 2>&1
            fi
            remove_failed_image ;;
        migrating)
            restore_legacy || exit 2
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
        sha=$(container_image "$live"); sha=${sha##*:}
        record_deploy "$sha" "$live"
        rm -f "$MIGRATION_MARK"
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
    container_running "$PROXY" && return 0
    say "$PROXY is not running; starting it."
    if ! start_proxy || ! wait_http "http://127.0.0.1:$PROD_PORT/" 30; then
        die "!! Could not start $PROXY. Production is DOWN; see deploy/RUNBOOK.md." 2
    fi
}

# ------------------------------------------------------------------ steps

prepare_commit() {  # prepare_commit <ref>: sets COMMIT, SHA, IMAGE and WORK/smoke_test.py
    local ref=$1
    log "Fetching $ref"
    git -C "$REPO_DIR" fetch --quiet origin '+refs/heads/*:refs/remotes/origin/*'
    COMMIT=$(git -C "$REPO_DIR" rev-parse --verify -q "$ref^{commit}" || true)
    [[ -n "$COMMIT" ]] || die "Unknown ref $ref (after the fetch, branches are origin/<name>)."
    if [[ "${ALLOW_UNPUSHED:-0}" != 1 && -z "$(git -C "$REPO_DIR" branch -r --contains "$COMMIT" 2>/dev/null || true)" ]]; then
        die "$ref is not on any branch of origin. Push it first (CI checks every pushed commit)."
    fi
    # Versions from before deploy.sh have no smoke test, and their image no
    # health check; they are rolled back by hand, see deploy/RUNBOOK.md.
    git -C "$REPO_DIR" show "$COMMIT:deploy/smoke_test.py" > "$WORK/smoke_test.py" 2>/dev/null \
        || die "$ref has no deploy/smoke_test.py, so deploy.sh cannot deploy it. To go back to a version from before deploy.sh, see deploy/RUNBOOK.md."
    SHA=$(git -C "$REPO_DIR" rev-parse --short=7 "$COMMIT")
    IMAGE="$APP:$SHA"
}

build_image() {
    log "Building $IMAGE"
    git -C "$REPO_DIR" archive --format=tar "$COMMIT" \
        | docker build --build-arg GIT_SHA="$SHA" \
            --build-arg GIT_DATE="$(git -C "$REPO_DIR" show -s --format=%cI "$COMMIT")" \
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
        echo "Removing $target ($(container_image "$target")), the release before the live one."
        remove_container "$target"
    fi
    ensure_network
    STAGED=$target
    docker run -d --name "$target" --network "$NETWORK" --restart unless-stopped \
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
    write_proxy_config "$target"
    reload_proxy
    if ! proxy_sends_to "$target"; then
        on_abort "Caddy did not take the new configuration"
    fi
    if ! smoke "http://127.0.0.1:$PROD_PORT"; then
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
    write_proxy_config "$target"
    docker rm -f "$PROXY" >/dev/null 2>&1 || true
    create_proxy
    PHASE=migrating
    container_id "$LEGACY" > "$MIGRATION_MARK"
    if container_running "$LEGACY"; then
        docker stop -t "$STOP_TIMEOUT" "$LEGACY" >/dev/null
    fi
    stopped_at=$(date +%s.%N)
    if ! start_proxy || ! wait_http "http://127.0.0.1:$PROD_PORT/" 30; then
        on_abort "The proxy did not answer on port $PROD_PORT"
    fi
    echo "Port $PROD_PORT was unavailable for $(awk -v a="$stopped_at" -v b="$(date +%s.%N)" 'BEGIN { printf "%.1f", b - a }') s after $LEGACY stopped."
    if ! smoke "http://127.0.0.1:$PROD_PORT"; then
        on_abort "The smoke test through the proxy failed"
    fi
    MIGRATED=1
}

# After a move behind the proxy has been recorded: keep the single container,
# stopped, for --rollback.
keep_legacy() {  # keep_legacy <live colour>
    container_exists "$LEGACY" || return 0
    if container_exists "$LEGACY_KEPT"; then
        docker rm -f "$LEGACY_KEPT" >/dev/null 2>&1 || true
    fi
    docker rename "$LEGACY" "$LEGACY_KEPT" || say "Could not rename $LEGACY to $LEGACY_KEPT; it is stopped."
    # A colour left from before a rollback to the single container is older than
    # it; --rollback goes to the single container instead.
    docker rm -f "$(other_colour "$1")" >/dev/null 2>&1 || true
}

# First deploy on a host with neither the proxy nor the single container.
start_proxy_fresh() {  # start_proxy_fresh <target>
    local target=$1
    log "Starting the proxy on port $PROD_PORT"
    PHASE=switching
    write_proxy_config "$target"
    docker rm -f "$PROXY" >/dev/null 2>&1 || true
    create_proxy
    if ! start_proxy || ! wait_http "http://127.0.0.1:$PROD_PORT/" 30 || ! smoke "http://127.0.0.1:$PROD_PORT"; then
        docker rm -f "$PROXY" >/dev/null 2>&1
        on_abort "The proxy did not serve the new release"
    fi
}

# Stop the old colour once its requests are done; keep it for --rollback.
retire() {  # retire <container>
    [[ -n "$1" ]] && container_running "$1" || return 0
    log "Stopping $1 (kept for deploy/deploy.sh --rollback)"
    sleep "$DRAIN_SECONDS"
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

# Recreate the proxy (a new CADDY_IMAGE): port 3000 is unavailable for about a second.
replace_proxy() {
    local live
    live=$(live_colour)
    [[ -n "$live" ]] && container_running "$live" || die "No live colour is running; nothing to put the proxy in front of."
    log "Replacing $PROXY ($(container_image "$PROXY")) with $CADDY_IMAGE in front of $live"
    [[ -n "$(image_id "$CADDY_IMAGE")" ]] || docker pull --quiet "$CADDY_IMAGE" >/dev/null
    write_proxy_config "$live"
    critical_section
    docker rm -f "$PROXY" >/dev/null 2>&1
    if ! create_proxy || ! start_proxy || ! wait_http "http://127.0.0.1:$PROD_PORT/" 30; then
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
        sha=${image##*:}
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
    if container_exists "$LEGACY_KEPT"; then
        log "Rolling back to the single container from before the proxy ($(container_image "$LEGACY_KEPT"))"
        say "Port $PROD_PORT is unavailable for a few seconds."
        critical_section
        docker rename "$LEGACY_KEPT" "$LEGACY"
        container_id "$LEGACY" > "$MIGRATION_MARK"
        restore_legacy || exit 2
        docker stop -t "$STOP_TIMEOUT" "$live" >/dev/null 2>&1 || true
        sha=$(container_image "$LEGACY"); sha=${sha##*:}
        record_deploy "$sha" "$LEGACY"
        log "$LEGACY is live again. The colours are stopped; the next deploy moves it behind the proxy again."
        return 0
    fi
    die "There is no previous release to roll back to. Deploy an older commit instead: deploy/deploy.sh <sha>"
}

status() {
    local name state live
    live=$(live_colour)
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
    recover_interrupted_migration
    if container_exists "$PROXY"; then
        local live
        live=$(live_colour)
        # Keep the proxy's configuration in step with this script.
        if [[ -n "$live" ]] && ! cmp -s <(printf '%s\n' "$CADDYFILE") "$PROXY_DIR/Caddyfile"; then
            write_proxy_config "$live"
            container_running "$PROXY" && reload_proxy
        fi
        # A move behind the proxy that was recorded but interrupted before the
        # single container was renamed.
        if [[ -n "$live" ]] && container_exists "$LEGACY" && ! container_running "$LEGACY"; then
            keep_legacy "$live"
        fi
    fi

    case "$arg" in
        --rollback) rollback ;;
        --replace-proxy) replace_proxy ;;
        -*) die "Unknown option $arg; see deploy/deploy.sh --help." ;;
        *) deploy "$arg" ;;
    esac
}

# bash reads a script as it runs it. Everything happens in main, called on the
# last line together with exit, so the whole file has been read before anything
# runs and a `git pull` during a deploy cannot change what runs.
main "$@"; exit
