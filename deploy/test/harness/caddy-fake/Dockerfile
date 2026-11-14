# A stand-in Caddy (lib.sh fake_caddy): the pinned Caddy, except that it refuses every
# Caddyfile that contains REFUSE, as a Caddy release that does not understand it would.
FROM caddy:2.11.9-alpine@sha256:003a97808e781aa9f7e75cc2f43d34d461099031faf5e20faefb9f61126836f0
ARG REFUSE=request_buffers
RUN mv /usr/bin/caddy /usr/bin/caddy.real \
 && printf '%s\n' '#!/bin/sh' \
    'for a in "$@"; do case "$a" in *Caddyfile) f=$a ;; esac; done' \
    "if [ -n \"\$f\" ] && grep -qF '$REFUSE' \"\$f\" 2>/dev/null; then echo \"Error: adapting config using caddyfile: \$f: '$REFUSE' is not understood by this Caddy (harness)\" >&2; exit 1; fi" \
    'exec /usr/bin/caddy.real "$@"' > /usr/bin/caddy \
 && chmod +x /usr/bin/caddy
