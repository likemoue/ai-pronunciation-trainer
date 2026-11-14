#!/usr/bin/env bash
# Print the cache key of the image's system-package layer (SYSTEM_REFRESH in
# the Dockerfile): one line that changes when Debian publishes a change to a
# package the image can install, and not otherwise.
#
#   scripts/system_refresh.sh        prints e.g. debian-5c0f7e2a91b3d846
#
# apt in the image reads one package index per suite: main/binary-amd64/Packages
# of trixie, trixie-updates and trixie-security. Each suite's InRelease lists
# the sha256 of that index, and apt downloads the index by that hash, so the
# key is a digest of those three lines. The rest of InRelease is left out: its
# Date changes on every update of the archive (several times a day), whether
# or not a package changed.
#
# When the archive cannot be read (no network, an unexpected answer), it warns
# on stderr and prints the ISO week instead (week-2026-W46), so the layer is
# still refreshed once a week. It always exits 0, within about 50 s: each
# request gives up after 8 s and is tried once more.
#
# CI (.github/workflows/ci.yml) and deploy/deploy.sh pass the key to docker build.
set -uo pipefail

# The Debian release of the base image (PYTHON_IMAGE in the Dockerfile).
CODENAME=trixie
# The image is built for amd64 (the VM and CI).
INDEX=main/binary-amd64/Packages
SUITES=("debian/dists/$CODENAME" "debian/dists/$CODENAME-updates" "debian-security/dists/$CODENAME-security")

fall_back() {
    echo "system_refresh.sh: $1; keying the system packages on the ISO week instead." >&2
    echo "week-$(date -u +%G-W%V)"
    exit 0
}

sha256() {
    if command -v sha256sum >/dev/null 2>&1; then sha256sum; else shasum -a 256; fi
}

lines=
for suite in "${SUITES[@]}"; do
    url=https://deb.debian.org/$suite/InRelease
    release=$(curl -fsSL --proto-redir =https --connect-timeout 5 --max-time 8 --retry 1 "$url") \
        || fall_back "could not fetch $url"
    # The one line "<sha256> <size> main/binary-amd64/Packages" of the SHA256
    # section, from the InRelease of that suite.
    line=$(awk -v codename="${suite##*/}" -v index_path="$INDEX" '
        { sub(/\r$/, "") }
        /^Codename: / { found_codename = $2 }
        /^SHA256:/ { in_sha256 = 1; next }
        in_sha256 && !/^ / { in_sha256 = 0 }
        in_sha256 && $3 == index_path && length($1) == 64 && $1 !~ /[^0-9a-f]/ && $2 ~ /^[0-9]+$/ {
            entry = $1 " " $2 " " $3
            entries++
        }
        END {
            if (found_codename != codename || entries != 1) exit 1
            print entry
        }' <<<"$release") \
        || fall_back "no single sha256 of $INDEX in $url"
    lines+="${suite##*/} $line"$'\n'
done

digest=$(printf '%s' "$lines" | sha256) || fall_back "could not compute a sha256"
[[ $digest =~ ^[0-9a-f]{16} ]] || fall_back "could not compute a sha256"
echo "debian-${digest:0:16}"
