"""Local LLM run viewer. Opt-in content is separate from metadata snapshots."""

import json
import os
import secrets
import sqlite3
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

from agent_platform_mcp import config
from agent_platform_mcp.tools import projects, store
from agent_platform_mcp.tools.stdout_artifacts import _mask

MAX_TEXT = 64 * 1024
RETENTION = 7 * 86400
ASSETS = Path(__file__).with_name('llm_view_assets')


@contextmanager
def content_db():
    with store.open() as state:
        path = state.path.parent / 'llm-content.db'
    projects._safe_storage(path)
    for suffix in ('-journal', '-wal', '-shm'):
        projects._safe_storage(Path(str(path) + suffix))
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    os.fchmod(fd, 0o600)
    os.close(fd)
    db = sqlite3.connect(path, timeout=5)
    db.row_factory = sqlite3.Row
    try:
        db.execute('PRAGMA secure_delete=ON')
        db.executescript('''CREATE TABLE IF NOT EXISTS capture (workspace TEXT PRIMARY KEY, enabled INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS content (run_id TEXT PRIMARY KEY, expires REAL NOT NULL,
                prompt TEXT, response TEXT, prompt_truncated INTEGER, response_truncated INTEGER);
            CREATE TABLE IF NOT EXISTS native_runs (run_id TEXT PRIMARY KEY, expires REAL, workspace TEXT, payload_json TEXT);
            CREATE TABLE IF NOT EXISTS native_suppressed (run_id TEXT PRIMARY KEY);
            CREATE TABLE IF NOT EXISTS native_files (path TEXT PRIMARY KEY, signature TEXT);''')
        with db:
            db.execute('DELETE FROM content WHERE expires <= ?', (time.time(),))
            db.execute('INSERT OR IGNORE INTO native_suppressed SELECT run_id FROM native_runs WHERE expires <= ?', (time.time(),))
            db.execute('DELETE FROM native_runs WHERE expires <= ?', (time.time(),))
            yield db
    finally:
        db.close()


def configure(root, enabled):
    context = config.resolve_project(root)
    with content_db() as db:
        db.execute('INSERT INTO capture VALUES (?,?) ON CONFLICT(workspace) DO UPDATE SET enabled=excluded.enabled',
                   (str(context.path), int(enabled)))
    return {'workspace': str(context.path), 'capture_enabled': enabled, 'retention_days': 7}


def record(run_id, *, prompt=None, response=None):
    """Capture only explicit text; never discover/read source or transcript files."""
    run_id = str(UUID(run_id))
    with store.open() as db:
        run = db.run(run_id)
    with content_db() as db:
        enabled = db.execute('SELECT enabled FROM capture WHERE workspace=?', (run['payload']['workspace'],)).fetchone()
        if not enabled or not enabled[0]:
            return {'status': 'disabled'}
        values = {}
        for name, value in (('prompt', prompt), ('response', response)):
            if value is not None:
                if not isinstance(value, str):
                    raise ValueError('content must be text')
                # Mask before truncating so a clipped secret does not evade masking.
                text = _mask(value)
                values[name] = text[:MAX_TEXT]
                values[name + '_truncated'] = len(text) > MAX_TEXT
        db.execute('INSERT OR IGNORE INTO content(run_id,expires) VALUES (?,?)', (run_id, time.time() + RETENTION))
        for key, value in values.items():
            # Keys come only from the fixed tuple above.
            db.execute(f'UPDATE content SET {key}=? WHERE run_id=?', (value, run_id))
    return {'status': 'captured'}


def purge():
    with content_db() as db:
        count = db.execute('SELECT COUNT(*) FROM content').fetchone()[0]
        db.execute('DELETE FROM content')
        count += db.execute('SELECT COUNT(*) FROM native_runs').fetchone()[0]
        db.execute('INSERT OR IGNORE INTO native_suppressed SELECT run_id FROM native_runs')
        db.execute('DELETE FROM native_runs')
    return {'deleted': count}


