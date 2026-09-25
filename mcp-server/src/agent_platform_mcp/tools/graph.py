"""Read-only graph diagnostics and file-level impact candidates, never gate evidence."""

from collections import defaultdict, deque
import hashlib
import json
from pathlib import Path, PurePosixPath
import re

from agent_platform_mcp.config import resolve_project
from agent_platform_mcp.tools.feature import _safe_path
from agent_platform_mcp.tools.fingerprint import excluded

MAX_BYTES = 32 * 1024 * 1024
RELATIONS = {'calls', 'imports', 'imports_from', 'references', 'uses'}


def _path(value: str, root: Path) -> str:
    if not isinstance(value, str) or not value or '\\' in value or any(ord(c) < 32 for c in value):
        raise ValueError('invalid graph source path')
    path = PurePosixPath(value)
    if path.is_absolute() or '..' in path.parts or ':' in value or path.as_posix() != value:
        raise ValueError('graph paths must be normalized project-relative paths')
    if excluded(value) or any(p in {'PROMPT', 'graphify-out'} for p in path.parts):
        raise ValueError('protected or local-work graph path')
    _safe_path(root / value, root)
    return value


def _load(root: str | Path | None):
    context = resolve_project(root)
    project = context.path
    path = project / 'graphify-out/graph.json'
    _safe_path(path, project)
    if not path.exists():
        return project, None
    if not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise ValueError('graph must be a regular JSON file at most 32 MiB')
    with path.open('rb') as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError('graph exceeds 32 MiB')
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ValueError('invalid graph JSON') from exc
    if isinstance(data, dict):
        if 'edges' in data and 'links' in data and data['edges'] != data['links']:
            raise ValueError('ambiguous graph edge arrays')
        if 'edges' not in data and 'links' in data:
            data['edges'] = data['links']
        if 'directed' in data and type(data['directed']) is not bool:
            raise ValueError('graph directed flag must be boolean')
    if not isinstance(data, dict) or not isinstance(data.get('nodes'), list) or not isinstance(data.get('edges'), list):
        raise ValueError('graph requires nodes and edges arrays')
    if len(data['nodes']) > 100_000 or len(data['edges']) > 500_000:
        raise ValueError('graph exceeds node or edge limit')
    for node in data['nodes']:
        if not isinstance(node, dict) or not isinstance(node.get('id'), str) or not node['id']:
            raise ValueError('graph node requires a string id')
        source = node.get('source_file')
        if source:
            _path(source, project)
        elif source not in (None, ''):
            raise ValueError('invalid graph source path')
    for edge in data['edges']:
        if not isinstance(edge, dict) or any(not isinstance(edge.get(k), str) or not edge[k] for k in ('source', 'target')):
            raise ValueError('graph edge requires string endpoints')
        for key in ('relation', 'confidence'):
            if key in edge and not isinstance(edge[key], str):
                raise ValueError('invalid graph edge metadata')
    return project, data


def _freshness(data, project, sources):
    snapshot = data.get('snapshot')
    if snapshot is None:
        return 'unknown'
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get('source_hashes'), dict):
        raise ValueError('snapshot requires source_hashes')
    hashes = snapshot['source_hashes']
    if len(hashes) > 10_000:
        raise ValueError('snapshot exceeds source limit')
    remaining = 128 * 1024 * 1024
    stale = False
    for source, expected in hashes.items():
        _path(source, project)
        if not isinstance(expected, str) or not re.fullmatch('[0-9a-f]{64}', expected):
            raise ValueError('snapshot source hash must be SHA256')
        path = project / source
        if not path.exists():
            stale = True
            continue
        if not path.is_file() or path.stat().st_size > min(remaining, MAX_BYTES):
            raise ValueError('snapshot source exceeds read budget or is not a regular file')
        with path.open('rb') as stream:
            content = stream.read(min(remaining, MAX_BYTES) + 1)
        remaining -= len(content)
        if remaining < 0 or len(content) > MAX_BYTES:
            raise ValueError('snapshot exceeds read budget')
        stale |= hashlib.sha256(content).hexdigest() != expected
    if stale:
        return 'stale'
    if sources and sources <= hashes.keys() and data.get('source_root') == str(project):
        return 'current'
    return 'unknown'


