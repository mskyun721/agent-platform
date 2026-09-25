import asyncio
import hashlib
import json
from pathlib import Path

import pytest

from agent_platform_mcp import cli, server
from agent_platform_mcp.tools import graph


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    from agent_platform_mcp.tools import projects
    monkeypatch.setenv('AGENT_PLATFORM_ALLOWED_PROJECT_ROOTS', str(tmp_path))
    monkeypatch.setattr(projects, 'REGISTRY_FILE', tmp_path / 'registry.json')
    root = tmp_path / 'repo'
    root.mkdir()
    for name in ('lib.py', 'app.py', 'tests/test_app.py'):
        p = root / name
        p.parent.mkdir(exist_ok=True)
        p.write_text('value = 1\n')
    return root


def save(root, **overrides):
    data = {
        'source_root': str(root),
        'nodes': [{'id': n, 'source_file': p} for n, p in
                  [('lib', 'lib.py'), ('app', 'app.py'), ('test', 'tests/test_app.py')]],
        'edges': [
            {'source': 'app', 'target': 'lib', 'relation': 'calls', 'confidence': 'EXTRACTED'},
            {'source': 'test', 'target': 'app', 'relation': 'imports', 'confidence': 'INFERRED'},
        ],
    }
    data.update(overrides)
    folder = root / 'graphify-out'
    folder.mkdir(exist_ok=True)
    (folder / 'graph.json').write_text(json.dumps(data))
    return data


def test_health_and_missing(workspace):
    assert graph.status(str(workspace))['status'] == 'missing'
    save(workspace)
    r = graph.status(str(workspace))
    assert r['integrity'] == 'valid'
    assert r['freshness'] == 'unknown'
    assert r['mode'] == 'advisory'
    assert r['counts']['nodes'] == 3


def test_integrity_dangling_duplicate_and_missing_source(workspace):
    d = save(workspace)
    d['nodes'] += [{'id': 'lib', 'source_file': 'gone.py'}]
    d['edges'] += [{'source': 'absent', 'target': 'lib', 'relation': 'calls'}]
    save(workspace, **d)
    r = graph.status(str(workspace))
    assert r['integrity'] == 'degraded'
    assert r['counts']['duplicate_ids'] == 1
    assert r['counts']['dangling_edges'] == 1
    assert r['counts']['missing_sources'] == 1
    assert graph.impact(['lib.py'], str(workspace))['affected'] == []


def test_snapshot_hash_and_missing_coverage(workspace):
    hashes = {p: hashlib.sha256((workspace / p).read_bytes()).hexdigest()
              for p in ['lib.py', 'app.py', 'tests/test_app.py']}
    save(workspace, snapshot={'source_hashes': hashes})
    assert graph.status(str(workspace))['freshness'] == 'current'
    (workspace / 'lib.py').write_text('changed\n')
    assert graph.status(str(workspace))['freshness'] == 'stale'
    save(workspace, snapshot={'source_hashes': {}})
    assert graph.status(str(workspace))['freshness'] == 'unknown'


def test_reverse_dependencies_and_explanations(workspace):
    save(workspace)
    r = graph.impact(['lib.py'], str(workspace))
    assert [x['path'] for x in r['affected']] == ['app.py', 'tests/test_app.py']
    assert r['affected'][0]['via'] == 'lib.py'
    assert r['affected'][1]['confidence'] == 'INFERRED'
    assert r['test_candidates'] == ['tests/test_app.py']
    assert r['truncated'] is False
    assert graph.impact(['tests/test_app.py'], str(workspace))['affected'] == []
    assert graph.impact(['new.py'], str(workspace))['unmapped_paths'] == ['new.py']


def test_cycle_limits_and_ignored_semantic_edges(workspace):
    d = save(workspace)
    d['edges'].append({'source': 'lib', 'target': 'test', 'relation': 'calls'})
    save(workspace, **d)
    assert len(graph.impact(['lib.py'], str(workspace))['affected']) == 2
    assert graph.impact(['lib.py'], str(workspace), depth=1)['truncated']
    assert graph.impact(['lib.py'], str(workspace), limit=1)['truncated']
    d['edges'][0]['relation'] = 'rationale_for'
    save(workspace, **d)
    assert graph.impact(['lib.py'], str(workspace))['affected'] == []


@pytest.mark.parametrize('path', ['../outside.py', '/tmp/outside.py', '.env', 'docs/private.md',
                                 'PROMPT/task.md', '.local/state.db', 'a\\b.py'])
def test_reject_unsafe_inputs(workspace, path):
    save(workspace)
    with pytest.raises(ValueError):
        graph.impact([path], str(workspace))


