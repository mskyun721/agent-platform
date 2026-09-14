"""Evaluator-owned real skill lifecycle; local registries and products are isolated."""

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch


def check(workspace: Path) -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "mcp-server/src"))
    from agent_platform_mcp.tools import projects, skill_packages as packages, skills
    namespace = {}
    path = workspace / "exercise_skill.py"
    exec(compile(path.read_text(), str(path), "exec"), namespace)
    with tempfile.TemporaryDirectory(prefix="skill-judge-") as temp:
        root = Path(temp).resolve()
        project, source = root / "project", root / "source"
        project.mkdir()
        source.mkdir()
        product = project / "product.py"
        product.write_text("unchanged product\n")
        (source / "SKILL.md").write_text("---\nname: judge-probe\ndescription: Isolated lifecycle check\n---\nDo nothing.\n")
        (source / "skill.json").write_text(json.dumps({"id": "judge-probe", "version": "1", "supports": ["claude", "codex"]}))
        with patch.object(projects, "REGISTRY_FILE", root / ".agent-projects.json"), \
             patch.object(packages, "PACKAGES", root / "packages"), patch.object(packages, "REGISTRY", root / "registry.json"), \
             patch.dict(os.environ, {"AGENT_PLATFORM_ALLOWED_PROJECT_ROOTS": str(root)}):
            projects.register(str(project), "judge-project")
            packages.add(str(source))
            skills.enable("judge-probe", "judge-project")
            calls = []
            def enable():
                calls.append("enable")
                return skills.enable("judge-probe", "judge-project")
            def disable():
                calls.append("disable")
                return skills.disable("judge-probe", "judge-project")
            def remove():
                calls.append("remove")
                return packages.remove("judge-probe")
            result = namespace["exercise"](enable, disable, remove)
            assert result == {"blocked_while_enabled": True, "removed": True}, "lifecycle result"
            assert calls == ["remove", "disable", "remove"], "lifecycle calls"
            assert product.read_text() == "unchanged product\n", "product must be preserved"
            assert packages.list_skills()["packages"] == [], "package must be removed"
            assert not (project / ".agents/skills/judge-probe").exists(), "Codex copy removed"
            assert not (project / ".claude/skills/judge-probe").exists(), "Claude copy removed"
