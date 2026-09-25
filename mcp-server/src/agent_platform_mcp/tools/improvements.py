"""Evidence-bound, explicitly reviewed changes to platform instruction files."""
import difflib
import hashlib
import json
import os
import tempfile
import time
from pathlib import Path
from uuid import UUID, uuid4

from agent_platform_mcp import config
from agent_platform_mcp.tools import learning, store, projects, improvement_evals
from agent_platform_mcp.tools.stdout_artifacts import _mask

SCHEMA = 'CREATE TABLE improvements (id TEXT PRIMARY KEY, workspace TEXT NOT NULL, payload_json TEXT NOT NULL);'
MAX_TEXT = 65536


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def _target(root, relative):
    path = Path(relative)
    if path.is_absolute() or len(path.parts) != 3 or '..' in path.parts or path.parts[:2] not in (
            ('standards', 'agents'), ('standards', 'reference')) or path.suffix != '.md':
        raise ValueError('target must be a direct Markdown file under standards/agents or standards/reference')
    target = root / path
    projects._safe_storage(target)
    if not target.is_file() or target.stat().st_size > MAX_TEXT:
        raise ValueError('target missing or oversized')
    return target


def _save(item):
    with store.open() as db, db.connection:
        db.connection.execute('INSERT INTO improvements VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET payload_json=excluded.payload_json',
                              (item['id'], item['workspace'], json.dumps(item)))


def _load(root, identity):
    workspace = str(learning.context(root).path)
    with store.open() as db:
        row = db.connection.execute('SELECT payload_json FROM improvements WHERE id=? AND workspace=?',
                                    (str(UUID(identity)), workspace)).fetchone()
    if row is None:
        raise ValueError('unknown candidate for workspace')
    return json.loads(row[0])


def _body(item):
    with learning.content_db() as db:
        db.execute('CREATE TABLE IF NOT EXISTS improvement_content (id TEXT PRIMARY KEY, payload_json TEXT NOT NULL)')
        row = db.execute('SELECT payload_json FROM improvement_content WHERE id=?', (item['id'],)).fetchone()
    if row is None or digest(row[0]) != item['content_hash']:
        raise ValueError('candidate content missing or modified')
    if item['status'] in ('draft', 'evaluated', 'approved', 'rejected') and time.time() - item['created_at'] > learning.RETENTION:
        with learning.content_db() as db:
            db.execute('DELETE FROM improvement_content WHERE id=?', (item['id'],))
        raise ValueError('candidate expired; propose again')
    return json.loads(row[0])


def _evidence(root, item):
    feedback = learning.show(root, item['feedback_id'])
    if feedback['content_status'] != 'available' or feedback['evidence_status'] == 'unavailable':
        raise ValueError('feedback evidence unavailable')
    if feedback['summary_hash'] != item['feedback_hash']:
        raise ValueError('feedback changed')


def _current(item, body, variant):
    root = Path(item['workspace'])
    for rel, versions in body['files'].items():
        path = root / rel
        projects._safe_storage(path)
        if not path.is_file() or path.read_text() != versions[variant]:
            raise ValueError('target changed; review a new candidate or preserve user edits')


def propose(root, feedback_id, *, trigger, action, target, replacement):
    ctx = learning.context(root)
    feedback = learning.show(root, feedback_id)
    if feedback['content_status'] != 'available' or feedback['evidence_status'] == 'unavailable':
        raise ValueError('feedback evidence unavailable')
    for value, maximum in ((trigger, 2000), (action, 2000), (replacement, MAX_TEXT)):
        if not isinstance(value, str) or not value.strip() or len(value.encode()) > maximum or _mask(value) != value:
            raise ValueError('candidate text invalid, oversized or contains suspected secrets')
    path = _target(ctx.path, target)
    original = path.read_text()
    if _mask(original) != original or original == replacement:
        raise ValueError('target contains suspected secrets or replacement has no change')
    files = {target: {'before': original, 'after': replacement}}
    if Path(target).parts[1] == 'agents':
        # Keep the generated adapter's native frontmatter, replacing only its canonical body.
        import re
        role = Path(target).stem
        rel = f'.claude/agents/{role}.md'
        adapter = ctx.path / rel
        projects._safe_storage(adapter)
        old = adapter.read_text()
        header = re.match(r'\A---\r?\n.*?\r?\n---(?:\r?\n|$)', old, re.S)
        marker = f'<!-- generated from standards/agents/{role}.md; edit the source, then run scripts/sync_claude_settings.py --agents-only -->'
        if not header or old[header.end():] != marker + '\n' + original.strip() + '\n':
            raise ValueError('agent adapter is not synchronized; review it first')
        files[rel] = {'before': old, 'after': header.group(0).rstrip()+'\n'+marker+'\n'+replacement.strip()+'\n'}
    body = json.dumps({'trigger': trigger, 'action': action, 'files': files}, sort_keys=True)
    identity = str(uuid4())
    item = {'id': identity, 'workspace': str(ctx.path), 'feedback_id': feedback_id, 'feedback_hash': feedback['summary_hash'],
            'target': target, 'target_hash': digest(original), 'replacement_hash': digest(replacement),
            'content_hash': digest(body), 'status': 'draft', 'created_at': time.time(), 'evaluation': None, 'review': None}
    with learning.content_db() as db:
        db.execute('CREATE TABLE IF NOT EXISTS improvement_content (id TEXT PRIMARY KEY, payload_json TEXT NOT NULL)')
        db.execute('INSERT INTO improvement_content VALUES (?,?)', (identity, body))
    _save(item)
    return show(root, identity)


