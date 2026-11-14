#!/usr/bin/env bash
# Harness library for the blue/green deploy.sh, sourced by the scenario scripts
# inside the aipt-bg-harness container. deploy.sh runs from a clone of a fake
# origin (as the RUNBOOK does); the app is a 60-line stand-in (app/).
# Lanes (LANE=1..3) use their own names, ports and directories so they can run side by side.
LANE=${LANE:-1}
case "$LANE" in
  1) export APP=aipt-bg1 PROD_PORT=3391 BLUE_PORT=3392 GREEN_PORT=3393 ;;
  2) export APP=aipt-bg2 PROD_PORT=3394 BLUE_PORT=3395 GREEN_PORT=3396 ;;
  3) export APP=aipt-bg3 PROD_PORT=3397 BLUE_PORT=3398 GREEN_PORT=3399 ;;
esac
# Bind mounts made by deploy.sh are resolved by the docker daemon, so deploy.sh's
# state directory lives on a path that the harness container and the daemon share
# (SW; mounted noexec in the Docker Desktop VM). Repos and harness files stay in W.
export W=/work/lane$LANE SW=/tmp/aipt-bg/lane$LANE
export HARNESS_STATE=$W/hstate REPO_DIR=$W/repo DEPLOY_LOG=$SW/state/deploys.log
export HEALTH_TIMEOUT=${HEALTH_TIMEOUT:-25} KEEP_IMAGES=${KEEP_IMAGES:-3} DRAIN_SECONDS=${DRAIN_SECONDS:-2} STOP_TIMEOUT=${STOP_TIMEOUT:-10}
export PATH=/h/bin:$PATH HARNESS_FIRE=/h/bin/fire
D=/usr/local/bin/docker
OUT=/out
RUN_NO=0
SCEN=${SCEN:-scratch}
RC=
FAILS=0
: > "$OUT/$SCEN.txt"

say() { echo "$*" | tee -a "$OUT/$SCEN.txt"; }

reset_all() {
  $D ps -aq --filter "name=^/$APP" | xargs -r $D rm -f >/dev/null
  $D images "$APP" --format '{{.Repository}}:{{.Tag}}' | xargs -r $D rmi >/dev/null 2>&1 || true
  $D network rm "$APP-net" >/dev/null 2>&1 || true
  rm -rf "$W" "$SW"; mkdir -p "$HARNESS_STATE" "$(dirname "$DEPLOY_LOG")"
  git init -q --bare "$W/origin.git"
  git clone -q "$W/origin.git" "$W/work" 2>/dev/null
  cp -r /h/app/. "$W/work/"
  mkdir -p "$W/work/deploy"
  tr -d '\r' < "${DEPLOY_SH:-/deploy/deploy.sh}" > "$W/work/deploy/deploy.sh"; chmod +x "$W/work/deploy/deploy.sh"
  say "== reset lane $LANE: deploy.sh = ${DEPLOY_SH:-/deploy/deploy.sh} ($(md5sum < "$W/work/deploy/deploy.sh" | cut -c1-8))"
}

# commit <label> <good|bad|crash>: new commit on main in the fake origin; sets $<label> to its short sha
commit() {
  ( cd "$W/work" && echo "$2" > HEALTH && echo "$1 $RANDOM$RANDOM" > build-id \
      && git add -A && git commit -qm "$1" && git push -q origin HEAD:main ) || return 1
  local sha; sha=$(git -C "$W/work" rev-parse --short=7 HEAD)
  printf -v "$1" '%s' "$sha"
  say "commit $1 = $sha ($2)"
}

# legacy <sha>: run that commit the way the single-container deploy.sh did
legacy() {
  git -C "$W/work" archive --format=tar "$1" | $D build -q --build-arg GIT_SHA="$1" -t "$APP:$1" - >/dev/null
  $D run -d --name "$APP" --restart unless-stopped -p "$PROD_PORT:3000" --memory 1g \
     --log-opt max-size=10m --tmpfs /tmp:rw,nosuid,size=16m "$APP:$1" >/dev/null
  printf '%s %s %s\n' "$(/bin/date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" "$($D container inspect -f '{{.Id}}' "$APP")" >> "$DEPLOY_LOG"
  local i; for i in $(seq 1 50); do [[ "$(serving)" == "ok $1" ]] && break; sleep 0.2; done
  say "legacy container $APP runs $1 on :$PROD_PORT"
}

