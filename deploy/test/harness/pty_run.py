#!/usr/bin/env python3
"""pty_run.py CMD...: run CMD as the session leader of a new pty, like a login over SSH.

When $HARNESS_STATE/hangup-now appears (bin/fire with FAULT_SIG_TO=hangup), the pty master is
closed, so the kernel hangs up the terminal and sends SIGHUP to the session, exactly as when an
SSH connection drops. Output read from the pty goes to stdout. Exits with CMD's status
(128+N when it was killed by signal N).
"""
import os, pty, select, sys, time

flag = os.path.join(os.environ['HARNESS_STATE'], 'hangup-now')
pid, fd = pty.fork()
if pid == 0:
    os.execvp(sys.argv[1], sys.argv[1:])

open_fd = True
while True:
    if open_fd:
        if os.path.exists(flag):
            sys.stdout.write('\n[pty_run] closing the pty master at %s (SSH session drops)\n' % time.strftime('%T'))
            sys.stdout.flush()
            os.close(fd)
            open_fd = False
            continue
        ready, _, _ = select.select([fd], [], [], 0.05)
        if ready:
            try:
                data = os.read(fd, 65536)
            except OSError:
                data = b''
            if data:
                sys.stdout.buffer.write(data)
                sys.stdout.flush()
    done, status = os.waitpid(pid, os.WNOHANG)
    if done:
        break
    if not open_fd:
        time.sleep(0.05)
if os.WIFSIGNALED(status):
    sys.exit(128 + os.WTERMSIG(status))
sys.exit(os.WEXITSTATUS(status))
