#!/usr/bin/env python3
"""traffic_check.py: verdicts on the requests that traffic.py sent (lib.sh).

traffic_check.py none TRAFFIC.json TRACE...
    Requests were sent throughout, and none failed, with one exception: a `caddy reload` can
    reset a connection that reaches the proxy at that instant, even a new one (3 of about
    70,000 requests in one full run; in a test of Caddy alone, 2-7 per 100 reloads). Such a
    failure is excused: a connection reset or closed without an answer, never an HTTP error,
    failing within RESET_SECONDS, that started during a reload that reached Caddy or less than
    RELOAD_GRACE seconds after it, at most PER_RELOAD per reload. bin/docker traces the start
    and the end of each reload. With traffic.py's full traffic, it also checks that the drain
    was tested: a long request was in flight on a colour when it was stopped, and an upload
    was still sending its body during a reload.

traffic_check.py move TRAFFIC.json TRACE LOG APP SECONDS
    The move of the single container APP behind the proxy, in the deploy that TRACE and LOG are
    from. deploy.sh prints how long the port refused new connections (from just before the
    `docker stop` of APP until the proxy answered): at most SECONDS. Every failed request must
    have started in that window, counted from the traced `docker stop`, and failed at the
    connection: the proxy itself never answers with an error.

Prints what it found, indented for the scenario's .txt; exits 1 if the check fails.
"""
import json
import re
import sys

MIN_REQUESTS = 100  # traffic.py sends more than 100 a second
MARGIN = 1.0  # seconds between deploy.sh's clock readings and the traced docker commands
RESET_ERRORS = ('ConnectionResetError', 'Connection reset by peer', 'RemoteDisconnected')
RESET_SECONDS = 0.5
RELOAD_GRACE = 0.5
PER_RELOAD = 2


def load(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError) as error:
        print(f'     no results from traffic.py: {error}')
        sys.exit(1)


def reloads(traces):
    """(start, end, run) of each `caddy reload` that reached Caddy, from bin/docker's traces: from
    the moment it began (after traffic.py's probes were sent) until it returned."""
    done = []
    for path in traces:
        run = path.rsplit('.', 2)[-2]
        start = None
        with open(path) as f:
            for line in f:
                fields = line.split()
                if (' docker exec ' in line and ' caddy reload ' in line) or ' reload-begins' in line:
                    start = float(fields[1])
                elif ' reload-done ' in line and start is not None:
                    done.append((start, float(fields[1]), run))
                    start = None
    return sorted(done)


def describe(failure, origin=None, windows=()):
    text = (f"{failure['t']} {failure['path']}, failed after {failure['after_s']:.2f} s: "
            f"{failure['error'][:100]}")
    if origin is not None:
        return f'{text} (+{failure["ts"] - origin:.2f} s)'
    soon = [window for window in windows if 0 < window[0] - failure['ts'] <= 1]
    before = [window for window in windows if window[0] <= failure['ts']]
    if soon:  # a reload probe (traffic.py) or a request sent just before a reload
        start, end, run = soon[0]
        text += f' ({start - failure["ts"]:.2f} s before the reload of {run} began, {end - start:.2f} s long)'
    elif before:
        start, end, run = before[-1]
        text += f' ({failure["ts"] - start:.2f} s after the reload of {run} began, {end - start:.2f} s long)'
    return text


def at_reload(failure, windows):
    """The reload whose listener hand-over can explain this failure, if any."""
    if failure['after_s'] > RESET_SECONDS or not any(error in failure['error'] for error in RESET_ERRORS):
        return None
    for window in windows:
        if window[0] <= failure['ts'] <= window[1] + RELOAD_GRACE:
            return window
    return None


def colour_stops(traces):
    """Times of the `docker stop` of a colour, from bin/docker's traces."""
    stop = re.compile(r' docker stop -t \S+ \S+-(blue|green)$')
    times = []
    for path in traces:
        with open(path) as f:
            times += [float(line.split()[1]) for line in f if stop.search(line.rstrip())]
    return sorted(times)


