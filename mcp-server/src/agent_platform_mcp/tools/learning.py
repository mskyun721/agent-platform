"""Compatibility shim; implementation lives in agent_platform_mcp.learning.feedback."""
import sys
from agent_platform_mcp.learning import feedback as _impl

sys.modules[__name__] = _impl
