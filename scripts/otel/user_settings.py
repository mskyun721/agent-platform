#!/usr/bin/env python3
"""`setup.sh --otel`: show, then apply on explicit confirmation, the OTel settings of the user's CLIs.

User-run only (agents never run it). Claude: the `scripts/otel/claude.env` keys go under "env" in
~/.claude/settings.json (or $CLAUDE_CONFIG_DIR). Codex: `codex-otel.toml` is appended to
~/.codex/config.toml (or $CODEX_HOME) unless an [otel] section already exists. A backup is
written before any change. Restart the CLIs afterwards.
"""
import json
import os
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXPORT = re.compile(r'^\s*export\s+([A-Z][A-Z0-9_]*)=(\S*)\s*$')


def claude_env(path=HERE / 'claude.env'):
    return {m.group(1): m.group(2) for m in map(EXPORT.match, path.read_text().splitlines()) if m}


def plan_claude(settings, env):
    """(updated settings, [(key, old, new)]) — only keys whose value would change."""
    current = settings.get('env') if isinstance(settings.get('env'), dict) else {}
    changes = [(key, current.get(key), value) for key, value in env.items() if current.get(key) != value]
    return {**settings, 'env': {**current, **env}}, changes


def _confirm(question, ask):
    try:
        return ask(f'{question} [y/N] ').strip().lower() in ('y', 'yes')
    except EOFError:
        return False


def _backup(path):
    backup = path.with_name(f'{path.name}.bak-{time.strftime("%Y%m%d%H%M%S")}')
    backup.write_bytes(path.read_bytes())
    return backup


def apply_claude(path, env, ask=input, out=print):
    if path.is_symlink():
        out(f'  {path} 는 심링크라 바꾸지 않습니다. 아래 키를 직접 넣으세요: {", ".join(env)}')
        return False
    try:
        settings = json.loads(path.read_text()) if path.exists() else {}
    except ValueError:
        out(f'  {path} 가 올바른 JSON 이 아니라 바꾸지 않습니다.')
        return False
    if not isinstance(settings, dict):
        out(f'  {path} 형식이 객체가 아니라 바꾸지 않습니다.')
        return False
    updated, changes = plan_claude(settings, env)
    if not changes:
        out(f'  {path}: 이미 적용돼 있습니다.')
        return False
    out(f'  {path} "env" 변경 예정:')
    for key, old, new in changes:
        out(f'    + {key}={new}' if old is None else f'    ~ {key}: {old} -> {new}')
    if not _confirm('  Claude 설정에 적용할까요?', ask):
        out('  건너뜀.')
        return False
    if path.exists():
        out(f'  백업: {_backup(path)}')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(updated, ensure_ascii=False, indent=2) + '\n')
    out('  적용했습니다.')
    return True


def apply_codex(path, snippet, ask=input, out=print):
    text = path.read_text() if path.exists() else ''
    if re.search(r'^\s*\[otel[\].]', text, re.M):
        out(f'  {path} 에 이미 [otel] 설정이 있습니다. {HERE / "codex-otel.toml"} 와 직접 비교하세요.')
        return False
    if path.is_symlink():
        out(f'  {path} 는 심링크라 바꾸지 않습니다. 아래 내용을 직접 붙이세요.')
        out(snippet)
        return False
    out(f'  {path} 끝에 붙일 내용:')
    out(snippet)
    if not _confirm('  Codex 설정에 붙일까요?', ask):
        out('  건너뜀.')
        return False
    if path.exists():
        out(f'  백업: {_backup(path)}')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text + ('\n' if text and not text.endswith('\n') else '') + '\n' + snippet)
    out('  적용했습니다.')
    return True


def main(ask=input, out=print, environ=os.environ):
    home = Path(environ.get('HOME', str(Path.home())))
    claude = Path(environ.get('CLAUDE_CONFIG_DIR') or home / '.claude') / 'settings.json'
    codex = Path(environ.get('CODEX_HOME') or home / '.codex') / 'config.toml'
    out('== OTel: Claude Code (사용자 설정)')
    apply_claude(claude, claude_env(), ask, out)
    out('== OTel: Codex (사용자 설정)')
    apply_codex(codex, (HERE / 'codex-otel.toml').read_text(), ask, out)
    out('collector 시작: agent-platform-agent otel start (또는 MCP otel_collector). 적용하려면 CLI 를 다시 시작하세요.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
