#!/usr/bin/env bash
# Build, smoke-test and roll out AI Pronunciation Trainer on this host.
#
#   deploy/deploy.sh [git-ref]        # default: origin/main
#
# 1. Builds ai-pronunciation-trainer:<short sha> from the ref.
# 2. Runs it as a staging container on 127.0.0.1:3001, waits until it is
#    healthy and runs deploy/smoke_test.py against it. Production is not
#    touched if anything fails, and the failed image is removed.
# 3. Replaces the production container (port 3000), waits until healthy and
#    smoke-tests it. From the moment the old container is stopped until the
#    new one has passed, any failure or interruption (Ctrl-C, a dropped SSH
#    session) puts the old container back.
# 4. Records the deploy in DEPLOY_LOG and keeps the images of the last
#    KEEP_IMAGES deploys for rollback. Image tags that are not in DEPLOY_LOG
#    (for example ones created by hand) are never removed.
#
# Run it so that it survives a dropped SSH session; see deploy/RUNBOOK.md.
# Needs docker and python3; no sudo.
set -Eeuo pipefail

APP=${APP:-ai-pronunciation-trainer}
REPO_DIR=${REPO_DIR:-"$HOME/ai-pronunciation-trainer"}
REF=${1:-origin/main}
PROD_PORT=${PROD_PORT:-3000}
STAGING_PORT=${STAGING_PORT:-3001}
KEEP_IMAGES=${KEEP_IMAGES:-3}
HEALTH_TIMEOUT=${HEALTH_TIMEOUT:-360}
# One line per successful deploy: "<UTC time> <short sha>", newest last.
DEPLOY_LOG=${DEPLOY_LOG:-"$HOME/.local/state/$APP/deploys.log"}
# Resource limits and log rotation, used for staging and production alike.
RUN_FLAGS=(--memory 9g --memory-swap 9g --pids-limit 512
           --log-opt max-size=10m --log-opt max-file=3
           --tmpfs /tmp:rw,nosuid,size=256m)

log() { printf '\n==> %s\n' "$*"; }
# `docker inspect NAME` would also match an image called NAME:latest.
container_exists() { docker container inspect "$1" >/dev/null 2>&1; }
container_running() { [[ "$(docker container inspect -f '{{.State.Running}}' "$1" 2>/dev/null)" == "true" ]]; }
image_id() { docker image inspect -f '{{.Id}}' "$1" 2>/dev/null || true; }
running_image_id() { docker container inspect -f '{{.Image}}' "$APP" 2>/dev/null || true; }
deployed_before() { [[ -f "$DEPLOY_LOG" ]] && awk -v sha="$1" '$2 == sha { found = 1 } END { exit !found }' "$DEPLOY_LOG"; }

wait_healthy() {
    local name=$1 deadline=$((SECONDS + HEALTH_TIMEOUT)) status
    while (( SECONDS < deadline )); do
        if ! container_running "$name"; then
            echo "$name is not running." >&2
            return 1
        fi
        status=$(docker container inspect -f '{{.State.Health.Status}}' "$name")
        case "$status" in
            healthy) echo "$name is healthy after $((HEALTH_TIMEOUT - deadline + SECONDS)) s"; return 0 ;;
            unhealthy) echo "$name is unhealthy." >&2; return 1 ;;
        esac
        sleep 3
    done
    echo "$name did not become healthy within $HEALTH_TIMEOUT s." >&2
    return 1
}

# A run that was killed between stopping and replacing production (SIGKILL,
# reboot) leaves the old container behind as $APP-previous. Unless the swap
# had already been verified, put it back before doing anything else.
recover_interrupted_deploy() {
    container_exists "$APP-previous" || return 0
    local current last
    current=$(docker container inspect -f '{{.Config.Image}}' "$APP" 2>/dev/null || true)
    last=$( [[ -f "$DEPLOY_LOG" ]] && tail -n 1 "$DEPLOY_LOG" | awk '{print $2}' || true)
    if [[ -n "$last" && "$current" == "$APP:$last" ]] && container_running "$APP"; then
        echo "Removing $APP-previous, left over from the deploy of $last."
        docker rm -f "$APP-previous" >/dev/null
        return 0
    fi
    echo "An earlier deploy was interrupted: $APP-previous exists and $APP ($current) was not verified." >&2
    docker rm -f "$APP" >/dev/null 2>&1 || true
    docker rename "$APP-previous" "$APP"
    docker start "$APP" >/dev/null
    echo "The previous container is running again. Check it (deploy/RUNBOOK.md), then deploy again." >&2
    exit 1
}

remove_failed_image() {
    # An image that failed staging is never used again, unless production runs
    # it or an earlier deploy used it (then it is a rollback candidate).
    local failed_id
    failed_id=$(image_id "$IMAGE")
    [[ -n "$failed_id" && "$failed_id" != "$(running_image_id)" ]] || return 0
    deployed_before "$SHA" && return 0
    docker rmi "$IMAGE" >/dev/null 2>&1 && echo "Removed the failed image $IMAGE." || true
}

