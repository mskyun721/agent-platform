"""Compatibility shim; implementation lives in agent_platform_mcp.learning.evals."""
import sys
from agent_platform_mcp.learning import evals as _impl

sys.modules[__name__] = _impl
