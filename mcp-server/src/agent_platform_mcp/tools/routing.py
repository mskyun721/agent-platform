"""Deterministic explicit/role routing; no inference, retries or backend fallback."""
import hashlib
import json
import re
from agent_platform_mcp import config
from agent_platform_mcp.tools import projects

BACKENDS = {'claude', 'codex'}


def configuration():
    path = config.ROOT / '.agent-config.json'
    projects._safe_storage(path)
    if not path.exists():
        return {}
    if path.stat().st_size > 1024 * 1024:
        raise ValueError('routing configuration too large')
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError('agent configuration must be an object')
    return data


def _model(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/+@-]{0,127}',value):
        raise ValueError('invalid model identifier')
    return value


def _models(value):
    if not isinstance(value, dict) or set(value)-BACKENDS:
        raise ValueError('models must map supported backends to model identifiers')
    for model in value.values():
        _model(model)
    return value


def _roles(value):
    if not isinstance(value, dict) or set(value)-config.VALID_AGENTS:
        raise ValueError('unknown routing role')
    for route in value.values():
        if not isinstance(route,dict) or set(route)-{'cli','models'}:
            raise ValueError('role route supports cli and models only')
        if 'cli' in route and route['cli'] not in BACKENDS:
            raise ValueError('invalid role backend')
        _models(route.get('models',{}))
    return value


def resolve(role, context, cli='auto', model=None):
    if role not in config.VALID_AGENTS or cli not in BACKENDS | {'auto'}:
        raise ValueError('invalid role or backend')
    cfg = configuration()
    policy = cfg.get('routing', {})
    if not isinstance(policy,dict) or set(policy)-{'roles','projects','allowed_cli','allowed_models'}:
        raise ValueError('invalid routing policy')
    allowed = policy.get('allowed_cli',sorted(BACKENDS))
    if not isinstance(allowed,list) or not allowed or any(not isinstance(c,str) or c not in BACKENDS for c in allowed):
        raise ValueError('allowed_cli must be a nonempty backend list')
    permitted = policy.get('allowed_models',{})
    if not isinstance(permitted,dict) or set(permitted)-BACKENDS:
        raise ValueError('invalid allowed_models')
    for values in permitted.values():
        if not isinstance(values,list) or not values:
            raise ValueError('allowed_models requires nonempty lists')
        for value in values:
            _model(value)
    roles = _roles(policy.get('roles',{}))
    scoped = policy.get('projects',{})
    if not isinstance(scoped,dict):
        raise ValueError('routing.projects must be an object')
    for routes in scoped.values():
        _roles(routes)
    project = scoped.get(context.project_id,scoped.get(str(context.path),{})).get(role,{})
    common = roles.get(role,{})
    backend_source, chosen = next((source,value) for source,value in (
        ('explicit',None if cli=='auto' else cli),('project_role',project.get('cli')),
        ('role',common.get('cli')),('preferred_cli',cfg.get('preferred_cli','codex'))) if value is not None)
    if chosen not in allowed:
        raise ValueError('selected backend is disallowed by routing policy')
    pins = _models(cfg.get('cli_models',{}))
    native = cfg.get('claude_models',{})
    if not isinstance(native,dict):
        raise ValueError('claude_models must be an object')
    model_source, selected = next((source,value) for source,value in (
        ('explicit',model),('project_role',project.get('models',{}).get(chosen)),
        ('role',common.get('models',{}).get(chosen)),('cli_models',pins.get(chosen)),
        ('claude_models',native.get(role) if chosen=='claude' else None),('cli_default',None))
        if value is not None or source=='cli_default')
    if selected is not None:
        _model(selected)
    if chosen in permitted and selected not in permitted[chosen]:
        raise ValueError('selected model is unspecified or disallowed by routing policy')
    return {'cli':chosen,'model':selected,'cli_source':backend_source,'model_source':model_source,
            'requested_cli':cli,'requested_model':model,'runtime_model_status':'unverified',
            'policy_hash':hashlib.sha256(json.dumps(cfg,sort_keys=True).encode()).hexdigest(),
            'fallback':'none'}


def validate_selection(value):
    keys = {'cli','model','cli_source','model_source','requested_cli','requested_model',
            'runtime_model_status','policy_hash','fallback'}
    if not isinstance(value,dict) or set(value)!=keys:
        raise ValueError('invalid selection metadata fields')
    if value['cli'] not in BACKENDS or value['requested_cli'] not in BACKENDS | {'auto'}:
        raise ValueError('invalid selection backend')
    if value['cli_source'] not in {'explicit','project_role','role','preferred_cli'} or value['model_source'] not in {
            'explicit','project_role','role','cli_models','claude_models','cli_default'}:
        raise ValueError('invalid selection source')
    for key in ('model','requested_model'):
        if value[key] is not None:
            _model(value[key])
    if value['runtime_model_status'] != 'unverified' or value['fallback'] != 'none':
        raise ValueError('unsupported selection status')
    if not isinstance(value['policy_hash'],str) or not re.fullmatch('[0-9a-f]{64}',value['policy_hash']):
        raise ValueError('invalid selection policy hash')
