"""Bounded child process groups with heartbeats and signal cleanup."""

import os
import signal
import subprocess
import threading
import time


class ProcessInterrupted(RuntimeError):
    interrupted = True


def run(command, *, cwd, timeout, pulse=None, shell=False):
    process = subprocess.Popen(command, cwd=cwd, shell=shell, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True, start_new_session=True)
    previous = None
    installed = threading.current_thread() is threading.main_thread()
    def terminate(_signum, _frame):
        raise ProcessInterrupted("execution interrupted by signal")
    if installed:
        previous = signal.signal(signal.SIGTERM, terminate)
    deadline = time.monotonic() + timeout
    try:
        while True:
            if pulse:
                pulse(process.pid)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(command, timeout)
            try:
                stdout, stderr = process.communicate(timeout=min(5, remaining))
                return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
            except subprocess.TimeoutExpired:
                if time.monotonic() >= deadline:
                    raise
    except BaseException:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.communicate()
        raise
    finally:
        if installed:
            signal.signal(signal.SIGTERM, previous)
