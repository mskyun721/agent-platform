"""Bounded usage summaries, without inferred savings or cross-source totals."""
from collections import Counter, defaultdict

FIELDS = ('input_tokens', 'output_tokens', 'cache_read_tokens', 'cache_write_tokens')
GROUP = ('workspace', 'backend', 'model', 'collection_source')


def _count(row, field):
    value = (row.get('usage') or {}).get(field)
    return value if type(value) is int and value >= 0 else None


def summarize(runs, *, total, limit, workspace=None):
    selected = [row for row in runs if workspace is None or row.get('workspace') == workspace]
    groups = defaultdict(list)
    for row in selected:
        groups[tuple(row.get(key) for key in GROUP)].append(row)
    result = []
    for key, rows in groups.items():
        tokens = {}
        for field in FIELDS:
            counts = [_count(row, field) for row in rows]
            known = [value for value in counts if value is not None]
            tokens[field] = {'known_sum': sum(known) if known else None,
                             'missing_records': len(rows) - len(known)}
        outcomes = Counter(row.get('outcome') or 'unknown' for row in rows)
        result.append(dict(zip(GROUP, key)) | {'records': len(rows), 'tokens': tokens,
                      'outcomes': dict(outcomes), 'failed_or_interrupted': sum(outcomes[k] for k in ('failed','interrupted','cancelled'))})
    # Rank within comparable groups; Claude/Codex input fields have different cache semantics.
    ranked = [row for rows in groups.values() for row in sorted(
        (r for r in rows if _count(r,'input_tokens') is not None),
        key=lambda r: _count(r,'input_tokens'), reverse=True)[:5]]
    top = [{key: row.get(key) for key in ('run_id', *GROUP)} |
           {'input_tokens': _count(row,'input_tokens')} for row in ranked]
    return {'groups': result, 'top_input_runs': top, 'sample_records': len(selected),
            'global_available_records': total, 'global_sample_limit': limit,
            'truncated': total > len(runs), 'workspace': workspace, 'savings_percent': None,
            'scope': 'Selected workspace within the latest global sample, not lifetime or complete task totals.',
            'limitations': ['Native and wrapper records may overlap; sources are not added together.',
                           'Backend input/cache token definitions differ; no cross-backend total or inferred cache hit rate.',
                           'Completed execution is not approval. Retries and accepted task cost require explicit task linkage.',
                           'Known sums exclude missing measurements. No measured savings baseline is available.']}


def report(root):
    from agent_platform_mcp.tools import learning, llm_view
    workspace = str(learning.context(root).path)
    sample = llm_view.list_runs(500)
    return summarize(sample['runs'], total=sample['total'], limit=sample['limit'], workspace=workspace)
