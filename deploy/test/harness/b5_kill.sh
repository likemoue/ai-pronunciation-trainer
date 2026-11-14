#!/usr/bin/env bash
# b5: SIGKILL (or a reboot) at every step of a normal deploy, then deploy again.
# Production must keep serving throughout, and the re-run must finish cleanly.
SCEN=${SCEN:-b5_kill}; source /h/lib.sh
declare -A CASES=(
  [build]="FAULT_SIG=KILL FAULT_SIG_TO=group FAULT_SIG_AT=build FAULT_SIG_DELAY=0.5"
  [run]="FAULT_SIG=KILL FAULT_SIG_TO=bash FAULT_SIG_AT=stage-run FAULT_SIG_DELAY=0.1"
  [wait]="FAULT_SIG=KILL FAULT_SIG_TO=group FAULT_SIG_AT=wait FAULT_SIG_DELAY=0.5"
  [reload]="FAULT_SIG=KILL FAULT_SIG_TO=bash FAULT_SIG_AT=reload"
  # The whole group dies right before `caddy reload`: upstream.caddy names the new colour, Caddy still sends to the old.
  [reload-group]="FAULT_SIG=KILL FAULT_SIG_TO=group FAULT_SIG_AT=reload"
  [after-reload]="FAULT_SIG=KILL FAULT_SIG_TO=group FAULT_SIG_AT=after-reload"
  [smoke-prod]="FAULT_SIG=KILL FAULT_SIG_TO=group FAULT_SIG_AT=smoke-prod FAULT_SIG_DELAY=0.5 SMOKE_SLEEP=2"
  [prelog]="FAULT_SIG=KILL FAULT_SIG_TO=bash FAULT_SIG_AT=pre-log"
  [posttag]="FAULT_SIG=KILL FAULT_SIG_TO=bash FAULT_SIG_AT=post-tag"
  [retire]="FAULT_SIG=KILL FAULT_SIG_TO=group FAULT_SIG_AT=stop-colour FAULT_SIG_DELAY=0.3"
)
ORDER=(build run wait reload reload-group after-reload smoke-prod prelog posttag retire)
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
  commit "K$n" good; eval "new=\$K$n"
  say ""; say "=================== SIGKILL case $c: live=$prev new=$new"
  read -r -a args <<<"${CASES[$c]}"
  run_deploy "${args[@]}"
  settle 3
  state "after SIGKILL"
  point=${CASES[$c]#*FAULT_SIG_AT=}; point=${point%% *}
  check "$c: the signal was sent at $point" fired "$point"
  check "$c: production serves something after the kill" serves_any
  if [[ $c == wait ]]; then
    # The idle colour holds the release the killed deploy was starting, never deployed.
    run_deploy --rollback
    check "$c: --rollback refuses the release the killed deploy left (exit 1)" test "$RC" = 1
    check "$c: it says that release is not in the deploy log" grep -q "which is not in .* so it is not the previous release" "$LOG"
    check "$c: still serves $prev" serves "$prev"
  fi
  run_deploy
  state "after deploying again"
  check "$c: re-run exit 0" test "$RC" = 0
  check "$c: serves $new" serves "$new"
  check "$c: the live colour runs" live_runs
  check "$c: the other colour is stopped" stopped "$(other "$(live)")"
  check "$c: only expected containers" only_expected_ctrs
done
traffic_stop 1
check "no request failed across ${#ORDER[@]} killed deploys and their re-runs" no_failed_requests 1
end_scenario
