#!/usr/bin/env python3
"""Claude Stop/SessionEnd and Codex Stop hook: start `observe collect --root <platform> --all-enabled` detached.

Every capture-enabled workspace (platform root or registered project) is collected, even when the
platform root's own capture is off.

Returns at once and always exits 0, so a slow or failing collection never blocks the session.
The command is fixed; nothing from the hook input is used, and the input is not read or logged.
"""
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def command(root=ROOT, uv=None):
    uv = uv or shutil.which('uv')
    if not uv:
        return None
    return [uv, '--directory', str(root / 'mcp-server'), 'run', '--locked',
            'agent-platform-agent', 'observe', 'collect', '--root', str(root), '--all-enabled']


def launch(root=ROOT):
    argv = command(root)
    if argv is None:
        return False
    try:
        subprocess.Popen(argv, cwd=root, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError:
        return False
    return True


def main():
    launch()  # No output: no decision or message, the hook never changes the session.
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
