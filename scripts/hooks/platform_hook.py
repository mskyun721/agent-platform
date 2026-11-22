#!/usr/bin/env python3
"""Bounded project hooks. Never evaluate command input or log prompt/tool bodies."""
import json
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIMIT = 1024 * 1024


def deny(reason):
    return {'hookSpecificOutput': {'hookEventName': 'PreToolUse', 'permissionDecision': 'deny',
                                   'permissionDecisionReason': reason}}


def ask(reason):
    return {'hookSpecificOutput': {'hookEventName': 'PreToolUse', 'permissionDecision': 'ask',
                                   'permissionDecisionReason': reason}}


# Commands that widen or move the MCP boundary (workspaces, registered paths, default):
# only the user runs them. Agents must ask instead of running them via Bash. Read-only
# and preview forms (project-list, project-publish-show, project-workspace list,
# project-migrate --dry-run, doctor, gate-check) pass without a prompt, and so does any
# command that only mentions a CLI name (grep, rg, git log --grep, cat, man ...).
# `project-<x>-set` (publish-set today, spec-set later) also writes .agent-projects.json.
BOUNDARY_CLI = re.compile(r'project-(?:workspace (?:add|remove)|add|register|unregister|rebind|migrate|use'
                          r'|[a-z][a-z0-9]*(?:-[a-z0-9]+)*-set)')
CLI_NAMES = ('agent-platform-agent', 'apa', 'agent_platform_mcp.cli')
# Programs that run the command named later in their argv (`uv run X`, `python -m X`, ...).
LAUNCHERS = re.compile(r'uvx?|poetry|pipx|python[\d.]*|time|nice|nohup|timeout|xargs|npx')
SHELLS = ('sh', 'bash', 'zsh', 'dash')
# Boundary files (case-insensitive: macOS file systems are). The migration marker counts:
# without it a deleted registry would turn the deprecated env fallback back on.
_NAMES = r'\.agent-projects\.(?:json|lock)|\.active-project\.migrated[\w.]*'
REGISTRY = re.compile(rf'(?:^|/)(?:{_NAMES})$', re.I)
REGISTRY_TEXT = re.compile(rf'(?:{_NAMES})\b', re.I)
REDIRECT_TO_REGISTRY = re.compile(rf'>>?\|?\s*["\']?[^\s"\';|&>]*(?:{_NAMES})\b', re.I)
SEGMENT = re.compile(r'\|\||&&|[;|\n]')
SCRIPT_RUNNER = re.compile(r'\b(?:python[\d.]*|node)\b')
SCRIPT_WRITE = re.compile(r'open\([^)]*["\'](?:[wax]b?\+?|r\+b?|rb\+)["\']|write_text|write_bytes'
                          r'|\bos\.(?:remove|unlink|replace|rename|renames|truncate)\b|\bshutil\.\w+'
                          r'|\.(?:unlink|rename|replace|touch)\(|(?:writeFile|appendFile|unlink|rename|rm|copyFile)Sync\b')


def _is_registry(token):
    return bool(REGISTRY.search(token.strip('"\'')))


def _words(segment):
    """Shell words of one segment; text after an unquoted `#` is a comment and dropped."""
    try:
        words = shlex.split(segment, comments=True)
    except ValueError:
        words = segment.split('#', 1)[0].split()
    while words and (words[0] in ('sudo', 'command', 'env', 'exec') or re.fullmatch(r'\w+=\S*', words[0])):
        words = words[1:]
    return words


def _writes_registry(command):
    """True only when a boundary file is the write target, never when it is only read."""
    if not REGISTRY_TEXT.search(command):
        return False
    if REDIRECT_TO_REGISTRY.search(command):
        return True
    if SCRIPT_RUNNER.search(command) and SCRIPT_WRITE.search(command):
        return True  # inline `python -c`/`node -e`/heredoc that names the registry and writes, moves or deletes
    for segment in SEGMENT.split(command):
        words = _words(segment)
        if not words:
            continue
        tool, args = Path(words[0]).name, words[1:]
        operands = [arg for arg in args if not arg.startswith('-')]
        named = any(_is_registry(arg) for arg in operands)
        if tool in ('tee', 'mv', 'rm', 'truncate', 'unlink', 'shred') and named:
            return True  # mv: the source vanishes too
        if tool in ('cp', 'install', 'ln', 'rsync') and operands and _is_registry(operands[-1]):
            return True
        if tool == 'dd' and any(arg.startswith('of=') and _is_registry(arg[3:]) for arg in args):
            return True
        if tool == 'find' and {'-delete', '-exec', '-execdir', '-ok'} & set(args) and REGISTRY_TEXT.search(segment):
            return True
        in_place = any(re.fullmatch(r'-[a-zA-Z]*i\S*|--in-place\S*', arg) for arg in args)
        if tool in ('sed', 'gsed', 'perl') and in_place and any(_is_registry(arg) for arg in args):
            return True
    return False


