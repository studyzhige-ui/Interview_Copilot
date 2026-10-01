"""Linux test-only liveness checks that tolerate a process exiting during read.

ENOENT and ESRCH both mean the selected PID is gone. Permission and other I/O
errors must remain test failures; never turn an unreadable live process into a
successful cleanup assertion. A zombie has exited and cannot execute model work.
"""

from pathlib import Path


def process_stopped(pid: int) -> bool:
    try:
        status = Path(f"/proc/{pid}/status").read_text()
    except (FileNotFoundError, ProcessLookupError):
        return True
    return any(
        line.startswith("State:") and line.split()[1] == "Z"
        for line in status.splitlines()
    )