prune_images() {
    # Keep the images of the last KEEP_IMAGES distinct deploys and whatever
    # production runs; remove the images of older deploys.
    local keep running sha
    keep=$(awk '{print $2}' "$DEPLOY_LOG" | tac | awk -v n="$KEEP_IMAGES" '!seen[$0]++ { if (count++ < n) print }')
    running=$(running_image_id)
    for sha in $(awk '{print $2}' "$DEPLOY_LOG" | sort -u); do
        grep -qx "$sha" <<<"$keep" && continue
        [[ -n "$(image_id "$APP:$sha")" ]] || continue
        [[ "$(image_id "$APP:$sha")" == "$running" ]] && continue
        docker rmi "$APP:$sha" >/dev/null 2>&1 && echo "removed $APP:$sha" || true
    done
}

recover_interrupted_deploy

cd "$REPO_DIR"
if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
    echo "The checkout in $REPO_DIR has local changes; commit or stash them first." >&2
    exit 1
fi

log "Fetching and checking out $REF"
git fetch origin '+refs/heads/*:refs/remotes/origin/*'
if [[ "$REF" == "origin/main" ]]; then
    git checkout -B main origin/main
else
    git checkout --detach "$REF"
fi
SHA=$(git rev-parse --short=7 HEAD)
IMAGE="$APP:$SHA"

log "Building $IMAGE"
docker build --build-arg GIT_SHA="$SHA" -t "$IMAGE" .

log "Starting staging on 127.0.0.1:$STAGING_PORT"
docker rm -f "$APP-staging" >/dev/null 2>&1 || true
if ! docker run -d --name "$APP-staging" -p "127.0.0.1:$STAGING_PORT:3000" "${RUN_FLAGS[@]}" "$IMAGE" >/dev/null \
        || ! wait_healthy "$APP-staging" \
        || ! python3 deploy/smoke_test.py "http://127.0.0.1:$STAGING_PORT"; then
    docker logs --tail 100 "$APP-staging" || true
    docker rm -f "$APP-staging" >/dev/null 2>&1 || true
    remove_failed_image
    echo "Staging failed; production was not touched." >&2
    exit 1
fi
docker rm -f "$APP-staging" >/dev/null

PREVIOUS_IMAGE=$(docker container inspect -f '{{.Config.Image}}' "$APP" 2>/dev/null || echo none)
HAD_PREVIOUS=0
container_exists "$APP" && HAD_PREVIOUS=1
log "Replacing production: $PREVIOUS_IMAGE -> $IMAGE"

restore_previous() {
    trap '' INT TERM HUP  # finish the restore even if interrupted again
    trap - ERR
    set +e
    echo "The new container failed or the deploy was interrupted; restoring the previous one." >&2
    if (( HAD_PREVIOUS )); then
        if container_exists "$APP-previous"; then
            # The old container was already renamed: drop the new one, rename back.
            docker logs --tail 100 "$APP" 2>&1 | tail -n 100 >&2
            docker rm -f "$APP" >/dev/null 2>&1
            if ! docker rename "$APP-previous" "$APP"; then
                echo "!! Could not rename $APP-previous back. Production is DOWN; see deploy/RUNBOOK.md." >&2
                exit 2
            fi
        fi
        if ! docker start "$APP" >/dev/null; then
            echo "!! Could not start the previous container. Production is DOWN; see deploy/RUNBOOK.md." >&2
            exit 2
        fi
        echo "Previous container ($PREVIOUS_IMAGE) is running again." >&2
    else
        docker logs --tail 100 "$APP" 2>&1 | tail -n 100 >&2
        docker rm -f "$APP" >/dev/null 2>&1
        echo "There was no previous container to restore." >&2
    fi
    exit 1
}
trap restore_previous ERR INT TERM HUP

if (( HAD_PREVIOUS )); then
    docker stop -t 40 "$APP" >/dev/null
    docker rename "$APP" "$APP-previous"
fi
docker run -d --name "$APP" --restart unless-stopped -p "$PROD_PORT:3000" "${RUN_FLAGS[@]}" "$IMAGE" >/dev/null
if ! wait_healthy "$APP" || ! python3 deploy/smoke_test.py "http://127.0.0.1:$PROD_PORT"; then
    restore_previous
fi
trap - ERR INT TERM HUP

mkdir -p "$(dirname "$DEPLOY_LOG")"
printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$SHA" >> "$DEPLOY_LOG"
docker rm -f "$APP-previous" >/dev/null 2>&1 || true
docker tag "$IMAGE" "$APP:latest"
log "Deployed $IMAGE"

log "Keeping the images of the last $KEEP_IMAGES deploys"
prune_images || echo "Image cleanup failed; the deploy itself succeeded." >&2
docker images "$APP"