# run_deploy [--pty|--pty-nohup|--tee] [KEY=VAL ...] [args]: run deploy.sh; sets RC and LOG
run_deploy() {
  local envs=() args=() mode=setsid
  while (( $# )); do
    case "$1" in
      --pty) mode=pty ;;
      --pty-nohup) mode=pty-nohup ;;
      --tee) mode=tee ;;
      *=*) envs+=("$1") ;;
      *) args+=("$1") ;;
    esac
    shift
  done
  RUN_NO=$((RUN_NO + 1))
  [[ -d $REPO_DIR ]] || git clone -q "$W/origin.git" "$REPO_DIR"
  rm -rf "$HARNESS_STATE"/fired.* "$HARNESS_STATE"/health-inspects "$HARNESS_STATE"/hangup-now "$HARNESS_STATE"/rc "$HARNESS_STATE"/port-blocked
  : > "$HARNESS_STATE/trace.log"
  LOG="$OUT/$SCEN.run$RUN_NO.log"
  say ""
  say "### run $RUN_NO: deploy.sh ${args[*]:-(origin/main)}   ${envs[*]} ${mode/setsid/}"
  T0=$SECONDS
  local launch='echo $$ > "$HARNESS_STATE/deploy.pid"; exec deploy/deploy.sh "$@"'
  case $mode in
    setsid)    ( cd "$REPO_DIR" && exec env "${envs[@]}" setsid -w bash -c "$launch" _ "${args[@]}" ) > "$LOG" 2>&1 ;;
    pty)       ( cd "$REPO_DIR" && exec env "${envs[@]}" python3 /h/pty_run.py bash -c "$launch" _ "${args[@]}" ) > "$LOG" 2>&1 ;;
    tee)       ( cd "$REPO_DIR" && exec env "${envs[@]}" setsid -w bash -c \
                   'echo $$ > "$HARNESS_STATE/deploy.pid"; { deploy/deploy.sh "$@"; echo $? > "$HARNESS_STATE/rc"; } 2>&1 | tee "$HARNESS_STATE/tee.log"' _ "${args[@]}" ) > "$LOG" 2>&1
               say "  deploy.sh itself exited with $(cat "$HARNESS_STATE/rc" 2>/dev/null) (141 = killed by SIGPIPE)" ;;
    pty-nohup) ( cd "$REPO_DIR" && exec env "${envs[@]}" python3 /h/pty_run.py bash -c \
                   'echo $$ > "$HARNESS_STATE/deploy.pid"; exec nohup deploy/deploy.sh "$@" > "$HARNESS_STATE/nohup.log" 2>&1' _ "${args[@]}" ) > "$LOG" 2>&1
               cat "$HARNESS_STATE/nohup.log" >> "$LOG" ;;
  esac
  RC=$?
  # deploy.sh may have been killed while a docker command it started was still running
  local pg i=0; pg=$(cat "$HARNESS_STATE/deploy.pid" 2>/dev/null)
  while [[ -n $pg ]] && pgrep -g "$pg" >/dev/null 2>&1 && (( i++ < 300 )); do sleep 0.2; done
  (( i > 1 )) && say "  (waited $((i / 5)) s for commands left in deploy.sh's process group)"
  cp "$HARNESS_STATE/trace.log" "$OUT/$SCEN.run$RUN_NO.trace"
  say "  exit code $RC after $((SECONDS - T0)) s; output: $(basename "$LOG")"
  grep -E '==>|!!|[Ff]ail|[Rr]estor|interrupted|Interrupted|healthy|not running|unavailable|Production|smoke (prod|staging)|Rolling|live|Removed|Another deploy|refuse|exists' "$LOG" \
    | grep -v '^ *ok ' | sed 's/^/  | /' | head -n 40 | tee -a "$OUT/$SCEN.txt" >/dev/null
}

serving() { curl -s -m 2 "http://127.0.0.1:$PROD_PORT/" | tr -d '\n' || true; }

# state [label]: containers, images, deploy log, proxy upstream, what PROD_PORT serves
state() {
  say "  -- state ${1:-}"
  $D ps -a --filter "name=^/$APP" --format '     ctr {{.Names}}  {{.Image}}  {{.State}}  ({{.Status}})' | sed 's/caddy:2.11.9-alpine@sha256:[0-9a-f]*/caddy/' | sort | tee -a "$OUT/$SCEN.txt"
  $D images "$APP" --format '     img {{.Repository}}:{{.Tag}}' | sort | tee -a "$OUT/$SCEN.txt"
  if [[ -f $DEPLOY_LOG ]]; then awk '{print "     log " $1 " " $2 " " substr($3, 1, 12)}' "$DEPLOY_LOG" | tee -a "$OUT/$SCEN.txt"; else say "     log (none)"; fi
  say "     upstream: $(cat "$SW/state/proxy/upstream.caddy" 2>/dev/null || echo none)"
  local s; s=$(serving)
  say "     GET :$PROD_PORT -> ${s:-NOTHING}"
}

