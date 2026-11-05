"""Process-group watchdog: elapsed wall time and combined descendant RSS."""
from pathlib import Path
import os
import signal
import subprocess
import time
import psutil
from .study import atomic_json


def run_budgeted(command, log, seconds=1200., memory_gib=8.):
    if not 0 < seconds <= 1200 or memory_gib <= 0:
        raise ValueError("local campaign must allow at most 1200 seconds and positive memory")
    log = Path(log); log.parent.mkdir(parents=True, exist_ok=True)
    start, peak, reason = time.monotonic(), 0, None
    with log.open("w") as stream:
        process = subprocess.Popen(command, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
        observed = psutil.Process(process.pid)
        try:
            while process.poll() is None:
                try:
                    rss = observed.memory_info().rss + sum(p.memory_info().rss for p in observed.children(recursive=True) if p.is_running())
                    peak = max(peak, rss)
                except psutil.NoSuchProcess:
                    rss = 0
                if time.monotonic()-start >= seconds:
                    reason = "wall_time_limit"
                elif rss > memory_gib*1024**3:
                    reason = "memory_limit"
                if reason:
                    os.killpg(process.pid, signal.SIGTERM)
                    try: process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL); process.wait()
                    break
                time.sleep(0.1)
        except BaseException:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL); process.wait()
            raise
    result = dict(command=command, seconds=time.monotonic()-start, peak_rss_gib=peak/1024**3,
                  returncode=process.returncode, stopped_by=reason, limit_seconds=seconds, limit_gib=memory_gib)
    atomic_json(log.with_suffix(".budget.json"), result)
    return result

