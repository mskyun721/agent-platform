"""Project-scoped local Claude/Codex transcript projection; no tools or reasoning."""

import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from agent_platform_mcp import config
from agent_platform_mcp.tools import llm_view, projects
from agent_platform_mcp.tools.stdout_artifacts import _mask

LOCK = threading.Lock()
PARSER_VERSION = 2  # Revisit unchanged transcripts when projection semantics change.
FIELDS = ('input_tokens', 'output_tokens', 'cache_read_tokens', 'cache_write_tokens')


def sources():
    return {'codex': Path(os.environ.get('CODEX_HOME', Path.home() / '.codex')) / 'sessions',
            'claude': Path(os.environ.get('CLAUDE_CONFIG_DIR', Path.home() / '.claude')) / 'projects'}


def text(content):
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ''
    return '\n'.join(c['text'] for c in content if isinstance(c, dict)
                     and c.get('type') in ('text', 'input_text', 'output_text') and isinstance(c.get('text'), str))


def usage(value, backend):
    keys = ('input_tokens', 'output_tokens', 'cached_input_tokens', 'cache_write_input_tokens') if backend == 'codex' else (
        'input_tokens', 'output_tokens', 'cache_read_input_tokens', 'cache_creation_input_tokens')
    counts = {field: value.get(key) if type(value.get(key)) is int and value[key] >= 0 else None for field, key in zip(FIELDS, keys)}
    return counts | {'source': backend + '-transcript', 'completeness': 'unavailable' if all(v is None for v in counts.values()) else
                     'full' if all(v is not None for v in counts.values()) else 'partial'}


def new_turn(backend, session, identity, workspace, ts):
    return {'run_id': str(uuid5(NAMESPACE_URL, f'{backend}:{session}:{identity}')), 'session_id': session,
            'project_id': None, 'workspace': workspace, 'task_id': backend + ' / ' + identity[:12],
            'role': 'direct', 'backend': backend, 'model': None, 'ts': ts, 'ended_at': None,
            'state': 'running', 'outcome': None, 'duration_sec': None, 'collection_source': 'native_session',
            'usage': usage({}, backend), 'content': {'status': 'captured', 'prompt': None, 'response': None}, 'events': []}


def finish(turn, timestamp, duration=None):
    turn.update(state='completed', outcome='completed', ended_at=timestamp)
    if type(duration) in (float, int) and duration >= 0:
        turn['duration_sec'] = duration / 1000
    elif timestamp and turn['ts']:
        try:
            turn['duration_sec'] = max(0, (datetime.fromisoformat(timestamp) - datetime.fromisoformat(turn['ts'])).total_seconds())
        except ValueError:
            pass


def bounded(turns):
    for turn in turns:
        for field in ('prompt', 'response'):
            value = turn['content'].get(field)
            if value is not None:
                value = _mask(value)
                turn['content'][field] = value[:llm_view.MAX_TEXT]
                turn['content'][field + '_truncated'] = len(value) > llm_view.MAX_TEXT
        if turn['content']['prompt']:
            turn['task_id'] = turn['content']['prompt'].splitlines()[0][:100]
    return [t for t in turns if t['content']['prompt']]


def parse_codex(rows, workspace):
    session, current, turns, previous, baseline = None, None, [], {}, {}
    for row in rows:
        p = row.get('payload', {})
        if not isinstance(p, dict):
            continue
        kind = row.get('type')
        if kind == 'session_meta':
            if p.get('cwd') != workspace:
                return []
            session = p.get('id') or p.get('session_id')
        if not session:
            continue
        event = p.get('type') if kind == 'event_msg' else None
        if event == 'task_started':
            current = new_turn('codex', session, p.get('turn_id', str(len(turns))), workspace, row.get('timestamp'))
            current['_turn'] = p.get('turn_id')
            turns.append(current)
            baseline = dict(previous)
        if current is None:
            continue
        if kind == 'turn_context':
            if p.get('cwd', workspace) != workspace:
                current = None
                continue
            current['model'] = p.get('model')
        elif kind == 'response_item' and p.get('role') == 'user':
            meta = p.get('internal_chat_message_metadata_passthrough') or {}
            kinds = meta.get('content_item_kinds', [])
            content = p.get('content', [])
            if kinds:
                content = [c for i, c in enumerate(content) if i < len(kinds) and kinds[i] == 'user.text']
            value = text(content)
            if value:
                old = current['content']['prompt']
                current['content']['prompt'] = (old + '\n' if old else '') + value
        elif event == 'user_message' and not current['content']['prompt']:
            current['content']['prompt'] = p.get('message')
        elif kind == 'token_usage_record' and p.get('turn_id') == current['_turn'] and isinstance(p.get('turn_token_usage'), dict):
            current['usage'] = usage(p['turn_token_usage'], 'codex')
            current['_native_usage'] = True
        elif event == 'token_count':
            total = (p.get('info') or {}).get('total_token_usage', {})
            if isinstance(total, dict):
                if not current.get('_native_usage'):
                    delta = {k: v - baseline.get(k, 0) for k, v in total.items() if type(v) is int and type(baseline.get(k, 0)) is int}
                    current['usage'] = usage(delta, 'codex')
                previous = total
        elif event in ('task_complete', 'task_completed'):
            current['content']['response'] = p.get('last_agent_message')
            finish(current, p.get('completed_at') or row.get('timestamp'), p.get('duration_ms'))
        elif event == 'turn_aborted':
            current.update(state='interrupted', outcome='interrupted', ended_at=row.get('timestamp'))
    for turn in turns:
        turn.pop('_turn', None)
        turn.pop('_native_usage', None)
    return bounded(turns)


