#!/usr/bin/env bash
# b8: what stops deploy.sh before it changes anything. A CADDY_IMAGE that refuses the
# configuration (--replace-proxy leaves the proxy serving, with traffic running); a proxy on
# an older Caddy that refuses a new configuration; commits older than OLDEST_RELEASE; CI's
# verdict from a stand-in GitHub API (bin/git, bin/curl). Also: no deploy log while a proxy
# exists, and port PROD_PORT taken while the proxy is stopped.
SCEN=${SCEN:-b8_gates}; source /h/lib.sh
reset_all
commit A good
run_deploy
commit B good
run_deploy
check "B: exit 0" test "$RC" = 0

# A CADDY_IMAGE that refuses the configuration: --replace-proxy checks it before it touches the
# proxy, which goes on serving.
fake_caddy caddy-refuses request_buffers
old_proxy=$($D container inspect -f '{{.Id}}' "$APP-proxy")
traffic_start 1; sleep 2
run_deploy "CADDY_IMAGE=$APP:caddy-refuses" --replace-proxy
sleep 2; traffic_stop 1
check "refusing Caddy: --replace-proxy exit 1" test "$RC" = 1
check "refusing Caddy: it says so" grep -q "refuses the configuration, so $APP-proxy was left as it was" "$LOG"
check "refusing Caddy: the same proxy, running" \
  bash -c "[[ \$(docker container inspect -f '{{.Id}} {{.State.Running}}' $APP-proxy) == '$old_proxy true' ]]"
check "refusing Caddy: serves B" serves "$B"
check "refusing Caddy: no request failed" no_failed_requests 1

# A proxy on an older Caddy: a configuration that it refuses stops a deploy, and nothing changes.
fake_caddy caddy-old "read_body 7s"
run_deploy "CADDY_IMAGE=$APP:caddy-old" --replace-proxy
check "older Caddy: the proxy runs it (exit 0)" test "$RC" = 0
commit C good
run_deploy READ_BODY_SECONDS=7
check "older Caddy: a configuration it refuses stops the deploy (exit 1)" test "$RC" = 1
check "older Caddy: it says so" grep -q "The proxy's configuration was not changed" "$LOG"
check "older Caddy: the Caddyfile is unchanged" grep -q "read_body 3s" "$SW/state/proxy/Caddyfile"
check "older Caddy: still serves B" serves "$B"
run_deploy --replace-proxy
check "back to the pinned Caddy: exit 0" test "$RC" = 0
check "back to the pinned Caddy: serves B" serves "$B"

# OLDEST_RELEASE: commits that do not contain it are refused, by deploys and by --rollback.
b_full=$(git -C "$W/work" rev-parse "$B")
run_deploy "OLDEST_RELEASE=$b_full" "$A"
check "OLDEST_RELEASE: an older commit is refused (exit 1)" test "$RC" = 1
check "OLDEST_RELEASE: it says why" grep -q "does not contain $B (OLDEST_RELEASE)" "$LOG"
run_deploy "OLDEST_RELEASE=$b_full" --rollback
check "OLDEST_RELEASE: --rollback to an older release is refused (exit 1)" test "$RC" = 1
check "OLDEST_RELEASE: it says why" grep -q "does not contain $B (OLDEST_RELEASE)" "$LOG"
run_deploy OLDEST_RELEASE=0123456789abcdef0123456789abcdef01234567
check "OLDEST_RELEASE that is not a commit: refused (exit 1)" test "$RC" = 1
check "OLDEST_RELEASE that is not a commit: it says so" grep -q "is not a commit in" "$LOG"
check "OLDEST_RELEASE: still serves B" serves "$B"

# No deploy log while a proxy exists: the next run records what Caddy serves and goes on.
rm -f "$DEPLOY_LOG"
run_deploy
check "no deploy log: exit 0" test "$RC" = 0
check "no deploy log: it recorded what Caddy served" grep -q "which an interrupted run did not record; recording it" "$LOG"
check "no deploy log: B, then C" bash -c "[[ \$(awk '{print \$2}' $DEPLOY_LOG | paste -sd ' ') == '$B $C' ]]"
check "no deploy log: serves C" serves "$C"

# Port PROD_PORT taken while the proxy is stopped: deploy.sh repeats docker's error and says
# how to find what holds the port.
$D stop "${APP:?}-proxy" >/dev/null
$D run -d --name "${APP:?}-blocker" -p "$PROD_PORT:80" alpine:3 sleep 600 >/dev/null
run_deploy
check "port taken: production is down, exit 2" test "$RC" = 2
check "port taken: it repeats docker's error" grep -q "The last docker start said: .*$PROD_PORT" "$LOG"
check "port taken: and how to find what holds the port" grep -qF "docker ps --filter publish=$PROD_PORT" "$LOG"
$D rm -f "${APP:?}-blocker" >/dev/null
run_deploy
check "port free again: exit 0" test "$RC" = 0
check "port free again: serves C" serves "$C"

# CI's verdict: a failed, cancelled or unfinished run is refused; a passed run deploys, and
# so does a commit GitHub cannot be asked about, with a warning.
commit D good
declare -A SAYS=([failure]="CI did not pass for $D (failure)" [cancelled]="CI's run for $D was cancelled"
                 [pending]="CI is still running for $D")
for verdict in failure cancelled pending; do
  run_deploy FAKE_GITHUB_REPO=owner/repo "FAKE_CI=$verdict"
  check "CI $verdict: refused (exit 1)" test "$RC" = 1
  check "CI $verdict: it says so" grep -qF "${SAYS[$verdict]}" "$LOG"
done
check "refused by CI: still serves C" serves "$C"
run_deploy FAKE_GITHUB_REPO=owner/repo FAKE_CI=success
check "CI passed: exit 0" test "$RC" = 0
check "CI passed: it says so" grep -qF "CI passed for $D" "$LOG"
check "CI passed: serves D" serves "$D"
run_deploy FAKE_GITHUB_REPO=owner/repo FAKE_CI=error
check "CI unknown: deploys anyway (exit 0)" test "$RC" = 0
check "CI unknown: with a warning" grep -qF "could not ask GitHub whether CI passed for $D" "$LOG"
check "only expected containers" only_expected_ctrs
end_scenario