def _summary(db, run):
    row = db.connection.execute('SELECT payload_json FROM usage WHERE run_id=?', (run['run_id'],)).fetchone()
    ended = db.connection.execute("SELECT event_json FROM events WHERE run_id=? AND event_type='run_ended' ORDER BY rowid DESC LIMIT 1",
                                  (run['run_id'],)).fetchone()
    duration = json.loads(ended[0])['payload'].get('duration_sec') if ended else None
    return {key: run[key] for key in ('run_id', 'project_id', 'task_id', 'role', 'backend', 'model', 'ts', 'ended_at', 'outcome', 'state')} | {
        'workspace': run['payload']['workspace'], 'duration_sec': duration,
        'usage': json.loads(row[0]) if row else None, 'collection_source': run['collection_source']}


def list_runs(limit=100):
    if type(limit) is not int or not 1 <= limit <= 500:
        raise ValueError('limit must be 1..500')
    with store.open() as db:
        rows = db.connection.execute('SELECT run_id FROM runs ORDER BY started_at DESC, rowid DESC LIMIT ?', (limit,)).fetchall()
        total = db.connection.execute('SELECT COUNT(*) FROM runs').fetchone()[0]
        runs = [_summary(db, db.run(row[0])) for row in rows]
    with content_db() as content:
        native = [json.loads(r[0]) for r in content.execute('SELECT payload_json FROM native_runs')]
    runs.extend({k: v for k, v in r.items() if k not in ('content', 'events')} for r in native)
    runs.sort(key=lambda r: r.get('ts') or '', reverse=True)
    return {'runs': runs[:limit], 'total': total + len(native), 'limit': limit}


def detail(run_id):
    run_id = str(UUID(run_id))
    with content_db() as content:
        native = content.execute('SELECT payload_json FROM native_runs WHERE run_id=?', (run_id,)).fetchone()
        if native:
            return json.loads(native[0])
    with store.open() as db:
        result = _summary(db, db.run(run_id))
        result['events'] = [json.loads(row[0]) for row in db.connection.execute(
            'SELECT event_json FROM events WHERE run_id=? ORDER BY ts,rowid', (run_id,))]
    with content_db() as db:
        row = db.execute('SELECT * FROM content WHERE run_id=?', (run_id,)).fetchone()
        result['content'] = {'status': 'captured', **dict(row)} if row else {'status': 'not_captured'}
    return result


def make_server(port=8765):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # Never log auth, prompt, output or request paths.

        def send(self, status, body, mime='application/json; charset=utf-8'):
            self.send_response(status)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            host = f'127.0.0.1:{self.server.server_port}'
            if self.headers.get('Host') != host or self.headers.get('Origin') not in (None, 'http://' + host):
                return self.send(403, b'{"error":"forbidden"}')
            url = urlsplit(self.path)
            assets = {'/': ('index.html', 'text/html'), '/app.js': ('app.js', 'text/javascript'), '/style.css': ('style.css', 'text/css')}
            if url.path in assets:
                name, mime = assets[url.path]
                return self.send(200, (ASSETS / name).read_bytes(), mime + '; charset=utf-8')
            expected = 'Bearer ' + self.server.access_token
            if not secrets.compare_digest(self.headers.get('Authorization', ''), expected):
                return self.send(403, b'{"error":"authentication required"}')
            try:
                if url.path == '/api/runs':
                    result = list_runs(int(parse_qs(url.query).get('limit', ['100'])[0]))
                    result['collector'] = getattr(self.server, 'collector_status', {})
                elif url.path.startswith('/api/runs/'):
                    result = detail(url.path.removeprefix('/api/runs/'))
                else:
                    return self.send(404, b'{"error":"not found"}')
                self.send(200, json.dumps(result, ensure_ascii=False).encode())
            except ValueError:
                self.send(400, b'{"error":"invalid or unknown run"}')
            except Exception:
                self.send(503, b'{"error":"observation storage unavailable"}')

    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    server.access_token = secrets.token_urlsafe(32)
    return server


def serve(port=8765):
    import threading
    from agent_platform_mcp.tools import native_sessions
    stop = threading.Event()
    with make_server(port) as server:
        def refresh():
            while not stop.is_set():
                try:
                    server.collector_status = native_sessions.collect()
                except Exception as exc:
                    server.collector_status = {'error': type(exc).__name__}
                stop.wait(5)
        worker = threading.Thread(target=refresh, daemon=True)
        worker.start()
        print(f'LLM Observability: http://127.0.0.1:{server.server_port}/#token={server.access_token}', flush=True)
        print('Local read-only viewer; Ctrl+C to stop. Content cleanup runs on access every 7-day expiry.', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            stop.set()
            worker.join(timeout=10)