def parse_claude(rows, workspace):
    current, turns, messages, session = None, [], {}, None
    active_workspace = None
    for row in rows:
        if row.get('isSidechain') or (row.get('isMeta') and row.get('subtype') != 'turn_duration'):
            continue
        if row.get('cwd') and row['cwd'] != active_workspace:
            active_workspace = row['cwd']
            current, messages = None, {}
        session = row.get('sessionId') or session
        if active_workspace != workspace:
            continue
        kind, message = row.get('type'), row.get('message') or {}
        if not isinstance(message, dict):
            continue
        content = message.get('content')
        if kind == 'user' and text(content) and session:
            current = new_turn('claude', session, row.get('uuid', str(len(turns))), workspace, row.get('timestamp'))
            current['content']['prompt'] = text(content)
            turns.append(current)
            messages = {}
        elif current and kind == 'assistant':
            current['model'] = message.get('model') or current['model']
            identity = message.get('id')
            if identity and isinstance(message.get('usage'), dict):
                # Multiple content blocks of one API message carry repeated snapshots.
                messages[identity] = usage(message['usage'], 'claude')
                sums = {f: sum(m[f] for m in messages.values()) if all(m[f] is not None for m in messages.values()) else None for f in FIELDS}
                current['usage'] = sums | {'source': 'claude-transcript', 'completeness': 'full' if all(v is not None for v in sums.values()) else 'partial'}
            value = text(content)
            if value:
                current['content']['response'] = value
            if message.get('stop_reason') == 'end_turn':
                finish(current, row.get('timestamp'))
        elif current and kind == 'system' and row.get('subtype') == 'turn_duration':
            finish(current, row.get('timestamp') or current['ended_at'], row.get('durationMs'))
    return bounded(turns)


def _rows(path):
    with path.open() as stream:
        for line in stream:
            try:
                row = json.loads(line)
                if isinstance(row, dict):
                    yield row
            except ValueError:
                continue  # A writer may still be appending the last JSON line.


def collect():
    """Refresh only this platform checkout; unchanged files are not reparsed."""
    with LOCK, llm_view.content_db() as db:
        workspace = str(config.ROOT.resolve())
        enabled = db.execute('SELECT enabled FROM capture WHERE workspace=?', (workspace,)).fetchone()
        status = {'workspace': workspace, 'enabled': bool(enabled and enabled[0]), 'checked_at': time.time()}
        if not status['enabled']:
            return status
        for backend, base in sources().items():
            info = status[backend] = {'imported': 0, 'errors': 0, 'skipped_large': 0, 'available': base.is_dir()}
            if not base.is_dir():
                continue
            try:
                projects._safe_storage(base)
                candidates = sorted((p for p in base.rglob('*.jsonl') if p.stat().st_mtime >= time.time() - llm_view.RETENTION),
                                    key=lambda p: p.stat().st_mtime, reverse=True)
                info['files'] = len(candidates)
                info['truncated'] = len(candidates) > 300
                for path in candidates[:300]:
                    try:
                        projects._safe_storage(path)
                        stat = path.stat()
                        if stat.st_size > 64 * 1024 * 1024:
                            info['skipped_large'] += 1
                            continue
                        signature = f'{PARSER_VERSION}:{stat.st_mtime_ns}:{stat.st_size}'
                        old = db.execute('SELECT signature FROM native_files WHERE path=?', (str(path),)).fetchone()
                        if old and old[0] == signature:
                            continue
                        parser = parse_codex if backend == 'codex' else parse_claude
                        rows = parser(_rows(path), workspace)
                        for record in rows:
                            if db.execute('SELECT 1 FROM native_suppressed WHERE run_id=?', (record['run_id'],)).fetchone():
                                continue
                            db.execute('INSERT INTO native_runs VALUES (?,?,?,?) ON CONFLICT(run_id) DO UPDATE SET payload_json=excluded.payload_json',
                                (record['run_id'], time.time() + llm_view.RETENTION, workspace, json.dumps(record)))
                        db.execute('INSERT INTO native_files VALUES (?,?) ON CONFLICT(path) DO UPDATE SET signature=excluded.signature', (str(path), signature))
                        info['imported'] += len(rows)
                    except (ValueError, OSError, TypeError, KeyError):
                        info['errors'] += 1
            except OSError:
                info['errors'] += 1
        return status
