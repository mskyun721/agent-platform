"""Project-scoped local Claude/Codex transcript projection; no tools or reasoning."""

import hashlib
import json
import os
import re
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from agent_platform_mcp import config
from agent_platform_mcp.tools import llm_view, projects, store
from agent_platform_mcp.tools.stdout_artifacts import _mask

try:
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX hosts collect without the burst guard
    fcntl = None

LOCK = threading.Lock()
PARSER_VERSION = 3  # Revisit unchanged transcripts when projection semantics change.
BUDGET_SEC = 10  # Hook-run collection must return promptly.
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


def new_turn(backend, session, identity, workspace, ts, project_id=None, role='direct'):
    return {'run_id': str(uuid5(NAMESPACE_URL, f'{backend}:{session}:{identity}')), 'session_id': session,
            'project_id': project_id, 'workspace': workspace, 'task_id': backend + ' / ' + identity[:12],
            'role': role, 'backend': backend, 'model': None, 'ts': ts, 'ended_at': None,
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


def _scope(workspaces):
    """{workspace: project_id}; a bare path is the single-workspace form."""
    return {workspaces: None} if isinstance(workspaces, str) else dict(workspaces)


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


def parse_codex(rows, workspaces):
    scope = _scope(workspaces)
    session, current, turns, previous, baseline = None, None, [], {}, {}
    workspace, role, history = None, 'direct', 0
    for index, row in enumerate(rows):
        p = row.get('payload', {})
        if not isinstance(p, dict):
            continue
        kind = row.get('type')
        if kind == 'session_meta':
            if session:
                continue  # A forked subagent replays its parent's meta; the first one owns the file.
            if p.get('cwd') not in scope:
                return []
            workspace = p['cwd']
            session = p.get('id') or p.get('session_id')
            source = p.get('source')
            if isinstance(source, dict) and 'subagent' in source:
                role = 'subagent'
                ordinal = p.get('subagent_history_start_ordinal')
                history = ordinal if type(ordinal) is int and ordinal > 0 else 0
            continue
        if not session or index < history:
            continue  # Rows before the ordinal are the parent's turns, already in the parent file.
        event = p.get('type') if kind == 'event_msg' else None
        if event == 'task_started':
            current = new_turn('codex', session, p.get('turn_id', str(len(turns))), workspace, row.get('timestamp'),
                               scope[workspace], role)
            current['_turn'] = p.get('turn_id')
            turns.append(current)
            baseline = dict(previous) if previous is not None else None
        if current is None:
            # Session totals still advance while a foreign turn is excluded.
            if event == 'token_count':
                total = (p.get('info') or {}).get('total_token_usage', {})
                if isinstance(total, dict) and total:
                    previous = total
            continue
        if kind == 'turn_context':
            if p.get('cwd', workspace) != workspace:
                # A prompt may precede its context record; remove the whole turn.
                turns.pop()
                current = None
                previous = None
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
            if isinstance(total, dict) and total:
                if not current.get('_native_usage') and baseline is not None:
                    delta = {k: v - baseline.get(k, 0) for k, v in total.items() if (not baseline or k in baseline) and type(v) is int and type(baseline.get(k, 0)) is int}
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


def parse_claude(rows, workspaces, agent_type=None, subagent=False):
    """A subagent file holds only sidechain rows; elsewhere sidechain rows are skipped."""
    scope = _scope(workspaces)
    current, turns, messages, session = None, [], {}, None
    active_workspace = None
    for row in rows:
        if bool(row.get('isSidechain')) != subagent or (row.get('isMeta') and row.get('subtype') != 'turn_duration'):
            continue
        if row.get('cwd') and row['cwd'] != active_workspace:
            active_workspace = row['cwd']
            current, messages = None, {}
        session = row.get('sessionId') or session
        if active_workspace not in scope:
            continue
        kind, message = row.get('type'), row.get('message') or {}
        if not isinstance(message, dict):
            continue
        content = message.get('content')
        if kind == 'user' and text(content) and session:
            current = new_turn('claude', session, row.get('uuid', str(len(turns))), active_workspace, row.get('timestamp'),
                               scope[active_workspace], 'subagent' if subagent else 'direct')
            if subagent:
                current['agent_type'] = agent_type
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


def scope(db):
    """Capture-enabled workspaces among the platform root and registered project paths -> project_id."""
    platform = str(config.ROOT.resolve())
    try:
        registered = {record['path']: key for key, record in projects._read()['projects'].items()}
    except (OSError, ValueError):
        registered = {}  # A damaged registry narrows collection to the platform root.
    candidates = {platform: registered.get(platform), **registered}
    enabled = {row[0] for row in db.execute('SELECT workspace FROM capture WHERE enabled=1')}
    return {path: key for path, key in candidates.items() if path in enabled}


def _agent_type(path):
    """Only `agentType` from the subagent's sibling meta file; other fields are not read out."""
    meta = path.with_name(path.stem + '.meta.json')
    try:
        projects._safe_storage(meta)
        if meta.stat().st_size > 64 * 1024:
            return None
        value = json.loads(meta.read_text()).get('agentType')
    except (OSError, ValueError, AttributeError):
        return None
    return value if isinstance(value, str) and re.fullmatch(r'[\w.:-]{1,64}', value) else None


def _parse(backend, path, workspaces):
    if backend == 'codex':
        return parse_codex(_rows(path), workspaces)
    if path.parent.name == 'subagents':
        return parse_claude(_rows(path), workspaces, _agent_type(path), subagent=True)
    return parse_claude(_rows(path), workspaces)


def collect(root=None, budget_sec=None):
    """Import changed transcripts of capture-enabled workspaces once; unchanged files are not reparsed.

    With `root`, a capture-disabled root skips the whole collection. Past `budget_sec` the
    remaining files wait for the next call (`truncated: true`)."""
    deadline = None if budget_sec is None else time.monotonic() + budget_sec
    with LOCK, llm_view.content_db() as db:
        status = {'checked_at': time.time(), 'truncated': False}
        if root is not None:
            workspace = str(config.resolve_project(root).path)
            enabled = db.execute('SELECT enabled FROM capture WHERE workspace=?', (workspace,)).fetchone()
            status |= {'workspace': workspace, 'enabled': bool(enabled and enabled[0])}
            if not status['enabled']:
                return status | {'status': 'skipped', 'reason': 'capture disabled'}
        workspaces = scope(db)
        status['scope'] = [{'workspace': path, 'project_id': key} for path, key in sorted(workspaces.items())]
        if not workspaces:
            return status | {'status': 'skipped', 'reason': 'capture disabled'}
        # A changed scope must revisit files that matched nothing before.
        fingerprint = hashlib.sha256(json.dumps(sorted(workspaces.items())).encode()).hexdigest()[:12]
        for backend, base in sources().items():
            info = status[backend] = {'imported': 0, 'subagent_turns': 0, 'errors': 0, 'skipped_large': 0, 'unchanged_files': 0,
                                      'no_matching_turn_files': 0, 'available': base.is_dir()}
            if not base.is_dir():
                continue
            try:
                projects._safe_storage(base)
                candidates = sorted((p for p in base.rglob('*.jsonl') if p.stat().st_mtime >= time.time() - llm_view.RETENTION),
                                    key=lambda p: p.stat().st_mtime, reverse=True)
                info['files'] = len(candidates)
                info['latest_source_mtime_any_workspace'] = candidates[0].stat().st_mtime if candidates else None
                info['truncated'] = len(candidates) > 300
                for path in candidates[:300]:
                    if deadline is not None and time.monotonic() > deadline:
                        info['truncated'] = True
                        break
                    try:
                        projects._safe_storage(path)
                        stat = path.stat()
                        if stat.st_size > 64 * 1024 * 1024:
                            info['skipped_large'] += 1
                            continue
                        signature = f'{PARSER_VERSION}:{fingerprint}:{stat.st_mtime_ns}:{stat.st_size}'
                        old = db.execute('SELECT signature FROM native_files WHERE path=?', (str(path),)).fetchone()
                        if old and old[0] == signature:
                            info['unchanged_files'] += 1
                            continue
                        rows = _parse(backend, path, workspaces)
                        if not rows:
                            info['no_matching_turn_files'] += 1
                        for record in rows:
                            if db.execute('SELECT 1 FROM native_suppressed WHERE run_id=?', (record['run_id'],)).fetchone():
                                continue
                            db.execute('INSERT INTO native_runs VALUES (?,?,?,?) ON CONFLICT(run_id) DO UPDATE SET payload_json=excluded.payload_json',
                                (record['run_id'], time.time() + llm_view.RETENTION, record['workspace'], json.dumps(record)))
                        db.execute('INSERT INTO native_files VALUES (?,?) ON CONFLICT(path) DO UPDATE SET signature=excluded.signature', (str(path), signature))
                        info['imported'] += len(rows)
                        info['subagent_turns'] += sum(r['role'] == 'subagent' for r in rows)
                    except (ValueError, OSError, TypeError, KeyError):
                        info['errors'] += 1
            except OSError:
                info['errors'] += 1
            status['truncated'] |= info['truncated']
        return status | {'status': 'collected'}


def save_health(name, result):
    with llm_view.content_db() as db:
        db.execute('INSERT INTO collector_health VALUES (?,?) ON CONFLICT(name) DO UPDATE SET payload_json=excluded.payload_json',
                   (name, json.dumps(result)))


@contextmanager
def _single_run():
    """Hooks may fire in bursts; a second concurrent one-shot collection is skipped, not queued."""
    with store.open() as state:
        path = state.path.parent / 'native-collect.lock'
    projects._safe_storage(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        if fcntl is None:
            yield True
            return
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        yield True
    finally:
        os.close(descriptor)


def collect_once(root, budget_sec=BUDGET_SEC):
    """Hook/MCP entry point: never raises, so a session is not blocked by a collection failure."""
    started = time.monotonic()
    try:
        with _single_run() as acquired:
            if not acquired:
                return {'status': 'skipped', 'reason': 'collection already running', 'truncated': False}
            result = collect(root, budget_sec)
            if result['status'] == 'collected':
                save_health('native_once', result)
    except Exception as exc:
        result = {'status': 'error', 'error': type(exc).__name__, 'truncated': False}
    result['elapsed_sec'] = round(time.monotonic() - started, 3)
    if result['elapsed_sec'] > budget_sec:
        result['truncated'] = True
    return result
