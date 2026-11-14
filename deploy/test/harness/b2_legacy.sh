#!/usr/bin/env bash
# b2: the host still runs the single container of earlier versions. The first deploy moves
# it behind the proxy (a short outage, measured with traffic); --rollback brings it back;
# the next deploy moves it again.
SCEN=${SCEN:-b2_legacy}; source /h/lib.sh
reset_all
commit L good
legacy "$L"
commit A good
traffic_start 1
run_deploy
traffic_stop 1
state "after the first deploy"
check "migration: exit 0" test "$RC" = 0
check "migration: proxy publishes :$PROD_PORT" running "$APP-proxy"
check "migration: serves A" serves "$A"
check "migration: legacy kept stopped as $APP-legacy" stopped "$APP-legacy"
check "migration: no container named $APP" no_ctr "$APP"
check "migration: no marker left" test ! -e "$SW/state/migration-in-progress"
say "  outage during the move: $(grep -o 'refused new connections for [0-9.]* s' "$LOG" | head -1); failed requests: $(traffic_failures 1)"
commit B good
traffic_start 2
run_deploy
traffic_stop 2
say "  failed requests in a normal deploy after the move: $(traffic_failures 2)"
check "after the move, a normal deploy drops nothing apart from its Caddy reload" test "$(traffic_failures_apart_from_reloads 2)" = 0
check "B: serves B" serves "$B"
check "legacy still kept" stopped "$APP-legacy"
run_deploy --rollback
check "rollback to A (blue): serves A" serves "$A"
docker rm -f "$APP-green" >/dev/null   # leave no previous colour
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
say "FAILS=$FAILS"