def coverage(data, windows, stops):
    """Did the full traffic test the drain? (long requests in flight on a colour when it was
    stopped, uploads still sending their body during a reload), as text, and whether it did."""
    in_flight = 0
    for long_start, long_end in data['long']:
        for stop in stops:
            before = [window for window in windows if window[1] < stop]
            # Sent to the colour that the last reload before the stop took the traffic off:
            # started after the reload before that one, and before this one.
            if (before and long_end > stop and long_start < before[-1][0]
                    and (len(before) < 2 or long_start > before[-2][1])):
                in_flight += 1
                break
    straddling = sum(1 for start, sent, _ in data['uploads']
                     if any(start < window[0] and sent > window[1] for window in windows))
    text = (f'{in_flight} long requests were in flight on a colour when it was stopped; '
            f'{straddling} uploads were sending their body during a reload ({data.get("reload_probes", 0)} reloads probed)')
    return text, (in_flight > 0 or not stops) and (straddling > 0 or not windows)


def none(traffic, traces):
    data = load(traffic)
    windows = reloads(traces)
    failures = data['failures']
    excused, counted, per_reload = [], [], {}
    for failure in failures:
        window = at_reload(failure, windows)
        if window is not None and per_reload.get(window, 0) < PER_RELOAD:
            per_reload[window] = per_reload.get(window, 0) + 1
            excused.append(failure)
        else:
            counted.append(failure)
    print(f"     {data['total']} requests, {len(failures)} failed"
          + (f', {len(excused)} of them reset at a Caddy reload (excused)' if excused else ''))
    for failure in excused:
        print('     reset at a reload: ' + describe(failure, windows=windows))
    for failure in counted[:20]:
        print('     failed: ' + describe(failure, windows=windows))
    if len(counted) > 20:
        print(f'     ... and {len(counted) - 20} more (the .json has them all)')
    if data['total'] < MIN_REQUESTS:
        print(f'     too few requests: traffic.py did not run throughout (at least {MIN_REQUESTS})')
        return False
    if data.get('full'):
        # Only the reloads and stops while traffic.py ran.
        during = [window for window in windows if data['began'] <= window[0] and window[1] <= data['ended']]
        stops = [stop for stop in colour_stops(traces) if data['began'] <= stop <= data['ended']]
        text, covered = coverage(data, during, stops)
        print('     ' + text)
        if not covered:
            print('     so the drain of the colour that loses the traffic was not tested')
            return False
    return not counted


def move(traffic, trace, log, app, bound):
    data = load(traffic)
    failures = data['failures']
    stop = re.compile(r' docker stop (-t \S+ )?' + re.escape(app) + '$')
    with open(trace) as f:
        stops = [float(line.split()[1]) for line in f if stop.search(line.rstrip())]
    with open(log) as f:
        said = re.search(r'refused new connections for ([0-9.]+) s', f.read())
    if not stops or not said:
        print(f'     no traced `docker stop {app}`, or deploy.sh did not say how long the port was unavailable')
        return False
    start, outage = stops[0], float(said.group(1))
    ok = True
    print(f'     deploy.sh: the port refused new connections for {outage} s (at most {bound} s); '
          f"{len(failures)} of {data['total']} requests failed")
    if outage > bound:
        print(f'     the move took longer than {bound} s')
        ok = False
    if failures:
        offsets = [failure['ts'] - start for failure in failures]
        print(f'     they started from {min(offsets):+.2f} s to {max(offsets):+.2f} s after the `docker stop {app}`')
    outside = [failure for failure in failures
               if not -MARGIN / 2 <= failure['ts'] - start <= outage + MARGIN]
    answered = [failure for failure in failures if failure['error'].startswith('HTTPError')]
    for what, which in (('outside the move', outside), ('answered with an HTTP error', answered)):
        if which:
            ok = False
            print(f'     {len(which)} failed {what}:')
            for failure in which[:10]:
                print('       ' + describe(failure, origin=start))
    if data['total'] < MIN_REQUESTS:
        print(f'     too few requests: traffic.py did not run throughout (at least {MIN_REQUESTS})')
        ok = False
    return ok


if __name__ == '__main__':
    command, args = sys.argv[1], sys.argv[2:]
    if command == 'none':
        passed = none(args[0], args[1:])
    elif command == 'move':
        passed = move(args[0], args[1], args[2], args[3], float(args[4]))
    else:
        sys.exit(f'unknown command {command}')
    sys.exit(0 if passed else 1)
