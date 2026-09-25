"""Local diagnostic metadata; configured hooks are never executed as probes."""
import json
import shutil
import subprocess
import time
from pathlib import Path

from agent_platform_mcp import config
from agent_platform_mcp.tools import projects, llm_view


def observation_status(root):
    ctx = config.resolve_project(root)
    workspace = str(ctx.path)
    with llm_view.content_db() as db:
        capture = db.execute('SELECT enabled FROM capture WHERE workspace=?', (workspace,)).fetchone()
        row = db.execute('SELECT payload_json FROM collector_health WHERE name=?', ('native',)).fetchone()
        health = json.loads(row[0]) if row else {}
        rows = db.execute('SELECT payload_json FROM native_runs WHERE workspace=?', (workspace,)).fetchall()
    age = max(0, time.time() - health['checked_at']) if isinstance(health.get('checked_at'), (int, float)) else None
    collector = {'status': 'unknown' if age is None else 'stale' if age > 30 else 'observed',
                 'age_sec': age, 'last_poll': health,
                 'limitation': 'A recent poll is not proof that a particular active session was captured.'}
    if health.get('error') and age is not None and age <= 30:
        collector['status'] = 'error'
    runs = [json.loads(r[0]) for r in rows]
    backends = {}
    for backend in ('claude', 'codex'):
        subset = [r for r in runs if r.get('backend') == backend]
        latest = max(subset, key=lambda r: r.get('ts') or '', default={})
        backends[backend] = {'stored_turns': len(subset), 'latest_turn_at': latest.get('ts'),
                             'latest_session_id': latest.get('session_id'), 'latest_run_id': latest.get('run_id'),
                             'active_session_status': 'unknown'}
    return {'workspace': workspace, 'capture_enabled': bool(capture and capture[0]),
            'collection_scope': 'platform-only', 'supported_workspace': ctx.path == config.ROOT.resolve(),
            'collector': collector, 'backends': backends}


def hooks(root):
    result = {}
    for backend, rel in (('claude', '.claude/settings.json'), ('codex', '.codex/hooks.json')):
        path = root / rel
        try:
            projects._safe_storage(path)
            if not path.exists():
                result[backend] = {'status': 'missing', 'runtime_status': 'unknown'}
                continue
            if path.stat().st_size > 1024 * 1024:
                raise ValueError('configuration too large')
            data = json.loads(path.read_text()).get('hooks', {})
            if not isinstance(data, dict):
                raise ValueError('invalid hooks')
            result[backend] = {'status': 'configured' if data else 'missing', 'events': sorted(data),
                               'runtime_status': 'unknown', 'scope': 'project-file-only'}
        except (OSError, ValueError, AttributeError):
            result[backend] = {'status': 'invalid', 'runtime_status': 'unknown'}
    return result


def diagnose(root):
    if not root:
        raise ValueError('explicit project root required')
    ctx = config.resolve_project(root)
    binaries = {}
    for name in ('claude', 'codex'):
        executable = shutil.which(name)
        item = {'installed': bool(executable), 'version': None}
        if executable:
            try:
                result = subprocess.run([executable, '--version'], capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    item['version'] = result.stdout.strip()[:100]
            except (OSError, subprocess.TimeoutExpired):
                pass
        binaries[name] = item
    result = {'workspace': str(ctx.path), 'cli': binaries, 'hooks': hooks(ctx.path)}
    try:
        result['observation'] = observation_status(root)
    except Exception as exc:
        result['observation'] = {'status': 'unavailable', 'error': type(exc).__name__}
    return result
