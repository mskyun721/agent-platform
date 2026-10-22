"""Backend contract: each adapter module exposes these names (module-as-adapter)."""
from pathlib import Path
from typing import Protocol

from agent_platform_mcp.events import Usage

UNAVAILABLE = Usage(None, None, None, None, "unavailable", "unavailable")


class Backend(Protocol):
    name: str
    host_files: tuple[str, ...]
    observed: bool  # native transcript collection implemented

    def command(self, prompt: str, workdir: Path, *, model: str | None, read_only: bool) -> list[str]: ...
    def parse(self, stdout: str) -> tuple[str, Usage, bool]: ...
