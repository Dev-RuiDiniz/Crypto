from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path
from typing import Optional


CREATE_NEW_PROCESS_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)


def spawn_process(
    cmd: list[str],
    *,
    cwd: Optional[Path] = None,
    env: Optional[dict[str, str]] = None,
) -> subprocess.Popen:
    creationflags = CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    popen_kwargs = {
        "cwd": str(cwd) if cwd else None,
        "env": env,
        "creationflags": creationflags,
    }
    if os.name != "nt":
        popen_kwargs["start_new_session"] = True
    return subprocess.Popen(cmd, **popen_kwargs)


def terminate_process(proc: subprocess.Popen, timeout_sec: float = 10.0) -> None:
    if proc.poll() is not None:
        return

    try:
        if os.name == "nt":
            proc.terminate()
        else:
            os.killpg(proc.pid, signal.SIGTERM)
    except Exception:
        proc.terminate()

    try:
        proc.wait(timeout=timeout_sec)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=3)


def current_python() -> str:
    return sys.executable
