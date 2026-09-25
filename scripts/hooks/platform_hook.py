#!/usr/bin/env python3
"""Bounded project hooks. Never evaluate command input or log prompt/tool bodies."""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIMIT = 1024 * 1024


def deny(reason):
    return {'hookSpecificOutput': {'hookEventName': 'PreToolUse', 'permissionDecision': 'deny',
                                   'permissionDecisionReason': reason}}


def note(event, message):
    if event in ('SessionStart', 'UserPromptSubmit'):
        return {'hookSpecificOutput': {'hookEventName': event, 'additionalContext': message}}
    return {'systemMessage': message}


def handle(data):
    event = data.get('hook_event_name')
    if event == 'PreToolUse':
        payload = data.get('tool_input')
        command = payload.get('command') if isinstance(payload, dict) else None
        if not isinstance(command, str):
            return deny('Malformed command input; guard could not inspect the command.')
        if re.search(r'(rm\s+-rf\s+/(?:\s|$)|sudo\s+rm|DROP\s+DATABASE|TRUNCATE\s+TABLE)', command, re.I):
            return deny('High-risk destructive command blocked by project policy.')
    elif event == 'UserPromptSubmit':
        prompt = data.get('prompt', '')
        if isinstance(prompt, str) and re.search(r'(API_KEY|SECRET|PASSWORD|TOKEN)=\S+', prompt, re.I):
            return note(event, 'Possible secret in prompt: do not copy it to files or reports; review rotation if genuine.')
    elif event == 'SessionStart':
        # Agent synchronization does not read environment/credential files.
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/sync_claude_settings.py'), '--agents-only'],
                                cwd=ROOT, capture_output=True, timeout=8)
        if result.returncode:
            return note(event, 'Platform agent synchronization failed. Run doctor; inspect agent source/adapter consistency.')
        if data.get('source') == 'startup':
            return note(event, 'Use only task-relevant context and role skills; graphify first, then bounded retrieval if needed. '
                        'Inspect measured usage with observe efficiency --root <explicit-root>. Keep required verification; never infer token savings.')
    elif event == 'PostToolUse':
        value = (data.get('tool_input') or {}).get('file_path')
        if not isinstance(value, str):
            return {}
        path = Path(value)
        cwd = Path(data.get('cwd') or ROOT)
        if not path.is_absolute():
            path = cwd / path
        # Never traverse a tool-provided symlink or inspect a protected file.
        if any(p.is_symlink() for p in (path, *path.parents)):
            return note(event, 'Skipped post-edit check for a symlink path.')
        lowered = path.name.lower()
        if any(x in lowered for x in ('.env', '.pem', '.key', 'credential', 'secret')):
            return {}
        warnings = []
        if path.suffix == '.kt' and shutil.which('ktlint'):
            result = subprocess.run(['ktlint', str(path)], capture_output=True, timeout=8)
            if result.returncode:
                warnings.append('Kotlin lint failed; run the project lint command for details.')
        if path.suffix == '.md' and 'docs' in path.parts and path.is_file():
            with path.open() as stream:
                if stream.readline(1024).strip() != '---':
                    warnings.append('Edited artifact is missing YAML front-matter.')
        if warnings:
            return note(event, ' '.join(warnings))
    return {}


def main():
    raw = sys.stdin.read(LIMIT + 1)
    try:
        if len(raw) > LIMIT:
            raise ValueError('oversized input')
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError('invalid payload')
    except ValueError:
        print(json.dumps(deny('Invalid hook input; command guard cannot verify this request.')))
        return
    try:
        result = handle(data)
    except (OSError, ValueError, TypeError, AttributeError, subprocess.TimeoutExpired):
        result = deny('Command guard failed.') if data.get('hook_event_name') == 'PreToolUse' else note(
            data.get('hook_event_name'), 'Platform hook check failed or timed out; verification remains unknown.')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
