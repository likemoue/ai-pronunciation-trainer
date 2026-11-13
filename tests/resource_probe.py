"""Peak memory of the subprocesses a block of code starts (Linux; a no-op elsewhere).

While the block runs, every process started with subprocess.Popen is watched:
its own high-water mark (VmHWM in /proc/<pid>/status) is read every few
milliseconds until it exits. RUSAGE_CHILDREN is not used because a child's
ru_maxrss includes the parent's size at fork, which in a full test run hides
anything under ~600 MB.
"""
import contextlib
import os
import subprocess
import threading
import time

_HAS_PROC = os.path.exists('/proc/self/status')


def _peak_rss(pid):
    """VmHWM of a running process in bytes, or None once it has exited."""
    try:
        with open(f'/proc/{pid}/status') as f:
            for line in f:
                if line.startswith('VmHWM:'):
                    return int(line.split()[1]) * 1024
    except OSError:
        pass
    return None  # gone, or a zombie (which has no memory left)


class ChildPeak:
    def __init__(self):
        self.peak = 0
        self.processes = 0

    def assert_below(self, limit_bytes: int):
        """Every process started in the block peaked below limit_bytes."""
        if not _HAS_PROC:
            return  # not measurable on this platform
        assert self.processes, 'no subprocess was started'
        assert self.peak < limit_bytes, f'child peak {self.peak / 2 ** 20:.0f} MiB'


@contextlib.contextmanager
def child_peak_rss():
    peak = ChildPeak()
    if not _HAS_PROC:
        yield peak
        return
    real_popen = subprocess.Popen
    watchers = []

    def watch(pid):
        while True:
            value = _peak_rss(pid)
            if value is None:
                return
            peak.peak = max(peak.peak, value)
            time.sleep(0.002)

    class WatchedPopen(real_popen):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            peak.processes += 1
            watcher = threading.Thread(target=watch, args=(self.pid,), daemon=True)
            watcher.start()
            watchers.append(watcher)

    subprocess.Popen = WatchedPopen
    try:
        yield peak
    finally:
        subprocess.Popen = real_popen
        for watcher in watchers:
            watcher.join(10)
