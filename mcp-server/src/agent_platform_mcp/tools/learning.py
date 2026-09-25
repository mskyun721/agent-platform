"""Explicit, project-scoped feedback; text never enters observation snapshots."""
import hashlib
import json
import os
import sqlite3
import time
from contextlib import contextmanager
from uuid import UUID, NAMESPACE_URL, uuid5

from agent_platform_mcp import config
from agent_platform_mcp.tools import projects, store, llm_view
from agent_platform_mcp.tools.stdout_artifacts import _mask

SCHEMA = '''CREATE TABLE feedback (
 id TEXT PRIMARY KEY, workspace TEXT NOT NULL, project_id TEXT,
 source_kind TEXT NOT NULL, source_id TEXT, backend TEXT, kind TEXT NOT NULL,
 summary_hash TEXT NOT NULL, created_at REAL NOT NULL);
 CREATE INDEX feedback_workspace ON feedback(workspace,created_at);'''
RETENTION = 30 * 86400


def context(root):
    if not root:
        raise ValueError('explicit project root required')
    return config.resolve_project(root)


@contextmanager
def content_db():
    with store.open() as state:
        path = state.path.parent / 'learning.db'
    projects._safe_storage(path)
    for suffix in ('-journal', '-wal', '-shm'):
        projects._safe_storage(path.with_name(path.name + suffix))
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    os.fchmod(fd, 0o600)
    os.close(fd)
    db = sqlite3.connect(path, timeout=5)
    try:
        db.execute('PRAGMA secure_delete=ON')
        db.execute('CREATE TABLE IF NOT EXISTS content (id TEXT PRIMARY KEY, summary TEXT, expires REAL)')
        with db:
            db.execute('DELETE FROM content WHERE expires <= ?', (time.time(),))
            yield db
    finally:
        db.close()


def source(workspace, kind, identity):
    if kind == 'manual':
        if identity is not None:
            raise ValueError('manual feedback has no source id')
        return None
    if kind not in ('platform_run', 'native_turn') or not identity:
        raise ValueError('source kind/id required')
    identity = str(UUID(identity))
    if kind == 'platform_run':
        with store.open() as db:
            run = db.run(identity)
        path, backend = run['payload']['workspace'], run.get('backend')
    else:
        with llm_view.content_db() as db:
            row = db.execute('SELECT workspace,payload_json FROM native_runs WHERE run_id=?', (identity,)).fetchone()
        if row is None:
            raise ValueError('unknown or expired native turn')
        path, backend = row[0], json.loads(row[1]).get('backend')
    if path != workspace:
        raise ValueError('source belongs to another workspace')
    return backend if backend in ('claude', 'codex') else None


def add(root, source_kind, source_id, kind, summary):
    ctx = context(root)
    workspace = str(ctx.path)
    if kind not in ('correction', 'failure', 'suggestion'):
        raise ValueError('unknown feedback kind')
    if not isinstance(summary, str) or not summary.strip() or len(summary) > 2000:
        raise ValueError('summary requires 1..2000 characters')
    summary = _mask(summary.strip())
    backend = source(workspace, source_kind, source_id)
    if source_id:
        source_id = str(UUID(source_id))
    digest = hashlib.sha256(summary.encode()).hexdigest()
    identity = str(uuid5(NAMESPACE_URL, json.dumps([workspace, source_kind, source_id, kind, digest])))
    with store.open() as db, db.connection:
        db.connection.execute('INSERT OR IGNORE INTO feedback VALUES (?,?,?,?,?,?,?,?,?)',
            (identity, workspace, ctx.project_id, source_kind, source_id, backend, kind, digest, time.time()))
    # Independent sidecar write guarded against a concurrent metadata purge.
    with store.open() as state, state.connection:
        state.connection.execute('BEGIN IMMEDIATE')
        if not state.connection.execute('SELECT 1 FROM feedback WHERE id=?', (identity,)).fetchone():
            raise ValueError('feedback was concurrently purged; retry explicitly')
        with content_db() as db:
            db.execute('INSERT OR IGNORE INTO content VALUES (?,?,?)', (identity, summary, time.time() + RETENTION))
    return show(root, identity)


def show(root, identity):
    workspace = str(context(root).path)
    identity = str(UUID(identity))
    with store.open() as db:
        row = db.connection.execute('SELECT * FROM feedback WHERE id=? AND workspace=?', (identity, workspace)).fetchone()
    if row is None:
        raise ValueError('unknown feedback for workspace')
    result = dict(row)
    with content_db() as db:
        text = db.execute('SELECT summary FROM content WHERE id=?', (identity,)).fetchone()
    result.update(summary=text[0] if text else None, content_status='available' if text else 'missing')
    try:
        source(workspace, result['source_kind'], result['source_id'])
        result['evidence_status'] = 'manual' if result['source_kind'] == 'manual' else 'available'
    except ValueError:
        result['evidence_status'] = 'unavailable'
    return result


def list_feedback(root):
    workspace = str(context(root).path)
    with store.open() as db:
        rows = db.connection.execute('SELECT * FROM feedback WHERE workspace=? ORDER BY created_at DESC LIMIT 100', (workspace,)).fetchall()
    return {'workspace': workspace, 'feedback': [dict(row) for row in rows], 'limit': 100}


def purge(root):
    workspace = str(context(root).path)
    # Hold the metadata write lock across sidecar deletion to serialize add/purge.
    with store.open() as db, db.connection:
        db.connection.execute('BEGIN IMMEDIATE')
        ids = db.connection.execute('SELECT id FROM feedback WHERE workspace=?', (workspace,)).fetchall()
        with content_db() as content:
            content.executemany('DELETE FROM content WHERE id=?', [(row[0],) for row in ids])
        db.connection.execute('DELETE FROM feedback WHERE workspace=?', (workspace,))
    return {'workspace': workspace, 'deleted': len(ids)}
