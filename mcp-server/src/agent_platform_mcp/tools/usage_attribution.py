"""Native session turn usage -> run attribution (PRD BR-2, AC-2; DECISIONS ADR-010).

A collected turn belongs to a run only when exactly one run of the same project (or, for an
unregistered workspace, the same workspace) and the same backend overlaps the turn's time span.
Several overlapping runs make the turn `ambiguous`, none makes it `unattributed`; usage is never
split by estimate. Only direct-session runs receive the attributed sum; a single wrapper or
imported run is `measured_elsewhere` (it records its own usage, so adding the turn would double count).

Per-turn decisions live in the collector's `native_attribution` table (counts and identifiers only,
no expiry), keyed by turn id. A run's usage is always recomputed from those rows, so a re-collected
or grown turn replaces its earlier contribution instead of adding to it.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from agent_platform_mcp import events
from agent_platform_mcp.tools import projects, store

SOURCE = 'native-session-attribution'
COUNTS = ('input_tokens', 'output_tokens', 'cache_read_tokens', 'cache_write_tokens')
STATUSES = ('attributed', 'ambiguous', 'unattributed', 'measured_elsewhere')
SCHEMA = '''CREATE TABLE IF NOT EXISTS native_attribution (turn_id TEXT PRIMARY KEY, project_id TEXT, workspace TEXT NOT NULL,
    backend TEXT NOT NULL, ts TEXT, status TEXT NOT NULL, run_id TEXT, candidates_json TEXT NOT NULL, usage_json TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS native_attribution_run ON native_attribution(run_id);'''


def _time(value) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return (parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def _owner(backend, project_id, workspace) -> tuple:
    """Same backend and project; an unregistered workspace (no project_id) matches by path."""
    return (backend, project_id) if project_id is not None else (backend, None, workspace)


def candidates(state: store.Store) -> dict[tuple, list[dict]]:
    """LLM runs that could own a turn, grouped by owner; point runs (no backend, or the L-4 marker) are left out."""
    result = {}
    for run_id, event_json, started, ended in state.connection.execute(
            "SELECT run_id,event_json,started_at,ended_at FROM runs WHERE json_extract(event_json,'$.backend') IN ('claude','codex')"):
        event = json.loads(event_json)
        payload = event.get('payload') or {}
        if payload.get('point'):
            continue
        key = _owner(event['backend'], event.get('project_id'), payload.get('workspace'))
        result.setdefault(key, []).append({'run_id': run_id, 'source': event.get('collection_source'),
                                           'start': _time(started), 'end': _time(ended)})
    return result


def decide(turn: dict, runs: dict[tuple, list[dict]], now: datetime) -> tuple[str, str | None, list[str]]:
    """(status, run_id, candidate run ids). The turn spans [ts, ended_at, or now while running]."""
    start = _time(turn.get('ts'))
    if start is None:
        return 'unattributed', None, []
    end = _time(turn.get('ended_at')) or (now if turn.get('state') == 'running' else start)
    found = [run for run in runs.get(_owner(turn['backend'], turn.get('project_id'), turn['workspace']), [])
             if run['start'] is not None and run['start'] <= end and (run['end'] or now) >= start]
    ids = sorted(run['run_id'] for run in found)
    if not found:
        return 'unattributed', None, ids
    if len(found) > 1:
        return 'ambiguous', None, ids
    return ('attributed' if found[0]['source'] == 'direct' else 'measured_elsewhere'), found[0]['run_id'], ids


def record(content: sqlite3.Connection, turns: list[dict], runs: dict[tuple, list[dict]], now: datetime) -> tuple[dict, set[str]]:
    """Upsert each turn's decision inside the caller's content transaction; returns counts and touched run ids."""
    counts = dict.fromkeys(STATUSES, 0)
    touched = set()
    for turn in turns:
        status, run_id, ids = decide(turn, runs, now)
        counts[status] += 1
        old = content.execute('SELECT run_id FROM native_attribution WHERE turn_id=?', (turn['run_id'],)).fetchone()
        if old and old[0]:
            touched.add(old[0])
        if status == 'attributed':
            touched.add(run_id)
        start = _time(turn.get('ts'))
        usage = {key: turn['usage'].get(key) for key in COUNTS}
        content.execute('INSERT OR REPLACE INTO native_attribution VALUES (?,?,?,?,?,?,?,?,?)',
                        (turn['run_id'], turn.get('project_id'), turn['workspace'], turn['backend'],
                         start.isoformat() if start else None, status, run_id if status == 'attributed' else None,
                         json.dumps(ids), json.dumps(usage)))
    return counts, touched


def total(rows: list[dict]) -> events.Usage:
    """Field sums; a field unknown in any turn stays null. `full` needs input/output in every turn
    (the events contract: cache counts may be null in full usage)."""
    if not rows:
        return events.Usage(None, None, None, None, 'unavailable', 'unavailable')
    sums = {key: sum(row[key] for row in rows) if all(type(row.get(key)) is int for row in rows) else None for key in COUNTS}
    if sums['input_tokens'] is not None and sums['output_tokens'] is not None:
        completeness = 'full'
    else:
        completeness = 'partial' if any(value is not None for value in sums.values()) else 'unavailable'
    if completeness == 'unavailable':
        return events.Usage(None, None, None, None, 'unavailable', 'unavailable')
    return events.Usage(*(sums[key] for key in COUNTS), SOURCE, completeness)


def apply(state: store.Store, content: sqlite3.Connection, run_ids: set[str]) -> int:
    """Write the recomputed sum of each touched run; returns how many runs changed."""
    changed = 0
    for run_id in sorted(run_ids):
        rows = [json.loads(row[0]) for row in content.execute(
            "SELECT usage_json FROM native_attribution WHERE run_id=? AND status='attributed'", (run_id,))]
        changed += state.attributed_usage(run_id, total(rows))
    return changed


def _content_path():
    return store.default_path().parent / 'llm-content.db'


def _rows(context: projects.ProjectContext, since: str | None, statuses: tuple[str, ...]) -> list[tuple] | None:
    """Read-only (`mode=ro`) scan of this project's decisions; None when the collector has no data."""
    path = _content_path()
    projects._safe_storage(path)
    if not path.is_file():
        return None
    connection = sqlite3.connect(f'{path.as_uri()}?mode=ro', uri=True, timeout=5)
    try:
        marks = ','.join('?' * len(statuses))
        return connection.execute(
            f'SELECT status,ts,candidates_json FROM native_attribution WHERE project_id IS ? AND (? IS NOT NULL OR workspace=?) '
            f'AND (? IS NULL OR ts>=?) AND status IN ({marks})',  # marks are only '?' placeholders
            (context.project_id, context.project_id, str(context.path), since, since, *statuses)).fetchall()
    except sqlite3.OperationalError:
        return None  # collector DB predates attribution
    finally:
        connection.close()


