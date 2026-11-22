"""Local OTel collector control (fixed docker compose argv) and a metadata-only usage summary."""

import json
import shutil
import subprocess
import time
from collections import defaultdict
from datetime import datetime, timezone

from agent_platform_mcp import config
from agent_platform_mcp.tools import projects
from agent_platform_mcp.tools.stdout_artifacts import _mask

# The only commands ever run; no caller-supplied argument reaches docker.
ACTIONS = {'start': ('up', '-d'), 'stop': ('down',), 'status': ('ps', '--format', 'json')}
TIMEOUTS = {'start': 300, 'stop': 120, 'status': 30}
SUMMARY_BUDGET_SEC = 20
TOP_SESSIONS = 50
# Whitelisted attributes per event; prompt/response/user attributes are never read out.
CLAUDE = {'session': 'session.id', 'model': 'model', 'input_tokens': 'input_tokens', 'output_tokens': 'output_tokens',
          'cache_read_tokens': 'cache_read_tokens', 'cache_write_tokens': 'cache_creation_tokens', 'cost_usd': 'cost_usd'}
CODEX = {'session': 'conversation.id', 'model': 'model', 'input_tokens': 'input_token_count',
         'output_tokens': 'output_token_count', 'cache_read_tokens': 'cached_token_count',
         'cache_write_tokens': 'cache_write_token_count'}
TOKENS = ('input_tokens', 'output_tokens', 'cache_read_tokens', 'cache_write_tokens')


def _compose():
    path = config.ROOT / 'scripts/otel/docker-compose.yml'
    projects._safe_storage(path)
    if not path.is_file():
        raise ValueError('scripts/otel/docker-compose.yml not found')
    return path


def _unavailable(reason):
    return {'status': 'unavailable', 'reason': reason}


def collector(action):
    if action not in ACTIONS:
        raise ValueError('action must be start, stop or status')
    compose = _compose()
    docker = shutil.which('docker')
    if not docker:
        return _unavailable('docker not found')
    try:
        done = subprocess.run([docker, 'compose', '-f', str(compose), *ACTIONS[action]], cwd=compose.parent,
                              stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=TIMEOUTS[action])
    except subprocess.TimeoutExpired:
        return {'status': 'error', 'reason': 'timeout', 'action': action}
    except OSError as exc:
        return _unavailable(type(exc).__name__)
    if done.returncode:
        if 'daemon' in done.stderr.lower():
            return _unavailable('daemon not running')
        return {'status': 'error', 'action': action, 'exit_code': done.returncode, 'stderr': _mask(done.stderr)[-500:]}
    if action != 'status':
        return {'status': 'started' if action == 'start' else 'stopped', 'endpoints': ['127.0.0.1:4317', '127.0.0.1:4318']}
    return _services(done.stdout)


def _services(stdout):
    text = stdout.strip()
    try:  # Compose prints a JSON array (older) or one JSON object per line (newer).
        rows = json.loads(text) if text.startswith('[') else [json.loads(line) for line in text.splitlines() if line.strip()]
    except ValueError:
        return {'status': 'error', 'reason': 'unexpected docker compose ps output'}
    services = [{'service': r.get('Service'), 'state': r.get('State'), 'status': r.get('Status')}
                for r in rows if isinstance(r, dict)]
    running = any(s['state'] == 'running' for s in services)
    return {'status': 'running' if running else 'stopped', 'services': services}


def _value(attribute):
    value = attribute.get('value') or {}
    for key in ('intValue', 'doubleValue', 'stringValue'):
        if key in value:
            raw = value[key]
            if key == 'intValue':  # OTLP/JSON encodes int64 as a string
                try:
                    return int(raw)
                except (TypeError, ValueError):
                    return None
            return raw
    return None


def _since(value):
    if value is None:
        return None
    try:
        day = datetime.strptime(value, '%Y-%m-%d').replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        raise ValueError('since must be YYYY-MM-DD') from None
    return int(day.timestamp() * 1e9)


def _record(record, threshold):
    """(backend, fields) for a usage event; None for anything else."""
    names = {a.get('key'): a for a in record.get('attributes') or [] if isinstance(a, dict)}
    event = _value(names['event.name']) if 'event.name' in names else None
    if event == 'api_request':
        backend, mapping = 'claude', CLAUDE
    elif event == 'codex.sse_event' and 'event.kind' in names and _value(names['event.kind']) == 'response.completed':
        backend, mapping = 'codex', CODEX
    else:
        return None
    if threshold is not None:
        try:
            stamp = int(record.get('timeUnixNano') or 0) or int(record.get('observedTimeUnixNano') or 0)
        except (TypeError, ValueError):
            stamp = 0
        if stamp < threshold:
            return None
    return backend, {field: _value(names[key]) if key in names else None for field, key in mapping.items()}


def summary(since=None):
    threshold = _since(since)
    directory = config.ROOT / 'scripts/otel/otel-data'
    projects._safe_storage(directory)
    deadline = time.monotonic() + SUMMARY_BUDGET_SEC
    groups = defaultdict(lambda: {'requests': 0, **{f: 0 for f in TOKENS}, 'cost_usd': None})
    files, truncated = {}, False
    for path in sorted(directory.glob('*.jsonl')) if directory.is_dir() else []:
        projects._safe_storage(path)
        with path.open('rb') as stream:
            if not stream.read(64).lstrip().startswith(b'{"resourceLogs"'):
                files[path.name] = 'skipped: not logs (metrics/traces repeat the log events)'
                continue
            stream.seek(0)
            files[path.name] = 'read'
            for line in stream:
                if time.monotonic() > deadline:
                    files[path.name], truncated = 'truncated', True
                    break
                if b'api_request' not in line and b'response.completed' not in line:
                    continue
                try:
                    batch = json.loads(line)
                except ValueError:
                    continue  # the collector may still be writing the last line
                for resource in batch.get('resourceLogs') or []:
                    for scope in resource.get('scopeLogs') or []:
                        for record in scope.get('logRecords') or []:
                            found = _record(record, threshold) if isinstance(record, dict) else None
                            if found:
                                _add(groups, *found)
    rows = [{'backend': b, 'session_id': s, 'model': m, **v} for (b, s, m), v in groups.items()]
    by_model = defaultdict(lambda: {'requests': 0, 'sessions': 0, **{f: 0 for f in TOKENS}, 'cost_usd': None})
    for row in rows:
        total = by_model[(row['backend'], row['model'])]
        total['sessions'] += 1
        _merge(total, row)
    rows.sort(key=lambda r: r['input_tokens'], reverse=True)
    return {'status': 'ok' if rows else 'no_data', 'since': since, 'truncated': truncated, 'files': files,
            'by_model': [{'backend': b, 'model': m, **v} for (b, m), v in sorted(by_model.items(), key=lambda i: str(i[0]))],
            'sessions': rows[:TOP_SESSIONS], 'sessions_total': len(rows),
            'limitations': ['Counts come from exported OTel log events only; nothing is read from prompt or response attributes.',
                            'Claude and Codex token definitions differ; they are not added together.',
                            'cost_usd is what the CLI reported (Claude only); Codex cost is null.']}


def _add(groups, backend, fields):
    _merge(groups[(backend, fields.get('session'), fields.get('model'))], {'requests': 1, **fields})


def _merge(target, source):
    target['requests'] += source['requests']
    for field in TOKENS:
        if type(source.get(field)) is int:
            target[field] += source[field]
    cost = source.get('cost_usd')
    if isinstance(cost, (int, float)) and not isinstance(cost, bool):
        target['cost_usd'] = round((target['cost_usd'] or 0) + cost, 6)