def test_graph_and_source_symlinks_rejected(workspace):
    save(workspace)
    p = workspace / 'graphify-out/graph.json'
    p.rename(p.with_suffix('.original'))
    p.symlink_to(p.with_suffix('.original'))
    with pytest.raises(ValueError):
        graph.status(str(workspace))
    p.unlink()
    save(workspace)
    (workspace / 'lib.py').unlink()
    (workspace / 'lib.py').symlink_to(workspace / 'app.py')
    with pytest.raises(ValueError):
        graph.status(str(workspace))


@pytest.mark.parametrize('data', [{'nodes': {}, 'edges': []}, {'nodes': [1], 'edges': []},
                                {'nodes': [], 'edges': [{'source': [], 'target': 'a'}]}])
def test_invalid_schema(workspace, data):
    save(workspace, **data)
    with pytest.raises(ValueError):
        graph.status(str(workspace))


def test_source_protection_and_foreign_root(workspace):
    save(workspace, nodes=[{'id': 'x', 'source_file': 'docs/private.md'}])
    with pytest.raises(ValueError):
        graph.status(str(workspace))
    save(workspace, source_root=str(workspace.parent))
    r = graph.impact(['lib.py'], str(workspace))
    assert r['status'] == 'degraded'
    assert r['affected'] == []


@pytest.mark.parametrize('kwargs', [{'depth': 0}, {'depth': 11}, {'limit': 0}, {'limit': True}])
def test_invalid_bounds(workspace, kwargs):
    save(workspace)
    with pytest.raises(ValueError):
        graph.impact(['lib.py'], str(workspace), **kwargs)


def test_cli_mcp_readonly_and_allowlist(workspace, capsys):
    save(workspace)
    before = {str(p): p.read_bytes() for p in workspace.rglob('*') if p.is_file()}
    assert cli.main(['graph', 'impact', 'lib.py', '--root', str(workspace)]) == 0
    assert json.loads(capsys.readouterr().out)['test_candidates'] == ['tests/test_app.py']
    assert server.graph_status(str(workspace))['integrity'] == 'valid'
    assert server.graph_impact(['lib.py'], str(workspace))['affected']
    names = {t.name for t in asyncio.run(server.mcp.list_tools())}
    assert {'graph_status', 'graph_impact'} <= names
    assert before == {str(p): p.read_bytes() for p in workspace.rglob('*') if p.is_file()}
    with pytest.raises((RuntimeError, ValueError)):
        graph.status('/')


def test_graphify_node_link_format(workspace):
    data = save(workspace)
    edges = data.pop('edges')
    data.update(links=edges, directed=True, graph={})
    (workspace / 'graphify-out/graph.json').write_text(json.dumps(data))
    assert graph.status(str(workspace))['counts']['edges'] == 2
    assert graph.impact(['lib.py'], str(workspace))['test_candidates'] == ['tests/test_app.py']


def test_undirected_graph_uses_conservative_neighbors(workspace):
    save(workspace, directed=False)
    r = graph.impact(['tests/test_app.py'], str(workspace))
    assert {p['path'] for p in r['affected']} == {'app.py', 'lib.py'}
    assert r['traversal'] == 'undirected-neighbors'
    assert any('direction' in w for w in r['warnings'])


def test_deleted_source_still_maps_and_is_reported(workspace):
    save(workspace)
    (workspace / 'lib.py').unlink()
    r = graph.impact(['lib.py'], str(workspace))
    assert r['counts']['missing_sources'] == 1
    assert r['unmapped_paths'] == []
    assert r['affected'][0]['path'] == 'app.py'


def test_graph_read_size_limit(workspace, monkeypatch):
    save(workspace)
    monkeypatch.setattr(graph, 'MAX_BYTES', 10)
    with pytest.raises(ValueError, match='32 MiB'):
        graph.status(str(workspace))


def test_snapshot_protected_source_never_opened(workspace, monkeypatch):
    save(workspace, snapshot={'source_hashes': {'docs/private.md': '0' * 64}})
    original = Path.open
    def checked_open(path, *args, **kwargs):
        assert path.name != 'private.md', 'protected source must not be opened'
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', checked_open)
    with pytest.raises(ValueError, match='protected'):
        graph.status(str(workspace))


def test_missing_graph_still_validates_input(workspace):
    with pytest.raises(ValueError):
        graph.impact(['../outside.py'], str(workspace))


def test_conflicting_formats_rejected(workspace):
    save(workspace, links=[])
    with pytest.raises(ValueError, match='ambiguous'):
        graph.status(str(workspace))
