"""Compatibility shim; implementation lives in agent_platform_mcp.learning.improvements."""
import sys
from agent_platform_mcp.learning import improvements as _impl

sys.modules[__name__] = _impl
