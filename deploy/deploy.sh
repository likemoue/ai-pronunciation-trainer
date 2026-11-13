#!/usr/bin/env bash
# Build, smoke-test and roll out AI Pronunciation Trainer on this host.
#
#   deploy/deploy.sh [git-ref]        # default: origin/main
#
# 1. Builds ai-pronunciation-trainer:<short sha> from the ref.
# 2. Runs it as a staging container on 127.0.0.1:3001, waits until it is
#    healthy and runs deploy/smoke_test.py against it. Production is not
#    touched if anything fails.
# 3. Replaces the production container (port 3000), waits until healthy and
#    smoke-tests it; on failure the previous container is started again.
# 4. Keeps the newest KEEP_IMAGES sha-tagged images for rollback.
#
# Needs docker and python3; no sudo. See deploy/RUNBOOK.md.
set -euo pipefail

APP=${APP:-ai-pronunciation-trainer}
REPO_DIR=${REPO_DIR:-"$HOME/ai-pronunciation-trainer"}
REF=${1:-origin/main}
PROD_PORT=${PROD_PORT:-3000}
STAGING_PORT=${STAGING_PORT:-3001}
KEEP_IMAGES=${KEEP_IMAGES:-3}
HEALTH_TIMEOUT=${HEALTH_TIMEOUT:-360}
# Resource limits and log rotation, used for staging and production alike.
RUN_FLAGS=(--memory 9g --memory-swap 9g --pids-limit 512
           --log-opt max-size=10m --log-opt max-file=3
           --tmpfs /tmp:rw,nosuid,size=256m)

log() { printf '\n==> %s\n' "$*"; }

wait_healthy() {
    local name=$1 deadline=$((SECONDS + HEALTH_TIMEOUT)) status
    while (( SECONDS < deadline )); do
        if [[ "$(docker inspect -f '{{.State.Running}}' "$name" 2>/dev/null)" != "true" ]]; then
            echo "$name is not running." >&2
            return 1
        fi
        status=$(docker inspect -f '{{.State.Health.Status}}' "$name")
        case "$status" in
            healthy) echo "$name is healthy after $((HEALTH_TIMEOUT - deadline + SECONDS)) s"; return 0 ;;
            unhealthy) echo "$name is unhealthy." >&2; return 1 ;;
        esac
        sleep 3
    done
    echo "$name did not become healthy within $HEALTH_TIMEOUT s." >&2
    return 1
}

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
docker run -d --name "$APP-staging" -p "127.0.0.1:$STAGING_PORT:3000" "${RUN_FLAGS[@]}" "$IMAGE" >/dev/null
if ! wait_healthy "$APP-staging" || ! python3 deploy/smoke_test.py "http://127.0.0.1:$STAGING_PORT"; then
    docker logs --tail 100 "$APP-staging" || true
    docker rm -f "$APP-staging" >/dev/null 2>&1 || true
    echo "Staging failed; production was not touched." >&2
    exit 1
fi
docker rm -f "$APP-staging" >/dev/null

PREVIOUS_IMAGE=$(docker inspect -f '{{.Config.Image}}' "$APP" 2>/dev/null || echo none)
log "Replacing production: $PREVIOUS_IMAGE -> $IMAGE"
docker rm -f "$APP-previous" >/dev/null 2>&1 || true
if docker inspect "$APP" >/dev/null 2>&1; then
    docker stop -t 40 "$APP" >/dev/null
    docker rename "$APP" "$APP-previous"
fi
docker run -d --name "$APP" --restart unless-stopped -p "$PROD_PORT:3000" "${RUN_FLAGS[@]}" "$IMAGE" >/dev/null

if wait_healthy "$APP" && python3 deploy/smoke_test.py "http://127.0.0.1:$PROD_PORT"; then
    docker rm "$APP-previous" >/dev/null 2>&1 || true
    docker tag "$IMAGE" "$APP:latest"
    log "Deployed $IMAGE"
else
    echo "The new container failed; restoring the previous one." >&2
    docker logs --tail 100 "$APP" || true
    docker rm -f "$APP" >/dev/null 2>&1 || true
    if docker inspect "$APP-previous" >/dev/null 2>&1; then
        docker rename "$APP-previous" "$APP"
        docker start "$APP" >/dev/null
        echo "Previous container ($PREVIOUS_IMAGE) restarted." >&2
    fi
    exit 1
fi

log "Keeping the newest $KEEP_IMAGES images"
docker images "$APP" --format '{{.Tag}}' | grep -E '^[0-9a-f]{7}$' | tail -n +$((KEEP_IMAGES + 1)) \
    | while read -r tag; do docker rmi "$APP:$tag" >/dev/null 2>&1 && echo "removed $APP:$tag" || true; done
docker images "$APP"
