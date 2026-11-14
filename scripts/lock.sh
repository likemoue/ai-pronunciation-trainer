#!/usr/bin/env bash
# Pin every dependency, by version and sha256, for the Docker image and CI
# (CPython 3.12 on Linux x86_64). Needs uv (https://docs.astral.sh/uv/).
#
#   scripts/lock.sh             re-resolve after editing requirements*.in; other pins stay as they are
#   scripts/lock.sh --upgrade   move every package to its newest release that is at least 7 days old
#   scripts/lock.sh --check     fail if requirements*.lock do not match requirements*.in (CI)
#
# Only releases uploaded before a cut-off date are considered. --upgrade sets it
# to 7 days ago (or to LOCK_DATE, e.g. LOCK_DATE=2026-11-07); otherwise the date
# in requirements.lock's header is reused, so the same inputs always resolve to
# the same pins. torch comes from the PyTorch CPU index, everything else from
# PyPI; installs need both indexes:
#   pip install --require-hashes -r requirements.lock \
#       --index-url https://pypi.org/simple --extra-index-url https://download.pytorch.org/whl/cpu
#
# A security fix younger than 7 days: add --exclude-newer-package NAME=DATE to
# the uv command below for that package only, and say why in the commit.
set -euo pipefail
cd "$(dirname "$0")/.."

mode=${1:-}
case "$mode" in
    ''|--upgrade|--check) ;;
    *) echo "usage: scripts/lock.sh [--upgrade | --check]" >&2; exit 2 ;;
esac

if [[ $mode == --upgrade || ! -f requirements.lock ]]; then
    cutoff=$(date -u -d "${LOCK_DATE:-7 days ago}" +%Y-%m-%dT00:00:00Z)
else
    cutoff=$(grep -oE -- '--exclude-newer [0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:]+Z' requirements.lock | head -n 1 | cut -d' ' -f2)
    [[ -n $cutoff ]] || { echo "No --exclude-newer date in the header of requirements.lock." >&2; exit 1; }
fi

compile() {  # compile <input> <output> [extra uv args...]
    local input=$1 output=$2
    shift 2
    uv pip compile "$input" -o "$output" --quiet \
        --generate-hashes --python-version 3.12 --python-platform x86_64-manylinux_2_39 \
        --torch-backend cpu --emit-index-annotation \
        --exclude-newer "$cutoff" "$@"
}

lock_all() {
    local upgrade=()
    [[ $mode == --upgrade ]] && upgrade=(--upgrade)
    compile requirements.in requirements.lock "${upgrade[@]}"
    compile requirements-dev.in requirements-dev.lock "${upgrade[@]}"
}

if [[ $mode == --check ]]; then
    work=$(mktemp -d)
    trap 'rm -rf "$work"' EXIT
    cp requirements.in requirements-dev.in requirements.lock requirements-dev.lock "$work/"
    (cd "$work" && lock_all)
    status=0
    for file in requirements.lock requirements-dev.lock; do
        if ! diff -u --strip-trailing-cr "$file" "$work/$file"; then
            echo "$file is out of date: run scripts/lock.sh and commit the result." >&2
            status=1
        fi
    done
    exit $status
fi

lock_all
echo "Locked with packages uploaded before $cutoff:"
grep -cE '^[A-Za-z0-9_.-]+==' requirements.lock requirements-dev.lock
