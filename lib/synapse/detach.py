#!/usr/bin/env python3
"""
detach.py — start the on-exit extraction as a detached headless Claude session.

[extract] on_exit = true: after the SessionEnd auto archive, run
`claude -p "/synapse:extract-session ID --project P"` on Sonnet in a process
that outlives the ending session. Never waits, never raises. The child runs
with SYNAPSE_DETACHED=1 and hooks off, so it cannot archive or nudge. Its
output goes to <home>/state/extract-<id>.log (JSON result with total_cost_usd).
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paths  # noqa: E402

ALLOWED_TOOLS = ("Bash(synapse extract *) Bash(synapse vault *) Bash(synapse where *) "
                 "Bash(synapse shared status*) Bash(rm -rf *.claude-work/.tmp/extract-*) "
                 "Read Write Edit Agent")


def command(claude: str, session_id: str, project: str) -> list[str]:
    prompt = (f"/synapse:extract-session {session_id} --project {project}\n"
              "Non-interactive run, nobody can answer: accept mode is auto. Write every proposal "
              "with --review-batch and never ask.")
    cmd = [claude, "-p", prompt,
           "--model", "sonnet", "--output-format", "json",
           "--allowedTools", ALLOWED_TOOLS,
           "--settings", '{"disableAllHooks":true}']
    root = os.environ.get("SYNAPSE_PLUGIN_DIR")   # spike/dev override; installed plugin otherwise
    if root:
        cmd += ["--plugin-dir", root]
    return cmd


def spawn_extract(cwd: Path, project: str, session_id: str) -> bool:
    """Start the detached extraction. True if a process was started."""
    if os.environ.get("SYNAPSE_DETACHED"):
        return False
    claude = shutil.which("claude")
    if not claude:
        return False
    try:
        log_path = paths.detached_log(session_id)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ, SYNAPSE_DETACHED="1")
        bin_dir = str(Path(__file__).resolve().parent.parent.parent / "bin")
        env["PATH"] = bin_dir + os.pathsep + env.get("PATH", "")
        kwargs: dict = {}
        if os.name == "nt":
            kwargs["creationflags"] = (subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
                                       | subprocess.CREATE_NO_WINDOW)
        else:
            kwargs["start_new_session"] = True
        with open(log_path, "ab") as log:
            subprocess.Popen(command(claude, session_id, project), cwd=str(cwd), env=env,
                             stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                             close_fds=True, **kwargs)
        return True
    except Exception:   # never block the exit
        return False