def _cli_args(words):
    """Arguments after the platform CLI when `words` actually runs it, else None."""
    if not words:
        return None
    tool = Path(words[0].lstrip('$(`')).name
    if tool in CLI_NAMES:
        return words[1:]
    if LAUNCHERS.fullmatch(tool):
        for index, word in enumerate(words[1:], 1):
            if Path(word).name in CLI_NAMES:
                return words[index + 1:]
    return None


def _changes_boundary(command, depth=0):
    for segment in SEGMENT.split(command):
        words = _words(segment)
        if not words:
            continue
        tool = Path(words[0]).name
        nested = (words[words.index('-c') + 1:words.index('-c') + 2] if tool in SHELLS and '-c' in words
                  else [' '.join(words[1:])] if tool == 'eval' else [])
        if depth < 3 and any(_changes_boundary(text, depth + 1) for text in nested):
            return True
        if (tool == 'setup.sh' or tool in SHELLS and words[1:2] and Path(words[1]).name == 'setup.sh') and any(
                re.fullmatch(r'--(?:roots|target)(?:=.*)?', word) for word in words):
            return True
        args = _cli_args(words)
        positional = [arg for arg in args or () if not arg.startswith('-')]
        if not positional:
            continue
        name = ' '.join(positional[:2]) if positional[0] == 'project-workspace' else positional[0]
        if BOUNDARY_CLI.fullmatch(name) and not (name == 'project-migrate' and '--dry-run' in args):
            return True
    return False


EDIT_TOOLS = ('Write', 'Edit', 'MultiEdit', 'NotebookEdit')
BOUNDARY_REASON = ('Changes the agent-platform project boundary (.agent-projects.json). '
                   'Only the user may do this: ask the user to run it in their own terminal.')


def _guarded_edit(path):
    """Boundary files and the Claude settings that hold the deny rules (case-insensitive)."""
    name, parent = path.name.lower(), path.parent.name.lower()
    return (name.startswith(('.agent-projects', '.active-project.migrated'))
            or parent == '.claude' and re.fullmatch(r'settings.*\.json', name) is not None)


CAPTURE_TOOL = 'mcp__agent-platform__observe_capture'
CAPTURE_REASON = ('Turns on local storage of prompt/response text (7-day retention). '
                  'Only on the user\'s explicit request: confirm with the user first.')


def _captures_on(command):
    """`agent-platform-agent observe capture on ...` run through Bash."""
    for segment in SEGMENT.split(command):
        positional = [arg for arg in _cli_args(_words(segment)) or () if not arg.startswith('-')]
        if positional[:3] == ['observe', 'capture', 'on']:
            return True
    return False


def guard_tool(data):
    payload = data.get('tool_input')
    if data.get('tool_name') == CAPTURE_TOOL:
        # `off` and the preview (confirm absent or false) change nothing; any other confirm value asks.
        on = isinstance(payload, dict) and payload.get('mode') == 'on' and payload.get('confirm', False) is not False
        return ask(CAPTURE_REASON) if on else {}
    if data.get('tool_name') in EDIT_TOOLS:
        target = payload.get('file_path') or payload.get('notebook_path') if isinstance(payload, dict) else None
        if not isinstance(target, str):
            return deny('Malformed edit input; guard could not inspect the target path.')
        return ask(BOUNDARY_REASON) if _guarded_edit(Path(target)) else {}
    command = payload.get('command') if isinstance(payload, dict) else None
    if not isinstance(command, str):
        return deny('Malformed command input; guard could not inspect the command.')
    if re.search(r'(rm\s+-rf\s+/(?:\s|$)|sudo\s+rm|DROP\s+DATABASE|TRUNCATE\s+TABLE)', command, re.I):
        return deny('High-risk destructive command blocked by project policy.')
    if _changes_boundary(command) or _writes_registry(command):
        return ask(BOUNDARY_REASON)
    if _captures_on(command):
        return ask(CAPTURE_REASON)
    return {}


def note(event, message):
    if event in ('SessionStart', 'UserPromptSubmit'):
        return {'hookSpecificOutput': {'hookEventName': event, 'additionalContext': message}}
    return {'systemMessage': message}


def handle(data):
    event = data.get('hook_event_name')
    if event == 'PreToolUse':
        return guard_tool(data)
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
            # Presence checks only; the environment file is never opened here.
            skills = ROOT / '.claude/skills'
            installed = skills.is_dir() and any(p.name != 'graphify' for p in skills.iterdir() if p.is_dir())
            if not (ROOT / '.env').is_file() or not installed:
                return note(event, 'agent-platform is not set up in this checkout. Tell the user to run '
                            '`./scripts/setup.sh` (see standards/reference/getting-started.md) before using MCP tools or skills.')
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
