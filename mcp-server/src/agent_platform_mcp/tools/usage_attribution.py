"""Native session turn usage -> run attribution (PRD BR-2, AC-2; DECISIONS ADR-010).

A collected turn belongs to a run only when exactly one run of the same project (or, for an
unregistered workspace, the same workspace) and the same backend overlaps the turn's time span.
A run also matches turns of the session workspace `state start` ran in (`session_workspace`, REVIEW
M-1). A run with `source_session_id` takes only that session's turns; a run without it whose
overlapping turns come from more than one (backend, session) gets none of them: they turn
`ambiguous` (REVIEW M-3). A `unknown`-backend run is matched by either backend under the same rule
(REVIEW M-2). Several overlapping runs make the turn `ambiguous`, none makes it `unattributed`;
usage is never split by estimate. Only direct-session runs receive the attributed sum; a single
wrapper or imported run is `measured_elsewhere` (it records its own usage, so adding the turn would
double count). A turn without any usage count (a local slash command, no reply yet) is `no_usage`
and never touches a sum (REVIEW H-1).

A turn spans [ts, ended_at]. An unfinished turn ends at its last activity (`active_at`); only the
last turn of a file written in the last OPEN_TURN_SEC is open until now (REVIEW H-1).

Per-turn decisions live in the collector's `native_attribution` table (counts and identifiers only),
keyed by turn id and expired with the turn's content (llm_view._expire). A run's usage is always
recomputed from those rows, so a re-collected or grown turn replaces its earlier contribution.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from agent_platform_mcp import events
from agent_platform_mcp.tools import projects, store

SOURCE = store.ATTRIBUTION_SOURCE
COUNTS = ('input_tokens', 'output_tokens', 'cache_read_tokens', 'cache_write_tokens')
STATUSES = ('attributed', 'ambiguous', 'unattributed', 'measured_elsewhere', 'no_usage')
UNKNOWN = 'unknown'  # `state start` outside a detectable host (observation.host_backend)
OPEN_TURN_SEC = 60  # a transcript written this recently may still be appended to
SCHEMA = '''CREATE TABLE IF NOT EXISTS native_attribution (turn_id TEXT PRIMARY KEY, project_id TEXT, workspace TEXT NOT NULL,
    backend TEXT NOT NULL, session_id TEXT, ts TEXT, status TEXT NOT NULL, run_id TEXT, candidates_json TEXT NOT NULL,
    usage_json TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS native_attribution_run ON native_attribution(run_id);
CREATE INDEX IF NOT EXISTS native_attribution_scan ON native_attribution(project_id, status, ts);'''


def migrate(db: sqlite3.Connection) -> None:
    """The table is derived data: a pre-session_id table is dropped and refilled by the PARSER_VERSION reparse."""
    columns = {row[1] for row in db.execute('PRAGMA table_info(native_attribution)')}
    if columns and 'session_id' not in columns:
        db.execute('DROP TABLE native_attribution')


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
    """LLM runs that could own a turn, keyed by owner and by session workspace; point runs (no backend,
    or the L-4 marker) are left out."""
    result = {}
    for run_id, event_json, started, ended in state.connection.execute(
            "SELECT run_id,event_json,started_at,ended_at FROM runs WHERE json_extract(event_json,'$.backend') IN (?,?,?)",
            ('claude', 'codex', UNKNOWN)):
        event = json.loads(event_json)
        payload = event.get('payload') or {}
        if payload.get('point'):
            continue
        run = {'run_id': run_id, 'source': event.get('collection_source'), 'start': _time(started), 'end': _time(ended),
               'session': payload.get('source_session_id')}
        keys = {_owner(event['backend'], event.get('project_id'), payload.get('workspace'))}
        if payload.get('session_workspace'):
            keys.add((event['backend'], 'session', payload['session_workspace']))
        for key in keys:
            result.setdefault(key, []).append(run)
    return result


def _session(turn: dict) -> str | None:
    """A forked Codex subagent belongs to its parent session (Claude subagent rows carry the parent's id)."""
    return turn.get('parent_session_id') or turn.get('session_id')


def decide(turn: dict, runs: dict[tuple, list[dict]], now: datetime, live: bool = False) -> tuple[str, str | None, list[str]]:
    """(status, run_id, candidate run ids). `live`: the turn may still be running (open until now)."""
    if not any(type((turn.get('usage') or {}).get(key)) is int for key in COUNTS):
        return 'no_usage', None, []
    start = _time(turn.get('ts'))
    if start is None:
        return 'unattributed', None, []
    end = _time(turn.get('ended_at')) or (now if live and turn.get('state') == 'running' else None) \
        or _time(turn.get('active_at')) or start
    matched = {}  # a run listed under both its owner and its session workspace counts once
    for backend in (turn['backend'], UNKNOWN):
        for key in (_owner(backend, turn.get('project_id'), turn['workspace']), (backend, 'session', turn['workspace'])):
            for run in runs.get(key, ()):
                if run['start'] is not None and run['start'] <= end and (run['end'] or now) >= start \
                        and run['session'] in (None, _session(turn)):
                    matched[run['run_id']] = run
    found = list(matched.values())
    ids = sorted(matched)
    if not found:
        return 'unattributed', None, ids
    if len(found) > 1:
        return 'ambiguous', None, ids
    return ('attributed' if found[0]['source'] == 'direct' else 'measured_elsewhere'), found[0]['run_id'], ids


def record(content: sqlite3.Connection, turns: list[dict], runs: dict[tuple, list[dict]], now: datetime,
           live_last: bool = False) -> tuple[dict, set[str]]:
    """Upsert each turn's decision inside the caller's content transaction; returns counts and touched run ids
    (every candidate too, so a run whose turns now span several sessions is re-checked in `apply`)."""
    counts = dict.fromkeys(STATUSES, 0)
    touched = set()
    for index, turn in enumerate(turns):
        status, run_id, ids = decide(turn, runs, now, live_last and index == len(turns) - 1)
        counts[status] += 1
        old = content.execute('SELECT run_id FROM native_attribution WHERE turn_id=?', (turn['run_id'],)).fetchone()
        if old and old[0]:
            touched.add(old[0])
        touched.update(ids)
        start = _time(turn.get('ts'))
        usage = {key: turn['usage'].get(key) for key in COUNTS}
        content.execute('INSERT OR REPLACE INTO native_attribution VALUES (?,?,?,?,?,?,?,?,?,?)',
                        (turn['run_id'], turn.get('project_id'), turn['workspace'], turn['backend'], _session(turn),
                         start.isoformat() if start else None, status, run_id if status == 'attributed' else None,
                         json.dumps(ids), json.dumps(usage)))
    return counts, touched


def total(rows: list[dict]) -> events.Usage:
    """Field sums; a field unknown in any turn stays null. `full` needs input/output in every turn
    (the events contract: cache counts may be null in full usage). Rows without any count are ignored."""
    rows = [row for row in rows if any(type(row.get(key)) is int for key in COUNTS)]
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


def apply(state: store.Store, content: sqlite3.Connection, run_ids: set[str], runs: dict[tuple, list[dict]]) -> tuple[int, int]:
    """Write the recomputed sum of each touched direct run; returns (runs changed, turns made ambiguous
    because a session-less run overlaps turns of more than one backend/session)."""
    known = {run['run_id']: run for group in runs.values() for run in group}
    changed = regrouped = 0
    for run_id in sorted(run_ids):
        run = known.get(run_id)
        if run is None or run['source'] != 'direct':
            continue  # wrapper/imported runs keep their own usage; a purged run has nothing to update
        if run['session'] is None and len(content.execute(
                "SELECT DISTINCT backend,session_id FROM native_attribution WHERE status<>'no_usage' AND candidates_json LIKE ?",
                (f'%"{run_id}"%',)).fetchall()) > 1:  # run ids are UUIDs: no LIKE wildcards
            regrouped += content.execute("UPDATE native_attribution SET status='ambiguous',run_id=NULL WHERE run_id=?",
                                         (run_id,)).rowcount
        rows = [json.loads(row[0]) for row in content.execute(
            "SELECT usage_json FROM native_attribution WHERE run_id=? AND status='attributed'", (run_id,))]
        changed += state.attributed_usage(run_id, total(rows))
    return changed, regrouped


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