def _report(project, data):
    result = {'project_dir': str(project), 'mode': 'advisory', 'status': 'missing',
              'integrity': 'unknown', 'freshness': 'unknown', 'counts': {},
              'warnings': ['Impact candidates do not prove completeness, test success, or approval.']}
    if data is None:
        return result
    if data.get('directed') is False:
        result['warnings'].append('Graph has no direction; impact uses conservative undirected neighbors.')
    elif 'directed' not in data:
        result['warnings'].append('Legacy graph direction is unspecified; dependency relations use source-to-target convention.')
    nodes, edges = data['nodes'], data['edges']
    ids = {n['id'] for n in nodes}
    sources = {n['source_file'] for n in nodes if n.get('source_file')}
    counts = {'nodes': len(nodes), 'edges': len(edges), 'source_files': len(sources),
              'duplicate_ids': len(nodes) - len(ids),
              'dangling_edges': sum(e['source'] not in ids or e['target'] not in ids for e in edges),
              'missing_sources': sum(not (project / s).is_file() for s in sources),
              'nodes_without_source': sum(not n.get('source_file') for n in nodes)}
    foreign = data.get('source_root') not in (None, str(project))
    integrity = 'degraded' if foreign or any(counts[k] for k in ('duplicate_ids', 'dangling_edges', 'missing_sources')) else 'valid'
    freshness = _freshness(data, project, sources) if not foreign else 'unknown'
    result.update(status='ready' if integrity == 'valid' and freshness == 'current' else 'degraded',
                  integrity=integrity, freshness=freshness, counts=counts)
    if foreign:
        result['warnings'].append('Graph belongs to a different source_root; impact traversal disabled.')
    if counts['duplicate_ids']:
        result['warnings'].append('Duplicate node IDs are ambiguous; impact traversal disabled.')
    if counts['dangling_edges'] or counts['nodes_without_source']:
        result['warnings'].append('Unresolved graph endpoints or source-less nodes limit impact coverage.')
    if freshness != 'current':
        result['warnings'].append('Graph freshness is not current; rebuild with source hashes for the intended scope.')
    if not any(_is_test(s) for s in sources):
        result['warnings'].append('No test source files are indexed; test candidates may be missing.')
    return result


def _is_test(path):
    p = PurePosixPath(path)
    return bool({'test', 'tests', '__tests__'} & set(p.parts)) or p.name.startswith('test_') or p.name.endswith(('.test.ts', '.spec.ts', 'Test.java', 'Test.kt'))


def status(root: str | Path | None = None) -> dict:
    project, data = _load(root)
    return _report(project, data)


def impact(paths: list[str], root: str | Path | None = None, depth: int = 3, limit: int = 100) -> dict:
    if type(depth) is not int or not 1 <= depth <= 10 or type(limit) is not int or not 1 <= limit <= 500:
        raise ValueError('depth must be 1..10 and limit 1..500')
    if not isinstance(paths, list) or not 1 <= len(paths) <= 100:
        raise ValueError('provide 1..100 changed paths')
    project, data = _load(root)
    changed = sorted({_path(p, project) for p in paths})
    result = {**_report(project, data), 'changed_paths': changed, 'affected': [],
              'test_candidates': [], 'unmapped_paths': changed, 'truncated': False,
              'traversal': 'undirected-neighbors' if data and data.get('directed') is False else 'reverse-dependencies'}
    if data is None or result['counts']['duplicate_ids'] or data.get('source_root') not in (None, str(project)):
        return result
    nodes = {n['id']: n.get('source_file') for n in data['nodes']}
    sources = set(nodes.values()) - {None, ''}
    result['unmapped_paths'] = sorted(set(changed) - sources)
    reverse = defaultdict(list)
    for edge in data['edges']:
        caller, callee = nodes.get(edge['source']), nodes.get(edge['target'])
        if caller and callee and caller != callee and edge.get('relation') in RELATIONS:
            confidence = edge.get('confidence', 'UNKNOWN')
            confidence = confidence if confidence in {'EXTRACTED', 'INFERRED', 'AMBIGUOUS'} else 'UNKNOWN'
            reverse[callee].append((caller, edge['relation'], confidence))
            if data.get('directed') is False:
                reverse[caller].append((callee, edge['relation'], confidence))
    visited = set(changed)
    queue = deque((p, 0) for p in changed)
    while queue:
        current, distance = queue.popleft()
        for caller, relation, confidence in sorted(reverse[current]):
            if caller in visited:
                continue
            if distance >= depth or len(result['affected']) >= limit:
                result['truncated'] = True
                continue
            visited.add(caller)
            result['affected'].append({'path': caller, 'distance': distance + 1,
                                       'via': current, 'relation': relation, 'confidence': confidence})
            queue.append((caller, distance + 1))
    result['test_candidates'] = sorted(p for p in visited if _is_test(p))
    return result