def show(root, identity):
    item = _load(root, identity)
    try:
        body = _body(item)
        if item['status'] not in ('applying', 'reverting'):
            _current(item, body, 'after' if item['status'] == 'applied' else 'before')
        item['diff'] = ''.join(''.join(difflib.unified_diff(v['before'].splitlines(True), v['after'].splitlines(True),
                             fromfile=p, tofile=p)) for p, v in body['files'].items())
        item['trigger'], item['action'] = body['trigger'], body['action']
    except (OSError, ValueError):
        item['stored_status'], item['status'] = item['status'], 'stale'
    return item


def list_candidates(root):
    workspace = str(learning.context(root).path)
    with store.open() as db:
        rows = db.connection.execute('SELECT payload_json FROM improvements WHERE workspace=? ORDER BY rowid DESC LIMIT 100', (workspace,)).fetchall()
    return {'candidates': [json.loads(r[0]) for r in rows], 'limit': 100}


def evaluate(root, identity, baseline, candidate):
    with projects._locked():
        item = _load(root, identity)
        if item['status'] not in ('draft', 'evaluated', 'approved', 'rejected'):
            raise ValueError('candidate cannot be evaluated in this state')
        # Every attempted re-evaluation invalidates earlier approval, including invalid inputs.
        item.update(status='draft', review=None, evaluation=None)
        _save(item)
        _evidence(root, item)
        _current(item, _body(item), 'before')
        item['evaluation'] = improvement_evals.compare(item, baseline, candidate)
        item['status'] = 'evaluated' if item['evaluation']['passed'] else 'draft'
        _save(item)
        return item


def _valid_evaluation(item):
    evaluation = item.get('evaluation')
    if not evaluation or not evaluation['passed']:
        raise ValueError('passing comparison required')
    checked = improvement_evals.compare(item, evaluation['baseline_ids'], evaluation['candidate_ids'])
    if not checked['passed'] or checked['record_hashes'] != evaluation['record_hashes']:
        raise ValueError('evaluation records changed; evaluate again')


def review(root, identity, decision, reviewer):
    if decision not in ('approved', 'rejected') or not isinstance(reviewer, str) or not reviewer.strip() or len(reviewer)>128 or _mask(reviewer)!=reviewer:
        raise ValueError('valid decision and reviewer identity required')
    with projects._locked():
        item = _load(root, identity)
        if item['status'] not in ('draft', 'evaluated', 'approved', 'rejected'):
            raise ValueError('candidate cannot be reviewed in this state')
        if decision == 'approved':
            _evidence(root,item)
            _current(item,_body(item),'before')
            _valid_evaluation(item)
        item.update(status=decision, review={'reviewer':reviewer,'at':time.time(),'content_hash':item['content_hash']})
        _save(item)
        return item


def _write(path, text):
    projects._safe_storage(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False, encoding='utf-8') as out:
            temporary = Path(out.name)
            os.chmod(temporary, path.stat().st_mode & 0o777)
            out.write(text)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()


def _change(root, identity, reverse, dry_run):
    with projects._locked():
        item = _load(root, identity)
        if Path(item['workspace']) != config.ROOT.resolve():
            raise ValueError('application is restricted to this platform checkout')
        expected, pending, final = ('applied','reverting','reverted') if reverse else ('approved','applying','applied')
        recovering = item['status'] == pending or (reverse and item['status'] == 'applying')
        if item['status'] != expected and not recovering:
            raise ValueError('candidate is not ready for this operation')
        body = _body(item)
        before, after = ('after','before') if reverse else ('before','after')
        if not reverse:
            _evidence(root,item)
            _valid_evaluation(item)
            if not item.get('review') or item['review']['content_hash'] != item['content_hash']:
                raise ValueError('current review required')
        # Pending journal supports explicit recovery after process failure without overwriting unrelated edits.
        for rel, versions in body['files'].items():
            path = Path(item['workspace']) / rel
            projects._safe_storage(path)
            current = path.read_text()
            allowed = (versions[before],versions[after]) if recovering else (versions[before],)
            if current not in allowed:
                raise ValueError('target changed; preserve user edits')
        if dry_run:
            diff = ''.join(''.join(difflib.unified_diff(v[before].splitlines(True), v[after].splitlines(True),
                          fromfile=p, tofile=p)) for p,v in body['files'].items())
            return show(root,identity) | {'diff':diff,'dry_run':True,'operation':'revert' if reverse else 'apply'}
        item['status']=pending
        _save(item)
        for rel,versions in body['files'].items():
            path=Path(item['workspace'])/rel
            if path.read_text() != versions[after]:
                if path.read_text() != versions[before]:
                    raise ValueError('concurrent file edit; operation pending for explicit recovery')
                _write(path,versions[after])
        item['status']=final
        item['changed_at']=time.time()
        _save(item)
        return item


def apply(root, identity, dry_run=False):
    return _change(root,identity,False,dry_run)


def revert(root, identity, dry_run=False):
    return _change(root,identity,True,dry_run)


def evaluation_input(root, identity, variant):
    item = _load(root,identity)
    _evidence(root,item)
    body = _body(item)
    _current(item,body,'before')
    if variant not in ('baseline','candidate'):
        raise ValueError('unknown evaluation variant')
    text = body['files'][item['target']]['before' if variant=='baseline' else 'after']
    return {'improvement_id':identity,'improvement_hash':item['content_hash'],'improvement_variant':variant,
            'instruction_content_hash':digest(text)}, text
