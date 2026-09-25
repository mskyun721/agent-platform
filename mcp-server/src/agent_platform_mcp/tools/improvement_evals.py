"""Strict comparison of local evaluator records; not an authenticity boundary."""
import hashlib
import json
from collections import Counter
from uuid import UUID
from agent_platform_mcp import config
from agent_platform_mcp.tools import projects

FIELDS = ('task', 'ai', 'task_hash', 'model', 'cli_version', 'instruction_mode',
          'python', 'platform_fingerprint', 'evaluation_budget_sec')


def records(ids):
    if not ids or len(ids) > 100 or len(set(ids)) != len(ids):
        raise ValueError('provide 1..100 distinct evaluation run ids')
    result, hashes = [], {}
    for value in ids:
        identity = str(UUID(value))
        if identity != value:
            raise ValueError('canonical run UUID required')
        path = config.ROOT / 'evals/results' / (identity + '.json')
        projects._safe_storage(path)
        if path.stat().st_size > 1024 * 1024:
            raise ValueError('evaluation record too large')
        raw = path.read_bytes()
        row = json.loads(raw)
        if row.get('run_id') != identity or row.get('status') != 'checked' or type(row.get('passed')) is not bool:
            raise ValueError('evaluation is not a checked result')
        if any(row.get(key) is None or row[key] == '' for key in FIELDS):
            raise ValueError('evaluation conditions are unknown')
        if row['ai'] not in ('claude', 'codex'):
            raise ValueError('unsupported evaluation backend')
        if row.get('verification_exit_code') != 0 and row['passed']:
            raise ValueError('success contradicts verification exit code')
        if type(row.get('human_interventions')) is not int or row['human_interventions'] < 0:
            raise ValueError('human intervention count missing')
        hashes[identity] = hashlib.sha256(raw).hexdigest()
        result.append(row)
    return result, hashes


def compare(item, baseline_ids, candidate_ids):
    if set(baseline_ids) & set(candidate_ids):
        raise ValueError('baseline and candidate runs must be independent')
    baseline, old_hashes = records(baseline_ids)
    candidate, new_hashes = records(candidate_ids)
    keys = lambda rows: Counter(tuple(r[k] for k in FIELDS) for r in rows)
    if keys(baseline) != keys(candidate):
        raise ValueError('incomparable evaluation conditions')
    for rows, variant, digest in ((baseline, 'baseline', item['target_hash']),
                                  (candidate, 'candidate', item['replacement_hash'])):
        for row in rows:
            if (row.get('improvement_id'), row.get('improvement_hash'), row.get('improvement_variant'),
                    row.get('instruction_content_hash')) != (item['id'], item['content_hash'], variant, digest):
                raise ValueError('evaluation is not bound to this candidate and instruction content')
        if any(n < 3 for n in keys(rows).values()) or {r['ai'] for r in rows} != {'claude', 'codex'}:
            raise ValueError('both backends require at least three trials per comparison case')
    passed = all(r['passed'] and r['human_interventions'] == 0 for r in candidate)
    metrics = {}
    for name, rows in (('baseline', baseline), ('candidate', candidate)):
        metrics[name] = {'runs': len(rows), 'passed': sum(r['passed'] for r in rows),
                         'human_interventions': sum(r['human_interventions'] for r in rows),
                         'duration_sec': [r.get('ai_duration_sec') for r in rows],
                         'usage': [r.get('usage') for r in rows]}
    return {'passed': passed, 'baseline_ids': baseline_ids, 'candidate_ids': candidate_ids,
            'record_hashes': old_hashes | new_hashes, 'metrics': metrics,
            'limitation': 'Local records can be edited by local processes. Three trials are smoke evidence, not statistical superiority.'}