def project_counts(context: projects.ProjectContext, since: str | None) -> dict:
    """Turns of the project left unattributed or ambiguous (since: ISO UTC start, from usage_report._since)."""
    rows = _rows(context, since, ('unattributed', 'ambiguous'))
    if rows is None:
        return {'unattributed_runs': None, 'ambiguous_runs': None}
    return {'unattributed_runs': sum(row[0] == 'unattributed' for row in rows),
            'ambiguous_runs': sum(row[0] == 'ambiguous' for row in rows)}


def feature_counts(connection, context: projects.ProjectContext, task_id: str, since: str | None) -> dict:
    """Ambiguous turns that had one of the feature's runs as a candidate, and unattributed turns
    inside the feature's span (first run start .. last run end, or now while a run is open)."""
    rows = _rows(context, since, ('unattributed', 'ambiguous'))
    if rows is None:
        return {'unattributed_runs': None, 'ambiguous_runs': None}
    spans = connection.execute('SELECT run_id,started_at,ended_at FROM runs WHERE project_id IS ? AND task_id=?',
                               (context.project_id, task_id)).fetchall()
    ids = {row[0] for row in spans}
    now = datetime.now(timezone.utc)
    first = min((_time(row[1]) for row in spans), default=None)
    last = max((_time(row[2]) or now for row in spans), default=None)
    unattributed = sum(1 for status, ts, _ in rows if status == 'unattributed' and first is not None
                       and _time(ts) is not None and first <= _time(ts) <= last)
    ambiguous = sum(1 for status, _, found in rows if status == 'ambiguous' and ids & set(json.loads(found)))
    return {'unattributed_runs': unattributed, 'ambiguous_runs': ambiguous}
