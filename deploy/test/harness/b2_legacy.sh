#!/usr/bin/env bash
# b2: the host still runs the single container of earlier versions. The first deploy moves
# it behind the proxy (a short outage, measured with traffic without the long requests, which
# the single container would finish first); --rollback brings it back; the next deploy moves it again.
SCEN=${SCEN:-b2_legacy}; source /h/lib.sh
# The longest the move may leave the port unavailable: the stand-in app finishes its
# requests (at most 1.5 s) before it exits, and the move took 1.4-3.4 s in earlier runs.
MOVE_OUTAGE_MAX=${MOVE_OUTAGE_MAX:-6}
reset_all
commit L good
legacy "$L"
commit A good
traffic_start 1 basic
run_deploy
move_run=$RUN_NO
traffic_stop 1
state "after the first deploy"
check "migration: exit 0" test "$RC" = 0
check "migration: proxy publishes :$PROD_PORT" running "$APP-proxy"
check "migration: serves A" serves "$A"
check "migration: legacy kept stopped as $APP-legacy" stopped "$APP-legacy"
check "migration: no container named $APP" no_ctr "$APP"
check "migration: no marker left" test ! -e "$SW/state/migration-in-progress"
check "migration: the port was unavailable for at most $MOVE_OUTAGE_MAX s, and only then did requests fail" \
  move_window 1 "$move_run" "$MOVE_OUTAGE_MAX"
commit B good
traffic_start 2
run_deploy
traffic_stop 2
check "after the move, a normal deploy drops no request" no_failed_requests 2
check "B: serves B" serves "$B"
check "legacy still kept" stopped "$APP-legacy"
run_deploy --rollback
check "rollback to A (blue): serves A" serves "$A"
docker rm -f "${APP:?}-green" >/dev/null   # leave no previous colour
run_deploy --rollback
check "no previous colour: --rollback refuses (exit 1)" test "$RC" = 1
check "no previous colour: it offers --rollback-legacy" grep -q -- "--rollback-legacy" "$LOG"
check "no previous colour: still serves A" serves "$A"
run_deploy --rollback-legacy
state "after rolling back to the single container"
check "rollback to legacy: exit 0" test "$RC" = 0
check "rollback to legacy: serves L" serves "$L"
check "rollback to legacy: $APP publishes the port" bash -c "docker port $APP 3000/tcp | grep -q :$PROD_PORT"
check "rollback to legacy: no proxy" no_ctr "$APP-proxy"
commit C good
run_deploy
state "after moving behind the proxy again"
check "second migration: exit 0" test "$RC" = 0
check "second migration: serves C" serves "$C"
check "second migration: legacy kept" stopped "$APP-legacy"
check "only expected containers" only_expected_ctrs
end_scenario
