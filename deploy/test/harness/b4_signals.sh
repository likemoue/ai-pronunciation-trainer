#!/usr/bin/env bash
# b4: SIGINT / SIGTERM / SIGHUP (Ctrl-C, kill, a dropped SSH session) at every step of a
# normal deploy, with traffic running. Production must keep serving: the previous release,
# or the new one if the deploy was recorded. The next deploy must work.
# Usage: b4_signals.sh [case ...]
SCEN=${SCEN:-b4_signals}; source /h/lib.sh
declare -A CASES=(
  [int-group-build]="FAULT_SIG=INT FAULT_SIG_TO=group FAULT_SIG_AT=build FAULT_SIG_DELAY=0.5"
  [term-bash-build]="FAULT_SIG=TERM FAULT_SIG_TO=bash FAULT_SIG_AT=build FAULT_SIG_DELAY=0.5"
  [int-group-run]="FAULT_SIG=INT FAULT_SIG_TO=group FAULT_SIG_AT=stage-run FAULT_SIG_DELAY=0.1"
  [term-bash-run]="FAULT_SIG=TERM FAULT_SIG_TO=bash FAULT_SIG_AT=stage-run FAULT_SIG_DELAY=0.1"
  [int-group-wait]="FAULT_SIG=INT FAULT_SIG_TO=group FAULT_SIG_AT=wait FAULT_SIG_DELAY=0.5"
  [hangup-wait]="--pty FAULT_SIG_TO=hangup FAULT_SIG_AT=wait FAULT_SIG_DELAY=0.5"
  [term-bash-smoke-staging]="FAULT_SIG=TERM FAULT_SIG_TO=bash FAULT_SIG_AT=smoke-staging FAULT_SIG_DELAY=0.5 SMOKE_SLEEP=2"
  [int-group-reload]="FAULT_SIG=INT FAULT_SIG_TO=group FAULT_SIG_AT=reload"
  [int-bash-after-reload]="FAULT_SIG=INT FAULT_SIG_TO=bash FAULT_SIG_AT=after-reload"
  [term-group-after-reload]="FAULT_SIG=TERM FAULT_SIG_TO=group FAULT_SIG_AT=after-reload"
  [hangup-after-reload]="--pty FAULT_SIG_TO=hangup FAULT_SIG_AT=after-reload"
  [int-group-smoke-prod]="FAULT_SIG=INT FAULT_SIG_TO=group FAULT_SIG_AT=smoke-prod FAULT_SIG_DELAY=0.5 SMOKE_SLEEP=2"
  [term-bash-smoke-prod]="FAULT_SIG=TERM FAULT_SIG_TO=bash FAULT_SIG_AT=smoke-prod FAULT_SIG_DELAY=0.5 SMOKE_SLEEP=2"
  [int-bash-prelog]="FAULT_SIG=INT FAULT_SIG_TO=bash FAULT_SIG_AT=pre-log"
  [int-group-posttag]="FAULT_SIG=INT FAULT_SIG_TO=group FAULT_SIG_AT=post-tag"
  [int-group-retire]="FAULT_SIG=INT FAULT_SIG_TO=group FAULT_SIG_AT=stop-colour FAULT_SIG_DELAY=0.3"
  [hangup-nohup-wait]="--pty-nohup FAULT_SIG_TO=hangup FAULT_SIG_AT=wait FAULT_SIG_DELAY=0.5"
  [hangup-nohup-after-reload]="--pty-nohup FAULT_SIG_TO=hangup FAULT_SIG_AT=after-reload"
)
ORDER=(int-group-build term-bash-build int-group-run term-bash-run int-group-wait hangup-wait term-bash-smoke-staging
       int-group-reload int-bash-after-reload term-group-after-reload hangup-after-reload int-group-smoke-prod
       term-bash-smoke-prod int-bash-prelog int-group-posttag int-group-retire hangup-nohup-wait hangup-nohup-after-reload)
(( $# )) && ORDER=("$@")

reset_all
commit A good
run_deploy
commit B good
run_deploy
traffic_start 1
n=0
for c in "${ORDER[@]}"; do
  n=$((n + 1))
  prev=$(logged_last)
  commit "S$n" good; eval "new=\$S$n"
  say ""; say "=================== case $c: live=$prev new=$new"
  read -r -a args <<<"${CASES[$c]}"
  run_deploy "${args[@]}"
  settle 3
  state "after the interrupted deploy"
  check "$c: production serves something" serves_any
  check "$c: the live colour runs" live_runs
  if [[ "$(logged_last)" == "$new" ]]; then
    check "$c: logged $new -> serves $new" serves "$new"
  else
    check "$c: not logged -> serves $prev" serves "$prev"
    check "$c: not logged -> new image removed or unused" bash -c "! docker image inspect $APP:$new >/dev/null 2>&1 || true"
  fi
  check "$c: only expected containers" only_expected_ctrs
  run_deploy
  check "$c: next deploy exit 0" test "$RC" = 0
  check "$c: next deploy serves $new" serves "$new"
done
traffic_stop 1
say "  failed requests across ${#ORDER[@]} interrupted deploys and their re-runs: $(traffic_failures 1), of which not at a Caddy reload: $(traffic_failures_apart_from_reloads 1)"
check "no request failed across ${#ORDER[@]} interrupted deploys and their re-runs, apart from Caddy reloads" test "$(traffic_failures_apart_from_reloads 1)" = 0
say "FAILS=$FAILS"
