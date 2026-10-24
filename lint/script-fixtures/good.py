"""Nothing here may be flagged."""
from __future__ import annotations

import subprocess


def run(args: list[str], use_shell: bool = False) -> int:
    # shell=True would be wrong here, the text in this comment is not code
    note = "shell=True"
    r = subprocess.run(args, capture_output=True, text=True, timeout=30, shell=False)
    subprocess.run(args, timeout=30, shell=use_shell)
    subprocess.run('a | b', shell=True, timeout=30)  # core-exception: EXC-003
    return r.returncode if note else 1
