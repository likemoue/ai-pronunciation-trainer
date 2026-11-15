#!/usr/bin/env bash
# b1: a host with nothing on it. First deploy starts the proxy; later deploys alternate
# colours with traffic running, --rollback, --status, image pruning (KEEP_IMAGES=2; a release
# logged under its own tag, english-ui, is kept).
SCEN=${SCEN:-b1_lifecycle}; KEEP_IMAGES=2; source /h/lib.sh
reset_all
commit A good
run_deploy
state "after the first deploy"
check "first deploy exit 0" test "$RC" = 0
check "proxy runs" running "$APP-proxy"
check "blue is live and serves A" bash -c "[[ \$(cat $SW/state/proxy/upstream.caddy) == 'to $APP-blue:3000' ]]"
check "port serves A" serves "$A"
check "log has 1 line" log_lines 1
check "latest = A" latest_is "$A"

traffic_start 1
commit B good
run_deploy
state "after deploying B"
check "B: exit 0" test "$RC" = 0
check "B: green live" test "$(live)" = "$APP-green"
check "B: serves B" serves "$B"
check "B: blue (A) kept, stopped" stopped "$APP-blue"
check "B: blue holds A" test "$(image_of "$APP-blue")" = "$A"
check "B: blue was stopped only after read_body and the margin" \
  grep -q "$APP-blue gets [0-9]* s more for the requests Caddy accepted before the switch (read_body 3 s + 1 s)" "$LOG"
# A release switched to by hand is logged under its own tag (deploy/RUNBOOK.md); pruning keeps it.
$D tag "$APP:$A" "$APP:english-ui"
sed -i "1i 2026-01-01T00:00:00Z english-ui 0123456789ab" "$DEPLOY_LOG"
commit C good
run_deploy
state "after deploying C"
check "C: exit 0" test "$RC" = 0
check "C: blue live with C" test "$(image_of "$APP-blue")" = "$C"
check "C: serves C" serves "$C"
check "C: green (B) kept, stopped" stopped "$APP-green"
check "C: image A pruned (KEEP_IMAGES=2)" no_img "$A"
check "C: images B and C kept" bash -c "$D image inspect $APP:$B $APP:$C >/dev/null"
run_deploy --rollback
state "after --rollback"
check "rollback: exit 0" test "$RC" = 0
check "rollback: serves B" serves "$B"
check "rollback: green live" test "$(live)" = "$APP-green"
check "rollback: blue (C) kept, stopped" stopped "$APP-blue"
check "rollback: logged B" test "$(logged_last)" = "$B"
check "rollback: latest = B" latest_is "$B"
run_deploy --rollback
state "after a second --rollback (back to C)"
check "rollback 2: serves C" serves "$C"
commit E good
run_deploy
check "E: serves E" serves "$E"
run_deploy "origin/main"
state "after re-deploying the same commit"
check "same sha: exit 0" test "$RC" = 0
check "same sha: serves E" serves "$E"
check "same sha: both colours hold E" bash -c "[[ \$(docker container inspect -f '{{.Config.Image}}' $APP-blue) == \$(docker container inspect -f '{{.Config.Image}}' $APP-green) ]]"
check "the english-ui line's image survived 4 prunings" has_img english-ui
traffic_stop 1
check "no request failed during 5 deploys and 2 rollbacks" no_failed_requests 1
run_deploy --status
check "--status exit 0" test "$RC" = 0
grep -q 'live' "$LOG" && say "  status output names the live colour" || { say "  FAIL status output"; FAILS=$((FAILS+1)); }
check "only proxy and colours exist" only_expected_ctrs
end_scenario