settle() { sleep "${1:-4}"; }

check() {  # check <description> <command...>
  local what=$1; shift
  if "$@"; then say "  PASS $what"; else say "  FAIL $what"; FAILS=$((FAILS + 1)); fi
}

serves() { local i; for i in $(seq 1 20); do [[ "$(serving)" == "ok $1" ]] && return 0; sleep 0.25; done; return 1; }
serves_any() { [[ "$(serving)" == "ok "* ]]; }
running() { [[ "$($D container inspect -f '{{.State.Running}}' "$1" 2>/dev/null)" == true ]]; }
stopped() { [[ "$($D container inspect -f '{{.State.Running}}' "$1" 2>/dev/null)" == false ]]; }
no_ctr() { ! $D container inspect "$1" >/dev/null 2>&1; }
has_img() { $D image inspect "$APP:$1" >/dev/null 2>&1; }
no_img() { ! has_img "$1"; }
image_of() { $D container inspect -f '{{.Config.Image}}' "$1" 2>/dev/null | sed "s|^$APP:||"; }
live() { awk '$1 == "to" { sub(/:3000$/, "", $2); print $2 }' "$SW/state/proxy/upstream.caddy" 2>/dev/null; }
logged_last() { tail -n 1 "$DEPLOY_LOG" 2>/dev/null | awk '{print $2}'; }
log_lines() { [[ "$(wc -l < "$DEPLOY_LOG" 2>/dev/null || echo 0)" == "$1" ]]; }
latest_is() { [[ "$($D image inspect -f '{{.Id}}' "$APP:latest" 2>/dev/null)" == "$($D image inspect -f '{{.Id}}' "$APP:$1" 2>/dev/null)" ]]; }
# Exactly the expected containers exist: proxy, colours, kept legacy; nothing else (no blocker, no strays).
only_expected_ctrs() {
  local extra
  extra=$($D ps -a --filter "name=^/$APP" --format '{{.Names}}' | grep -vxE "$APP-proxy|$APP-blue|$APP-green|$APP-legacy" || true)
  [[ -z $extra ]] || { say "     unexpected containers: $extra"; return 1; }
}
one_running_colour_or_both() { running "$APP-blue" || running "$APP-green"; }
live_runs() { local l; l=$(live); [[ -n $l ]] && running "$l"; }

# Traffic: requests every few ms (and slow ones that cross switches) against PROD_PORT.
traffic_start() {
  rm -f "$HARNESS_STATE/traffic.stop"
  python3 /h/traffic.py "http://127.0.0.1:$PROD_PORT" "$HARNESS_STATE/traffic.stop" "$OUT/$SCEN.traffic$1.json" \
    > "$OUT/$SCEN.traffic$1.out" 2>&1 &
  TRAFFIC_PID=$!
  sleep 1
}
traffic_stop() {
  touch "$HARNESS_STATE/traffic.stop"
  wait "$TRAFFIC_PID" 2>/dev/null
  say "  traffic: $(cat "$OUT/$SCEN.traffic$1.out")"
}
traffic_failures() { python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["failed"])' "$OUT/$SCEN.traffic$1.json"; }
# Failed requests that did not start within 2 s after a `caddy reload` (traced by bin/docker).
# A reload closes Caddy's idle connections, so a request started at that instant can fail
# (deploy/RUNBOOK.md); any other failure is a bug.
traffic_failures_apart_from_reloads() {
  python3 - "$OUT/$SCEN.traffic$1.json" "$OUT/$SCEN".run*.trace <<'EOF'
import json, sys
failures = json.load(open(sys.argv[1]))['failures']
reloads = [float(line.split()[1]) for trace in sys.argv[2:] for line in open(trace) if ' caddy reload ' in line]
print(len([f for f in failures if not any(0 <= f['ts'] - r <= 2 for r in reloads)]))
EOF
}
other() { if [[ $1 == "$APP-blue" ]]; then echo "$APP-green"; else echo "$APP-blue"; fi; }
