#!/usr/bin/env bash
# b7: one deploy at a time; output through `| tee` that dies; leftovers of the
# single-container deploy.sh; refs that cannot be deployed; a stopped proxy; a
# hand-edited proxy config; --status and --help.
SCEN=${SCEN:-b7_misc}; source /h/lib.sh
reset_all
commit A good
run_deploy
commit B good

# Two deploys at once: the second one must refuse at once.
( cd "$REPO_DIR" && SMOKE_SLEEP=4 deploy/deploy.sh > "$OUT/$SCEN.first.log" 2>&1; echo $? > "$HARNESS_STATE/first.rc" ) &
sleep 2
run_deploy
check "concurrent: second deploy exits 1" test "$RC" = 1
check "concurrent: it says another deploy runs" grep -q 'Another deploy is running' "$LOG"
wait
check "concurrent: first deploy exit 0" test "$(cat "$HARNESS_STATE/first.rc")" = 0
check "concurrent: serves B" serves "$B"

# `deploy.sh | tee` where tee is killed (the output pipe closes).
commit C good
( cd "$REPO_DIR" && { SMOKE_SLEEP=3 deploy/deploy.sh; echo $? > "$HARNESS_STATE/tee.rc"; } 2>&1 | tee "$HARNESS_STATE/tee.out" >/dev/null ) &
sleep 1.5; pkill -f "tee $HARNESS_STATE/tee.out" || true; wait
settle 3
state "after tee died"
say "  deploy.sh exited with $(cat "$HARNESS_STATE/tee.rc" 2>/dev/null)"
check "tee: serves B or C" bash -c "[[ \$(curl -s -m2 127.0.0.1:$PROD_PORT/) == 'ok $B' || \$(curl -s -m2 127.0.0.1:$PROD_PORT/) == 'ok $C' ]]"
check "tee: only expected containers" only_expected_ctrs
run_deploy
check "tee: next deploy exit 0" test "$RC" = 0
check "tee: serves C" serves "$C"

# Leftovers of the single-container deploy.sh are refused, nothing is touched.
$D run -d --name "$APP-previous" alpine:3 sleep 600 >/dev/null
commit E good
run_deploy
check "leftover: exit 1" test "$RC" = 1
check "leftover: message" grep -q "single-container deploy.sh was interrupted" "$LOG"
check "leftover: still serves C" serves "$C"
$D rm -f "$APP-previous" >/dev/null
touch "$SW/state/swap-in-progress"
run_deploy
check "swap marker: exit 1" test "$RC" = 1
rm -f "$SW/state/swap-in-progress"

# Refs that cannot be deployed.
run_deploy origin/no-such-branch
check "unknown ref: exit 1" test "$RC" = 1
( cd "$W/work" && git rm -q deploy/smoke_test.py && git commit -qm nosmoke && git push -q origin HEAD:nosmoke )
run_deploy origin/nosmoke
check "branch not on main: exit 1" test "$RC" = 1
check "branch not on main: message" grep -q "is not on main" "$LOG"
run_deploy DEPLOY_ANY_BRANCH=1 origin/nosmoke
check "no smoke test: exit 1" test "$RC" = 1
check "no smoke test: message" grep -q "has no deploy/smoke_test.py" "$LOG"
( cd "$W/work" && git checkout -q main 2>/dev/null; git reset -q --hard origin/main 2>/dev/null || true )
( cd "$REPO_DIR" && git fetch -q origin && git checkout -q -B local-only origin/main && git commit -q --allow-empty -m unpushed )
run_deploy DEPLOY_ANY_BRANCH=1 local-only
check "unpushed: exit 1" test "$RC" = 1
check "unpushed: message" grep -q "not on any branch of origin" "$LOG"
( cd "$REPO_DIR" && git checkout -q -B main origin/main )
check "refused refs: still serves C" serves "$C"

# A stopped proxy is started again; a hand-edited Caddyfile is rewritten.
$D stop "$APP-proxy" >/dev/null
echo "# edited by hand" >> "$SW/state/proxy/Caddyfile"
run_deploy
state "after a deploy with the proxy stopped and its config edited"
check "stopped proxy: deploy exit 0" test "$RC" = 0
check "stopped proxy: serves E" serves "$E"
check "edited config: rewritten" bash -c "! grep -q 'edited by hand' $SW/state/proxy/Caddyfile"

# --replace-proxy recreates the proxy in front of the live colour.
old_proxy=$($D container inspect -f '{{.Id}}' "$APP-proxy")
run_deploy --replace-proxy
check "--replace-proxy: exit 0" test "$RC" = 0
check "--replace-proxy: a new proxy container" bash -c "[[ \$(docker container inspect -f '{{.Id}}' $APP-proxy) != $old_proxy ]]"
check "--replace-proxy: serves E" serves "$E"

# --status and --help need no lock and change nothing.
run_deploy --status
check "--status: exit 0" test "$RC" = 0
check "--status: shows the version" grep -q "$E" "$LOG"
run_deploy --help
check "--help: exit 0" test "$RC" = 0
check "--help: prints usage" grep -q -- "--rollback" "$LOG"
check "only expected containers" only_expected_ctrs
say "FAILS=$FAILS"
