#!/usr/bin/env bash
# b6: faults while the single container is moved behind the proxy. After each case the
# port must be served (by the single container, or by the proxy if the move finished),
# and deploying again must finish the move.
# Usage: b6_migration.sh [case ...]
SCEN=${SCEN:-b6_migration}; source /h/lib.sh
declare -A CASES=(
  [proxy-start-fails]="FAULT_PROXY_START=fail"
  [port-taken]="FAULT_PROXY_START=port BLOCKER_SECS=1"
  [smoke-prod-fails]="SMOKE_FAIL_PORTS=$PROD_PORT"
  [int-stop-legacy]="FAULT_SIG=INT FAULT_SIG_TO=group FAULT_SIG_AT=stop-legacy FAULT_SIG_DELAY=0.3"
  [term-bash-start-proxy]="FAULT_SIG=TERM FAULT_SIG_TO=bash FAULT_SIG_AT=start-proxy"
  [hangup-after-start-proxy]="--pty FAULT_SIG_TO=hangup FAULT_SIG_AT=after-start-proxy"
  [int-smoke-prod]="FAULT_SIG=INT FAULT_SIG_TO=group FAULT_SIG_AT=smoke-prod FAULT_SIG_DELAY=0.5 SMOKE_SLEEP=2"
  [int-after-rename]="FAULT_SIG=INT FAULT_SIG_TO=bash FAULT_SIG_AT=after-rename"
  [kill-stop-legacy]="FAULT_SIG=KILL FAULT_SIG_TO=group FAULT_SIG_AT=stop-legacy FAULT_SIG_DELAY=0.3"
  [kill-after-start-proxy]="FAULT_SIG=KILL FAULT_SIG_TO=bash FAULT_SIG_AT=after-start-proxy"
  [kill-smoke-prod]="FAULT_SIG=KILL FAULT_SIG_TO=group FAULT_SIG_AT=smoke-prod FAULT_SIG_DELAY=0.5 SMOKE_SLEEP=2"
  [kill-after-rename]="FAULT_SIG=KILL FAULT_SIG_TO=bash FAULT_SIG_AT=after-rename"
  [kill-prelog]="FAULT_SIG=KILL FAULT_SIG_TO=bash FAULT_SIG_AT=pre-log"
)
ORDER=(proxy-start-fails port-taken smoke-prod-fails int-stop-legacy term-bash-start-proxy hangup-after-start-proxy
       int-smoke-prod int-after-rename kill-stop-legacy kill-after-start-proxy kill-smoke-prod kill-after-rename kill-prelog)
(( $# )) && ORDER=("$@")

for c in "${ORDER[@]}"; do
  reset_all
  commit L good
  legacy "$L"
  commit A good
  say ""; say "=================== migration case $c"
  read -r -a args <<<"${CASES[$c]}"
  run_deploy "${args[@]}"
  first=$RC
  settle 3
  $D rm -f "$APP-blocker" >/dev/null 2>&1 || true
  state "after the faulty first deploy (exit $first)"
  if [[ "$(serving)" == "ok $L" ]]; then
    say "  the single container serves again"
    check "$c: $APP publishes the port again" bash -c "docker port $APP 3000/tcp 2>/dev/null | grep -q :$PROD_PORT"
    check "$c: no proxy left" no_ctr "$APP-proxy"
  elif [[ "$(serving)" == "ok $A" ]]; then
    say "  the proxy serves the new release"
  elif [[ $c == kill-* ]]; then
    # SIGKILL in the middle of the move leaves the port unserved until the next run.
    say "  down after the SIGKILL until the next run: '$(serving)'"
  else
    say "  FAIL $c: the port serves nothing useful: '$(serving)'"
    FAILS=$((FAILS + 1))
  fi
  run_deploy
  state "after deploying again"
  # A run that finds an interrupted move and has to put the single container back stops
  # there (exit 1); one more deploy then moves it.
  if [[ $RC == 1 ]] && grep -q 'interrupted while it moved' "$LOG"; then
    check "$c: recovery put $L back" serves "$L"
    run_deploy
    state "after a third deploy"
  fi
  check "$c: deploy exit 0" test "$RC" = 0
  check "$c: serves A behind the proxy" serves "$A"
  check "$c: proxy runs" running "$APP-proxy"
  check "$c: single container kept stopped as $APP-legacy" stopped "$APP-legacy"
  check "$c: no container named $APP" no_ctr "$APP"
  check "$c: no marker" test ! -e "$SW/state/migration-in-progress"
  check "$c: only expected containers" only_expected_ctrs
done
say "FAILS=$FAILS"
