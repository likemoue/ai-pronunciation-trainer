"""Peak memory of child processes (Linux and macOS; a no-op on Windows)."""
import contextlib
import sys

try:
    import resource
except ImportError:  # Windows
    resource = None

# ru_maxrss is in bytes on macOS and in KiB on Linux.
_SCALE = 1 if sys.platform == 'darwin' else 1024


class ChildPeak:
    def __init__(self):
        self.before = self.after = self.parent = None

    def assert_below(self, extra_bytes: int):
        """The children that ended inside the block peaked below the parent's
        own peak plus extra_bytes. (A child shares the parent's memory between
        fork and exec, so its peak is never lower than the parent's size.)"""
        if self.after is None or self.after <= self.before:
            return  # not measurable here, or no child peaked higher than an earlier one
        assert self.after < self.parent + extra_bytes, (
            f'child peak {self.after / 2 ** 20:.0f} MiB, parent peak {self.parent / 2 ** 20:.0f} MiB')


@contextlib.contextmanager
def child_peak_rss():
    peak = ChildPeak()
    if resource is not None:
        peak.before = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss * _SCALE
    yield peak
    if resource is not None:
        peak.after = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss * _SCALE
        peak.parent = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * _SCALE
