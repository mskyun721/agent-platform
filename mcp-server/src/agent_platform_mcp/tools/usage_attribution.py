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

Only runs that can overlap the turns are loaded and searched by start time (DBA F-1). An open run
(`ended_at IS NULL`) is a candidate only while it started at most MAX_OPEN before the turn: an older one
lost its `state end` and is stale, never matched, and counted by `stale_open` (DBA F-7). `prepare` does
every read and decision before the collector's content write transaction, `write` only inserts and
regroups, and the run sums go to state.db after the content commit in one transaction (DBA F-3).
"""

from __future__ import annotations

import bisect
import json
import sqlite3
from datetime import datetime, timedelta, timezone

from agent_platform_mcp import events
from agent_platform_mcp.tools import projects, store

SOURCE = store.ATTRIBUTION_SOURCE
COUNTS = ('input_tokens', 'output_tokens', 'cache_read_tokens', 'cache_write_tokens')
STATUSES = ('attributed', 'ambiguous', 'unattributed', 'measured_elsewhere', 'no_usage')
UNKNOWN = 'unknown'  # `state start` outside a detectable host (observation.host_backend)
OPEN_TURN_SEC = 60  # a transcript written this recently may still be appended to
MARGIN = timedelta(days=1)
MAX_OPEN = timedelta(days=7)  # = llm_view.RETENTION: an open run older than any retained turn is stale (DBA F-7)
LLM_RUNS = "json_extract(event_json,'$.backend') IN (?,?,?)"
SCHEMA = '''CREATE TABLE IF NOT EXISTS native_attribution (turn_id TEXT PRIMARY KEY, project_id TEXT, workspace TEXT NOT NULL,
    backend TEXT NOT NULL, session_id TEXT, ts TEXT, status TEXT NOT NULL, run_id TEXT, candidates_json TEXT NOT NULL,
    usage_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS native_pending (run_id TEXT PRIMARY KEY);
CREATE INDEX IF NOT EXISTS native_attribution_run ON native_attribution(run_id);
CREATE INDEX IF NOT EXISTS native_attribution_scan ON native_attribution(project_id, status, ts);'''


def migrate(db: sqlite3.Connection) -> None:
    """The table is derived data: a pre-session_id table is dropped and refilled by the PARSER_VERSION reparse.
    The check repeats under BEGIN IMMEDIATE so two processes opening the DB together drop it once (DBA F-4).
    Later schema changes add columns with ALTER TABLE ... ADD COLUMN instead: a DROP loses run sums of
    transcripts that are no longer on disk when a run is recomputed (REVIEW N-5)."""
    def stale():
        columns = {row[1] for row in db.execute('PRAGMA table_info(native_attribution)')}
        return bool(columns) and 'session_id' not in columns
    if not stale():
        return
    with db:
        db.execute('BEGIN IMMEDIATE')
        if stale():
            db.execute('DROP TABLE IF EXISTS native_attribution')


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


def _group(runs: list[dict]) -> dict:
    """Closed runs sorted by start (with the longest span, for an interval search) and open runs apart."""
    closed = sorted((run for run in runs if run['end'] is not None), key=lambda run: run['start'])
    return {'closed': closed, 'starts': [run['start'] for run in closed], 'open': [run for run in runs if run['end'] is None],
            'longest': max((run['end'] - run['start'] for run in closed), default=timedelta(0))}


def runs_of(runs: dict[tuple, dict]) -> dict[str, dict]:
    return {run['run_id']: run for group in runs.values() for run in group['closed'] + group['open']}


def candidates(state: store.Store, window: tuple[datetime, datetime] | None = None) -> dict[tuple, dict]:
    """LLM runs that could own a turn, keyed by owner and by session workspace; point runs (no backend,
    or the L-4 marker) are left out. With `window` (the turns' first start, last end) only runs that can
    overlap it are read (DBA F-1): the collected turns sit in the retention window, so this is the
    `now - RETENTION` bound computed from the turns themselves. An open run must have started within
    MAX_OPEN of the window (DBA F-7). The scan is 12 ms at 100k runs, so no index is added (ADR-012)."""
    where, args = LLM_RUNS, ('claude', 'codex', UNKNOWN)
    if window is not None:  # a day of slack for timestamp formatting; the exact check is in decide()
        where = '(ended_at>=? OR (ended_at IS NULL AND started_at>=?)) AND started_at<=? AND ' + where
        args = ((window[0] - MARGIN).isoformat(), (window[0] - MAX_OPEN - MARGIN).isoformat(),
                (window[1] + MARGIN).isoformat(), *args)
    result = {}
    for run_id, event_json, started, ended in state.connection.execute(
            f'SELECT run_id,event_json,started_at,ended_at FROM runs WHERE {where}', args):  # fixed fragments only
        event = json.loads(event_json)
        payload = event.get('payload') or {}
        if payload.get('point') or _time(started) is None:
            continue
        run = {'run_id': run_id, 'source': event.get('collection_source'), 'start': _time(started), 'end': _time(ended),
               'session': payload.get('source_session_id')}
        keys = {_owner(event['backend'], event.get('project_id'), payload.get('workspace'))}
        if payload.get('session_workspace'):
            keys.add((event['backend'], 'session', payload['session_workspace']))
        for key in keys:
            result.setdefault(key, []).append(run)
    return {key: _group(group) for key, group in result.items()}


def cached(state: store.Store, span: tuple[datetime, datetime], cache: dict) -> dict[tuple, dict]:
    """candidates() once per UTC day range within one collect (DBA F-8). The load is not filtered by project
    or backend, so the day range alone is the key; whole days are a superset (decide() checks exact spans)."""
    low = span[0].replace(hour=0, minute=0, second=0, microsecond=0)
    high = span[1].replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    if (low, high) not in cache:
        cache[(low, high)] = candidates(state, (low, high))
    return cache[(low, high)]


def stale_open(state: store.Store, now: datetime) -> int:
    """Open LLM runs started more than MAX_OPEN ago: never candidates; `state close-stale` ends them (DBA F-7)."""
    return state.connection.execute(f'SELECT count(*) FROM runs WHERE ended_at IS NULL AND started_at<? AND {LLM_RUNS}',
                                    ((now - MAX_OPEN).isoformat(), 'claude', 'codex', UNKNOWN)).fetchone()[0]


def _session(turn: dict) -> str | None:
    """A forked Codex subagent belongs to its parent session (Claude subagent rows carry the parent's id)."""
    return turn.get('parent_session_id') or turn.get('session_id')


def _span(turn: dict, now: datetime, live: bool) -> tuple[datetime, datetime] | None:
    start = _time(turn.get('ts'))
    if start is None:
        return None
    return start, (_time(turn.get('ended_at')) or (now if live and turn.get('state') == 'running' else None)
                   or _time(turn.get('active_at')) or start)


def window(turns: list[dict], now: datetime, live_last: bool = False) -> tuple[datetime, datetime] | None:
    """The span the runs of these turns can lie in; None when no turn has a start."""
    spans = [span for index, turn in enumerate(turns) if (span := _span(turn, now, live_last and index == len(turns) - 1))]
    return (min(span[0] for span in spans), max(span[1] for span in spans)) if spans else None


def _overlapping(group: dict, start: datetime, end: datetime, now: datetime):
    """Interval search: closed runs starting in [start - longest, end] that end at or after start, then open
    runs started in [start - MAX_OPEN, end] (an older open run is stale, DBA F-7)."""
    low = bisect.bisect_left(group['starts'], start - group['longest'])
    high = bisect.bisect_right(group['starts'], end)
    yield from (run for run in group['closed'][low:high] if run['end'] >= start)
    yield from (run for run in group['open'] if start - MAX_OPEN <= run['start'] <= end and now >= start)


def decide(turn: dict, runs: dict[tuple, dict], now: datetime, live: bool = False) -> tuple[str, str | None, list[str]]:
    """(status, run_id, candidate run ids). `live`: the turn may still be running (open until now)."""
    if not any(type((turn.get('usage') or {}).get(key)) is int for key in COUNTS):
        return 'no_usage', None, []
    span = _span(turn, now, live)
    if span is None:
        return 'unattributed', None, []
    matched = {}  # a run listed under both its owner and its session workspace counts once
    for backend in (turn['backend'], UNKNOWN):
        for key in (_owner(backend, turn.get('project_id'), turn['workspace']), (backend, 'session', turn['workspace'])):
            if key in runs:
                matched.update((run['run_id'], run) for run in _overlapping(runs[key], *span, now)
                               if run['session'] in (None, _session(turn)))
    found = list(matched.values())
    ids = sorted(matched)
    if not found:
        return 'unattributed', None, ids
    if len(found) > 1:
        return 'ambiguous', None, ids
    return ('attributed' if found[0]['source'] == 'direct' else 'measured_elsewhere'), found[0]['run_id'], ids


def prepare(content: sqlite3.Connection, turns: list[dict], runs: dict[tuple, dict], now: datetime,
            live_last: bool = False) -> dict:
    """Every read and decision for one transcript's turns, made before the content write transaction
    (DBA F-3). A session-less direct run whose overlapping turns come from more than one (backend, session)
    gets none of them: its turns turn `ambiguous`. Counts are the turns' final statuses after that pass;
    `moved` lists earlier turns the pass took away from a run."""
    known, rows, found, touched = runs_of(runs), [], [], set()
    for index, turn in enumerate(turns):
        status, run_id, ids = decide(turn, runs, now, live_last and index == len(turns) - 1)
        old = content.execute('SELECT run_id FROM native_attribution WHERE turn_id=?', (turn['run_id'],)).fetchone()
        touched.update(ids, [old[0]] if old and old[0] else [])
        start = _time(turn.get('ts'))
        rows.append([turn['run_id'], turn.get('project_id'), turn['workspace'], turn['backend'], _session(turn),
                     start.isoformat() if start else None, status, run_id if status == 'attributed' else None,
                     json.dumps(ids), json.dumps({key: turn['usage'].get(key) for key in COUNTS})])
        found.append(ids)
    batch = {row[0] for row in rows}
    sums, regroup, moved, regrouped = {}, [], set(), 0
    for run_id in sorted(touched):
        run = known.get(run_id)
        if run is None or run['source'] != 'direct':
            continue  # wrapper/imported runs keep their own usage; a purged run has nothing to update
        older = [(turn_id, usage) for turn_id, usage in content.execute(
            "SELECT turn_id,usage_json FROM native_attribution WHERE run_id=? AND status='attributed'", (run_id,))
            if turn_id not in batch]
        mine = [row for row, ids in zip(rows, found) if run_id in ids and row[6] != 'no_usage']
        if run['session'] is None:
            sessions = {(backend, session) for backend, session, turn_id in content.execute(
                "SELECT backend,session_id,turn_id FROM native_attribution WHERE status<>'no_usage' AND candidates_json LIKE ?",
                (f'%"{run_id}"%',)) if turn_id not in batch}  # run ids are UUIDs: no LIKE wildcards (DBA F-5)
            if len(sessions | {(row[3], row[4]) for row in mine}) > 1:
                regroup.append(run_id)
                moved.update(turn_id for turn_id, _ in older)
                regrouped += len(older) + sum(row[7] == run_id for row in mine)
                for row in mine:
                    if row[7] == run_id:
                        row[6], row[7] = 'ambiguous', None
                older = []
        sums[run_id] = total([json.loads(usage) for _, usage in older]
                             + [json.loads(row[9]) for row in rows if row[7] == run_id])
    counts = dict.fromkeys(STATUSES, 0)
    for row in rows:
        counts[row[6]] += 1
    return {'rows': rows, 'regroup': regroup, 'sums': sums, 'counts': counts, 'regrouped': regrouped,
            'moved': moved, 'attributed': {row[0] for row in rows if row[6] == 'attributed'}}


def write(content: sqlite3.Connection, plan: dict) -> None:
    """The content transaction part: inserts of the prepared rows, the regroup of earlier turns and the
    pending marks of the runs whose sums go to state.db next (cleared once written, REVIEW N-7)."""
    content.executemany('INSERT OR REPLACE INTO native_attribution VALUES (?,?,?,?,?,?,?,?,?,?)', plan['rows'])
    content.executemany('INSERT OR IGNORE INTO native_pending VALUES (?)', [(run_id,) for run_id in plan['sums']])
    for run_id in plan['regroup']:
        content.execute("UPDATE native_attribution SET status='ambiguous',run_id=NULL WHERE run_id=?", (run_id,))


def resync(content: sqlite3.Connection, state: store.Store) -> list[str]:
    """Rewrites the sums of pending runs from their committed rows (REVIEW N-7): a state write that failed
    after the content commit converges even when its transcript is never collected again. Purged runs are dropped."""
    pending = [row[0] for row in content.execute('SELECT run_id FROM native_pending')]
    if not pending:
        return []
    live = [run_id for run_id in pending if state.connection.execute('SELECT 1 FROM runs WHERE run_id=?', (run_id,)).fetchone()]
    changed = state.attributed_usage({run_id: total([json.loads(row[0]) for row in content.execute(
        "SELECT usage_json FROM native_attribution WHERE run_id=? AND status='attributed'", (run_id,))]) for run_id in live})
    content.executemany('DELETE FROM native_pending WHERE run_id=?', [(run_id,) for run_id in pending])
    content.commit()
    return changed


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
