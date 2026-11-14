#!/usr/bin/env bash
# Run the fault-injection harness for deploy/deploy.sh (deploy/test/README.md).
#
#   deploy/test/run.sh                                  every scenario, in three lanes
#   deploy/test/run.sh 1:b1_lifecycle 2:b3_failures,b7_misc   chosen scenarios: <lane>:<scenario>[,<scenario>...]
#
# Needs docker; works on Linux and in Git Bash with Docker Desktop. Results go to
# deploy/test/out/ (or OUT_DIR): <scenario>.txt has every check, runN.log what
# deploy.sh printed, runN.trace every docker command it ran. Exits 1 if a check failed.
set -euo pipefail
export MSYS_NO_PATHCONV=1   # Git Bash: pass paths to docker unchanged

here=$(cd "$(dirname "$0")" && pwd)
repo=$(cd "$here/../.." && pwd)
out=${OUT_DIR:-"$here/out"}
host_path() { if command -v cygpath >/dev/null 2>&1; then cygpath -m "$1"; else printf '%s\n' "$1"; fi; }

specs=("$@")
if (( ${#specs[@]} == 0 )); then
    specs=("1:b4_signals" "2:b6_migration,b2_legacy" "3:b5_kill,b1_lifecycle,b3_failures,b7_misc")
fi

mkdir -p "$out"
rm -f "$out"/*
docker build -q -t aipt-deploy-harness "$(host_path "$here/harness")" >/dev/null
docker rm -f aipt-deploy-harness >/dev/null 2>&1 || true
# --network host: deploy.sh checks 127.0.0.1:<port>, published by the daemon.
# /tmp/aipt-bg: deploy.sh's state directories, which it bind-mounts into the
# proxy, so the daemon must see them at the same path (a path in the Docker
# Desktop VM on Windows and macOS).
docker run -d --init --name aipt-deploy-harness --network host \
    -v /var/run/docker.sock:/var/run/docker.sock -v /tmp/aipt-bg:/tmp/aipt-bg \
    -v "$(host_path "$here/harness"):/h:ro" -v "$(host_path "$repo/deploy"):/deploy:ro" \
    -v "$(host_path "$out"):/out" aipt-deploy-harness sleep infinity >/dev/null

cleanup() {
    docker exec aipt-deploy-harness bash -c '
        for app in aipt-bg1 aipt-bg2 aipt-bg3; do
            docker ps -aq --filter "name=^/$app" | xargs -r docker rm -f >/dev/null
            docker images "$app" --format "{{.Repository}}:{{.Tag}}" | xargs -r docker rmi >/dev/null 2>&1 || true
            docker network rm "$app-net" >/dev/null 2>&1 || true
        done
        rm -rf /tmp/aipt-bg/lane*' >/dev/null 2>&1 || true
    docker rm -f aipt-deploy-harness >/dev/null 2>&1 || true
}
trap cleanup EXIT

run_lane() {  # run_lane <lane> <scenario>[,<scenario>...]
    local scenario
    for scenario in ${2//,/ }; do
        docker exec -e LANE="$1" -e SCEN="$scenario" aipt-deploy-harness bash "/h/$scenario.sh" \
            > "$out/${scenario}_console.txt" 2>&1 || true
        printf '%-14s lane %s: %3d passed, %d failed\n' "$scenario" "$1" \
            "$(grep -c '  PASS' "$out/$scenario.txt" || true)" "$(grep -c '  FAIL' "$out/$scenario.txt" || true)"
    done
}

for spec in "${specs[@]}"; do
    run_lane "${spec%%:*}" "${spec#*:}" &
done
wait

if grep -h '  FAIL' "$out"/*.txt 2>/dev/null; then
    echo "The harness found failures; see $out." >&2
    exit 1
fi
echo "Every check passed."
