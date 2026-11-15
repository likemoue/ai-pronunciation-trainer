#!/usr/bin/env bash
# b3: releases that fail. Production keeps serving the live release, the failed colour and
# image are removed, and the next deploy works.
SCEN=${SCEN:-b3_failures}; source /h/lib.sh
reset_all
commit A good
run_deploy
commit B good
run_deploy
traffic_start 1
n=0
for c in bad-health crash unhealthy staging-port create smoke-staging smoke-prod reload rollback-check inspect-blip; do
  if [[ $c == rollback-check ]]; then
    # After all those failures, --rollback still goes to the release before the live one.
    run_deploy --rollback
    check "rollback after 8 failed deploys: exit 0" test "$RC" = 0
    check "rollback after 8 failed deploys: serves A" serves "$A"
    run_deploy --rollback
    check "and back: serves B" serves "$B"
    continue
  fi
  n=$((n + 1))
  prev=$(logged_last); prevlive=$(live)
  case $c in
    bad-health) commit "F$n" bad; args=() ;;
    crash) commit "F$n" crash; args=() ;;
    unhealthy) commit "F$n" good; args=(FAULT_STAGING=unhealthy) ;;
    staging-port) commit "F$n" good; args=(FAULT_STAGING=port) ;;
    create) commit "F$n" good; args=(FAULT_STAGING=create) ;;
    smoke-staging) commit "F$n" good; args=("SMOKE_FAIL_PORTS=$BLUE_PORT,$GREEN_PORT") ;;
    smoke-prod) commit "F$n" good; args=("SMOKE_FAIL_PORTS=$PROD_PORT") ;;
    reload) commit "F$n" good; args=(FAULT_RELOAD=fail) ;;
    inspect-blip) commit "F$n" good; args=(FAULT_INSPECT_FAIL=2) ;;
  esac
  eval "new=\$F$n"
  say ""; say "=================== failure case $c: live=$prev new=$new"
  run_deploy "${args[@]}"
  $D rm -f "${APP:?}-blocker" >/dev/null 2>&1 || true
  state "after"
  check "$c: it got as far as starting $new" grep -q "Starting $APP:$new as" "$LOG"
  if [[ $c == inspect-blip ]]; then
    check "$c: a transient inspect failure does not fail the deploy" test "$RC" = 0
    check "$c: serves $new" serves "$new"
    continue
  fi
  check "$c: exit 1" test "$RC" = 1
  check "$c: still serves $prev" serves "$prev"
  check "$c: live colour unchanged" test "$(live)" = "$prevlive"
  check "$c: live colour runs" live_runs
  check "$c: failed image removed" no_img "$new"
  # The idle slot holds the previous release (A) again, stopped, for --rollback.
  check "$c: previous release back in $(other "$prevlive"), stopped" bash -c "! docker container inspect -f '{{.State.Running}}' $(other "$prevlive") | grep -q true"
  check "$c: it is release $A" test "$(image_of "$(other "$prevlive")")" = "$A"
  check "$c: log unchanged" test "$(logged_last)" = "$prev"
  check "$c: only expected containers" only_expected_ctrs
done
traffic_stop 1
check "no request failed during 9 failed deploys and 2 rollbacks" no_failed_requests 1
commit G good
run_deploy
check "next good deploy: exit 0" test "$RC" = 0
check "next good deploy: serves G" serves "$G"
end_scenario
