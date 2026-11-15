#!/usr/bin/env bash
# Install lock files with pip so that every file is checked against its sha256.
#
#   scripts/pip_install_locked.sh <python> <lock file>...
#
# To build a package that has no wheel (eng-to-ipa), pip normally downloads a
# build backend (setuptools) without checking any hash. Here the setuptools
# pinned in the first lock file is installed first, with its hashes, and the
# packages are built with it.
#
# Indexes come from PIP_INDEX_URL and PIP_EXTRA_INDEX_URL: requirements.lock
# needs https://pypi.org/simple and https://download.pytorch.org/whl/cpu (torch).
set -euo pipefail

python=$1
shift
backend=$(mktemp)
trap 'rm -f "$backend"' EXIT
# The setuptools entry: its requirement line and the hash lines that follow it.
# A carriage return is dropped first, so a lock with CRLF line endings (a
# Windows checkout, or a `git archive` made from one) keeps its hash lines.
awk '{ sub(/\r$/, "") } /^setuptools==/ { keep = 1 } keep { print } keep && !/\\$/ { exit }' "$1" > "$backend"
grep -q -- '--hash=sha256:' "$backend" || { echo "No setuptools with hashes in $1." >&2; exit 1; }
pip --python "$python" install --require-hashes --no-deps -r "$backend"

locks=()
for lock in "$@"; do
    locks+=(-r "$lock")
done
pip --python "$python" install --require-hashes --no-build-isolation "${locks[@]}"
