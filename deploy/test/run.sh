#!/usr/bin/env bash
# Run the fault-injection harness for deploy/deploy.sh (deploy/test/README.md).
#
#   deploy/test/run.sh                                  every scenario, in three lanes
#   deploy/test/run.sh 1:b1_lifecycle 2:b3_failures,b7_misc   chosen scenarios: <lane>:<scenario>[,<scenario>...]
#
# Needs docker; works on Linux and in Git Bash with Docker Desktop. Results go to
# deploy/test/out/ (or OUT_DIR): <scenario>.txt has every check, runN.log what
# deploy.sh printed, runN.trace every docker command it ran. Exits 1 if a check
# failed or a scenario did not run to its end, 2 if the harness could not start.
set -euo pipefail
export MSYS_NO_PATHCONV=1   # Git Bash: pass paths to docker unchanged

here=$(cd "$(dirname "$0")" && pwd)
repo=$(cd "$here/../.." && pwd)
out=${OUT_DIR:-"$here/out"}
# docker -v takes a relative source for the name of a volume: make it a path.
[[ "$out" == /* || "$out" =~ ^[A-Za-z]:[/\\] ]] || out="$PWD/$out"
host_path() { if command -v cygpath >/dev/null 2>&1; then cygpath -m "$1"; else printf '%s\n' "$1"; fi; }
die() { echo "run.sh: $*" >&2; exit 2; }
CTR=aipt-deploy-harness   # the harness container; each lane has its own app name (harness/lib.sh)

# The fewest checks each scenario makes when it runs to its end (some depend on the
# outcome of a case); fewer means that part of it was skipped.
declare -A MIN_CHECKS=([b1_lifecycle]=33 [b2_legacy]=23 [b3_failures]=89 [b4_signals]=169
                       [b5_kill]=74 [b6_migration]=234 [b7_misc]=31 [b8_gates]=42)

scenarios=()
for f in "$here"/harness/b[0-9]*_*.sh; do f=${f##*/}; scenarios+=("${f%.sh}"); done

specs=("$@")
if (( ${#specs[@]} == 0 )); then
    specs=("1:b4_signals,b8_gates" "2:b6_migration,b2_legacy" "3:b5_kill,b1_lifecycle,b3_failures,b7_misc")
fi
# Check every argument before anything is started or removed: a scenario without its
# lane would have no app name to limit its clean-up to.
lanes=() chosen=()
for spec in "${specs[@]}"; do
    [[ $spec =~ ^([123]):([a-z0-9_]+(,[a-z0-9_]+)*)$ ]] \
        || die "'$spec' is not <lane>:<scenario>[,<scenario>...] with lane 1, 2 or 3, for example 1:b1_lifecycle."
    lane=${BASH_REMATCH[1]} list=${BASH_REMATCH[2]}
    [[ " ${lanes[*]} " != *" $lane "* ]] \
        || die "Lane $lane is given twice; give it its scenarios in one argument, for example $lane:b1_lifecycle,b3_failures."
    lanes+=("$lane")
    for s in ${list//,/ }; do
        [[ " ${scenarios[*]} " == *" $s "* ]] || die "There is no scenario $s. The scenarios: ${scenarios[*]}."
        [[ " ${chosen[*]} " != *" $s "* ]] || die "Scenario $s is given twice."
        chosen+=("$s")
    done
done

# deploy.sh runs git, curl and docker through these (a checkout made on Windows may not
# have the executable bit: git add --chmod=+x).
for f in "$here"/harness/bin/*; do
    [[ -x $f ]] || die "${f#"$repo/"} is not executable."
done

mkdir -p "$out"
docker build -q -t "$CTR" "$(host_path "$here/harness")" >/dev/null || die "Could not build the harness image."

# One harness at a time on a docker daemon, as they would share the names above and
# /tmp/aipt-bg. The harness container is the lock: its label names the run.sh that
# created it, so a container left by a run.sh that was killed is replaced, and one
# that is in use is never touched.
owner="$(uname -n) $$"
create_harness() {
    # --network host: deploy.sh checks 127.0.0.1:<port>, published by the daemon.
    # /tmp/aipt-bg: deploy.sh's state directories, which it bind-mounts into the
    # proxy, so the daemon must see them at the same path (a path in the Docker
    # Desktop VM on Windows and macOS).
    docker create --name "$CTR" --label "aipt.harness.owner=$owner" --init --network host \
        -v /var/run/docker.sock:/var/run/docker.sock -v /tmp/aipt-bg:/tmp/aipt-bg \
        -v "$(host_path "$here/harness"):/h:ro" -v "$(host_path "$repo/deploy"):/deploy:ro" \
        -v "$(host_path "$out"):/out" "$CTR" sleep infinity >/dev/null
}
if ! error=$(create_harness 2>&1); then
    holder=$(docker container inspect -f '{{.Id}} {{index .Config.Labels "aipt.harness.owner"}}' "$CTR" 2>/dev/null) \
        || die "Could not create the container $CTR: $error"
    read -r stale host pid <<<"$holder"
    if [[ $host == "$(uname -n)" && $pid =~ ^[0-9]+$ ]] && ! ps -p "$pid" >/dev/null 2>&1; then
        echo "Removing $CTR, left by run.sh $pid, which no longer runs."
        docker rm -f "$stale" >/dev/null
        error=$(create_harness 2>&1) || die "Could not create the container $CTR: $error"
    else
        die "Another run of the harness (run.sh ${pid:-of an older version} on ${host:-?}) uses this docker daemon: $CTR exists. Wait for it; if no run.sh is running, remove it with: docker rm -f $CTR"
    fi
fi
# From here on the container is used by its id: lanes left running by a run.sh that
# was killed then fail, rather than run in the container of the next run.sh.
id=$(docker container inspect -f '{{.Id}}' "$CTR")

cleanup() {
    docker exec "$id" bash -c '
        for app in aipt-bg1 aipt-bg2 aipt-bg3; do
            docker ps -aq --filter "name=^/$app" | xargs -r docker rm -f >/dev/null
            docker images "$app" --format "{{.Repository}}:{{.Tag}}" | xargs -r docker rmi >/dev/null 2>&1 || true
            docker network rm "$app-net" >/dev/null 2>&1 || true
        done
        rm -rf /tmp/aipt-bg/lane*' >/dev/null 2>&1 || true
    docker rm -f "$id" >/dev/null 2>&1 || true
}
trap cleanup EXIT
docker start "$id" >/dev/null || die "Could not start the container $CTR."

# The harness's own earlier results; anything else in OUT_DIR stays.
for s in "${scenarios[@]}"; do
    rm -f "$out/$s".* "$out/${s}_console.txt"
done

# verdict <scenario> <lane> <exit status>: one line for the scenario. Passes only if it ran
# to its end (its .txt ends with FAILS=0), exited 0, and made all its checks.
verdict() {
    local s=$1 txt="$out/$1.txt" passed=0 failed=0 last='' problems=() note='' p
    if [[ -f $txt ]]; then
        passed=$(grep -c '^  PASS ' "$txt" || true)
        failed=$(grep -c '^  FAIL ' "$txt" || true)
        last=$(tail -n 1 "$txt")
    fi
    [[ $last =~ ^FAILS=[0-9]+$ ]] || problems+=("it did not run to its end")
    # end_scenario (lib.sh) exits 1 after a failed check.
    [[ $3 == 0 || ( $3 == 1 && $last =~ ^FAILS=[1-9] ) ]] || problems+=("exit status $3")
    (( passed + failed >= ${MIN_CHECKS[$s]:-1} )) || problems+=("it makes at least ${MIN_CHECKS[$s]:-1} checks")
    for p in "${problems[@]}"; do note+="; $p"; done
    printf '%-14s lane %s: %3d passed, %d failed%s\n' "$s" "$2" "$passed" "$failed" "$note"
    [[ $last == FAILS=0 && $failed == 0 && -z $note ]]
}

run_lane() {  # run_lane <lane> <scenario>...: one after another; fails if any of them did
    local lane=$1 s rc result=0
    shift
    for s in "$@"; do
        rc=0
        docker exec -e LANE="$lane" -e SCEN="$s" "$id" bash "/h/$s.sh" > "$out/${s}_console.txt" 2>&1 || rc=$?
        verdict "$s" "$lane" "$rc" || result=1
    done
    return "$result"
}

pids=()
for spec in "${specs[@]}"; do
    list=${spec#*:}
    # shellcheck disable=SC2086  # one argument per scenario
    run_lane "${spec%%:*}" ${list//,/ } &
    pids+=("$!")
done
result=0
for pid in "${pids[@]}"; do
    wait "$pid" || result=1
done

if (( result )); then
    for s in "${chosen[@]}"; do grep -h '^  FAIL ' "$out/$s.txt" 2>/dev/null || true; done
    echo "The harness found failures, or a scenario did not run to its end; see $out." >&2
    exit 1
fi
echo "Every check passed."
