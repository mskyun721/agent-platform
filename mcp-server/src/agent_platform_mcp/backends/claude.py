"""Claude Code print mode; bounded tools without permission bypass."""
from agent_platform_mcp.tools import native_output

name = "claude"
host_files = ("CLAUDE.md", ".claude/agents", ".mcp.json")
observed = True


def command(prompt, workdir, *, model, read_only):
    toolset = "Read,Glob,Grep,WebSearch,WebFetch" if read_only else "Read,Glob,Grep,Edit,Write,Bash"
    allowed = toolset if read_only else "Read,Glob,Grep,Edit,Write"
    cmd = ["claude", "-p", "--output-format", "json", "--strict-mcp-config",
           "--permission-mode", "dontAsk", "--tools", toolset, "--allowedTools", allowed]
    if model:
        cmd += ["--model", model]
    return cmd + ["--", prompt]


def parse(stdout):
    return native_output.claude(stdout)
