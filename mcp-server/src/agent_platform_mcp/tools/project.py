"""Project initialization tool: clone springboot-kotlin-skeleton and customize it."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from agent_platform_mcp.config import ROOT, set_active_project
from agent_platform_mcp.tools import log as log_tools

SKELETON_REPO = "https://github.com/moohee-lee/springboot-kotlin-skeleton.git"

PROJECT_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{1,63}$")
PACKAGE_PATH_RE = re.compile(r"^[a-z][a-z0-9]*(\.[a-z][a-z0-9]*)+$")

# Initializr ID → (gradle coordinate, scope)
DEPENDENCY_MAP: dict[str, tuple[str, str]] = {
    "web": ("org.springframework.boot:spring-boot-starter-web", "implementation"),
    "webflux": ("org.springframework.boot:spring-boot-starter-webflux", "implementation"),
    "r2dbc": ("org.springframework.boot:spring-boot-starter-data-r2dbc", "implementation"),
    "jpa": ("org.springframework.boot:spring-boot-starter-data-jpa", "implementation"),
    "security": ("org.springframework.boot:spring-boot-starter-security", "implementation"),
    "validation": ("org.springframework.boot:spring-boot-starter-validation", "implementation"),
    "actuator": ("org.springframework.boot:spring-boot-starter-actuator", "implementation"),
    "cache": ("org.springframework.boot:spring-boot-starter-cache", "implementation"),
    "redis": ("org.springframework.boot:spring-boot-starter-data-redis-reactive", "implementation"),
    "postgresql": ("org.postgresql:postgresql", "runtimeOnly"),
    "r2dbc-postgresql": ("org.postgresql:r2dbc-postgresql", "runtimeOnly"),
    "h2": ("com.h2database:h2", "runtimeOnly"),
    "flyway": ("org.flywaydb:flyway-core", "implementation"),
    "kafka": ("org.springframework.kafka:spring-kafka", "implementation"),
    "test": ("org.springframework.boot:spring-boot-starter-test", "testImplementation"),
    "mockk": ("io.mockk:mockk", "testImplementation"),
    "testcontainers": ("org.testcontainers:junit-jupiter", "testImplementation"),
}

DEFAULT_TEST_DEPS = [
    '    testImplementation("org.springframework.boot:spring-boot-starter-test")',
    '    testImplementation("io.mockk:mockk")',
]


# ---------------------------------------------------------------------------
# Phase 1: Input validation
# ---------------------------------------------------------------------------

def _validate_inputs(
    project_name: str,
    package_path: str,
    target_dir: Path,
) -> None:
    if not PROJECT_NAME_RE.match(project_name):
        raise ValueError(
            f"Invalid project_name '{project_name}'. "
            "Must match ^[a-z][a-z0-9-]{{1,63}}$."
        )
    if not PACKAGE_PATH_RE.match(package_path):
        raise ValueError(
            f"Invalid package_path '{package_path}'. "
            "Must match ^[a-z][a-z0-9]*(\\.[a-z][a-z0-9]*)+$."
        )
    dest = target_dir / project_name
    if dest.exists():
        raise FileExistsError(f"Target directory already exists: {dest}")


# ---------------------------------------------------------------------------
# Phase 2: Skeleton clone
# ---------------------------------------------------------------------------

def _clone_skeleton(target_dir: Path, project_name: str) -> Path:
    dest = target_dir / project_name
    subprocess.run(
        ["git", "clone", SKELETON_REPO, str(dest)],
        check=True,
        capture_output=True,
        text=True,
    )
    git_dir = dest / ".git"
    if git_dir.exists():
        shutil.rmtree(git_dir)
    return dest


# ---------------------------------------------------------------------------
# Phase 3: Auto-detect current values
# ---------------------------------------------------------------------------

def _detect_current_package(src_root: Path) -> str | None:
    """Scan src/main/kotlin/ to derive the base package from directory structure."""
    kotlin_main = src_root / "src" / "main" / "kotlin"
    if not kotlin_main.is_dir():
        return None
    # Walk until we find a directory that contains at least one .kt file
    for path in sorted(kotlin_main.rglob("*.kt")):
        content = path.read_text(encoding="utf-8", errors="ignore")
        m = re.search(r"^\s*package\s+([\w.]+)", content, re.MULTILINE)
        if m:
            pkg = m.group(1)
            # Return the shortest prefix that corresponds to an actual directory
            parts = pkg.split(".")
            for depth in range(len(parts), 0, -1):
                candidate = kotlin_main / Path(*parts[:depth])
                if candidate.is_dir():
                    return ".".join(parts[:depth])
    return None


def _detect_current_values(dest: Path) -> dict[str, str | None]:
    info: dict[str, str | None] = {
        "project_name": None,
        "package_path": None,
        "java_version": None,
        "kotlin_version": None,
        "spring_boot_version": None,
        "gradle_version": None,
    }

    settings = dest / "settings.gradle.kts"
    if settings.is_file():
        text = settings.read_text(encoding="utf-8")
        m = re.search(r'rootProject\.name\s*=\s*"([^"]+)"', text)
        if m:
            info["project_name"] = m.group(1)

    info["package_path"] = _detect_current_package(dest)

    build = dest / "build.gradle.kts"
    # Also check buildSrc for version definitions
    buildsrc_versions = dest / "buildSrc" / "src" / "main" / "kotlin" / "Versions.kt"

    for fpath in [build, buildsrc_versions]:
        if not fpath.is_file():
            continue
        text = fpath.read_text(encoding="utf-8")
        if not info["java_version"]:
            m = re.search(r"jvmToolchain\((\d+)\)", text)
            if m:
                info["java_version"] = m.group(1)
        if not info["kotlin_version"]:
            m = re.search(r'kotlin\("jvm"\)\s+version\s+"([^"]+)"', text)
            if not m:
                m = re.search(r'KOTLIN\s*=\s*"([^"]+)"', text)
            if m:
                info["kotlin_version"] = m.group(1)
        if not info["spring_boot_version"]:
            m = re.search(r'kotlin\("plugin\.spring"\)\s+version\s+"([^"]+)"', text)
            if not m:
                m = re.search(r'id\("org\.springframework\.boot"\)\s+version\s+"([^"]+)"', text)
            if not m:
                m = re.search(r'SPRING_BOOT\s*=\s*"([^"]+)"', text)
            if m:
                info["spring_boot_version"] = m.group(1)

    wrapper_props = dest / "gradle" / "wrapper" / "gradle-wrapper.properties"
    if wrapper_props.is_file():
        text = wrapper_props.read_text(encoding="utf-8")
        m = re.search(r"gradle-([\d.]+)-", text)
        if m:
            info["gradle_version"] = m.group(1)

    return info


# ---------------------------------------------------------------------------
# Phase 4: Version replacement
# ---------------------------------------------------------------------------

def _replace_version_in_file(path: Path, pattern: str, replacement: str) -> bool:
    if not path.is_file():
        return False
    original = path.read_text(encoding="utf-8")
    updated = re.sub(pattern, replacement, original)
    if updated != original:
        path.write_text(updated, encoding="utf-8")
        return True
    return False


def _apply_versions(
    dest: Path,
    java_version: int | None,
    kotlin_version: str | None,
    spring_boot_version: str | None,
    gradle_version: str | None,
    current: dict[str, str | None],
) -> list[str]:
    changes: list[str] = []
    build = dest / "build.gradle.kts"
    buildsrc_versions = dest / "buildSrc" / "src" / "main" / "kotlin" / "Versions.kt"
    wrapper_props = dest / "gradle" / "wrapper" / "gradle-wrapper.properties"

    if java_version and current.get("java_version") != str(java_version):
        for fpath in [build, buildsrc_versions]:
            if _replace_version_in_file(
                fpath,
                r"jvmToolchain\(\d+\)",
                f"jvmToolchain({java_version})",
            ):
                changes.append(f"java_version → {java_version}")
                break

    if kotlin_version and current.get("kotlin_version") != kotlin_version:
        replaced = False
        for fpath in [build, buildsrc_versions]:
            if _replace_version_in_file(
                fpath,
                r'(kotlin\("jvm"\)\s+version\s+")[^"]+(")',
                rf'\g<1>{kotlin_version}\g<2>',
            ):
                replaced = True
            if _replace_version_in_file(
                fpath,
                r'(KOTLIN\s*=\s*")[^"]+(")',
                rf'\g<1>{kotlin_version}\g<2>',
            ):
                replaced = True
        if replaced:
            changes.append(f"kotlin_version → {kotlin_version}")

    if spring_boot_version and current.get("spring_boot_version") != spring_boot_version:
        replaced = False
        for fpath in [build, buildsrc_versions]:
            for pattern, repl in [
                (
                    r'(kotlin\("plugin\.spring"\)\s+version\s+")[^"]+(")',
                    rf'\g<1>{spring_boot_version}\g<2>',
                ),
                (
                    r'(id\("org\.springframework\.boot"\)\s+version\s+")[^"]+(")',
                    rf'\g<1>{spring_boot_version}\g<2>',
                ),
                (
                    r'(SPRING_BOOT\s*=\s*")[^"]+(")',
                    rf'\g<1>{spring_boot_version}\g<2>',
                ),
            ]:
                if _replace_version_in_file(fpath, pattern, repl):
                    replaced = True
        if replaced:
            changes.append(f"spring_boot_version → {spring_boot_version}")

    if gradle_version and current.get("gradle_version") != gradle_version:
        if _replace_version_in_file(
            wrapper_props,
            r"(distributionUrl=.*?gradle-)[\d.]+(-)",
            rf"\g<1>{gradle_version}\g<2>",
        ):
            changes.append(f"gradle_version → {gradle_version}")

    return changes


# ---------------------------------------------------------------------------
# Phase 5: Dependency replacement
# ---------------------------------------------------------------------------

def _build_dep_lines(dep_ids: list[str]) -> list[str]:
    lines: list[str] = []
    unknown: list[str] = []
    for dep_id in dep_ids:
        if dep_id not in DEPENDENCY_MAP:
            unknown.append(dep_id)
            continue
        coord, scope = DEPENDENCY_MAP[dep_id]
        lines.append(f'    {scope}("{coord}")')
    if unknown:
        raise ValueError(f"Unknown dependency IDs: {unknown}. Allowed: {sorted(DEPENDENCY_MAP)}")
    # Always include base test dependencies if not explicitly specified
    test_ids = {"test", "mockk"}
    for tid in test_ids:
        coord, scope = DEPENDENCY_MAP[tid]
        line = f'    {scope}("{coord}")'
        if line not in lines:
            lines.append(line)
    return lines


def _apply_dependencies(dest: Path, dep_ids: list[str]) -> bool:
    build = dest / "build.gradle.kts"
    if not build.is_file():
        return False

    dep_lines = _build_dep_lines(dep_ids)
    deps_block = "dependencies {\n" + "\n".join(dep_lines) + "\n}"

    original = build.read_text(encoding="utf-8")
    updated = re.sub(
        r"dependencies\s*\{[^}]*\}",
        deps_block,
        original,
        flags=re.DOTALL,
    )
    if updated != original:
        build.write_text(updated, encoding="utf-8")
        return True
    return False


# ---------------------------------------------------------------------------
# Phase 6: Package & project name replacement
# ---------------------------------------------------------------------------

def _pkg_to_path(package: str) -> str:
    """Convert package string to filesystem path segments."""
    return package.replace(".", "/")


def _replace_in_file(path: Path, old: str, new: str) -> bool:
    try:
        original = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, PermissionError):
        return False
    if old not in original:
        return False
    path.write_text(original.replace(old, new), encoding="utf-8")
    return True


def _rename_package_dirs(kotlin_root: Path, old_pkg: str, new_pkg: str) -> None:
    old_rel = Path(_pkg_to_path(old_pkg))
    new_rel = Path(_pkg_to_path(new_pkg))
    old_dir = kotlin_root / old_rel
    new_dir = kotlin_root / new_rel

    if not old_dir.is_dir():
        return
    if old_dir.resolve() == new_dir.resolve():
        return

    new_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(str(old_dir), str(new_dir), dirs_exist_ok=True)

    # Find the highest old directory that can safely be removed without
    # touching the new location. Walk from the full old path upward,
    # stopping at the first segment that diverges from the new package.
    #
    # Example: com.example.skeleton → com.ktcloud.kcp.cm
    #   common prefix = ["com"]  (depth=1)
    #   prune_dir     = kotlin_root / "com" / "example"   ← safe to delete
    #
    # Example: org.foo.bar → com.example.baz
    #   common prefix = []  (depth=0)
    #   prune_dir     = kotlin_root / "org"               ← safe to delete
    old_parts = old_pkg.split(".")
    new_parts = new_pkg.split(".")

    common_depth = 0
    for o, n in zip(old_parts, new_parts):
        if o == n:
            common_depth += 1
        else:
            break

    # Prune at the first diverging segment of the old package path
    prune_parts = old_parts[: common_depth + 1]
    prune_dir = kotlin_root / Path(*prune_parts)
    if prune_dir.is_dir() and not new_dir.is_relative_to(prune_dir):
        shutil.rmtree(prune_dir)


def _apply_package_rename(
    dest: Path,
    old_project_name: str,
    new_project_name: str,
    old_package: str,
    new_package: str,
) -> list[str]:
    changes: list[str] = []
    old_pkg_path = _pkg_to_path(old_package)
    new_pkg_path = _pkg_to_path(new_package)

    # Update settings.gradle.kts rootProject.name
    settings = dest / "settings.gradle.kts"
    if _replace_in_file(settings, f'"{old_project_name}"', f'"{new_project_name}"'):
        changes.append(f"settings.gradle.kts: rootProject.name → {new_project_name}")

    # Rename package directories
    for subdir in ("src/main/kotlin", "src/test/kotlin"):
        kotlin_root = dest / subdir
        if kotlin_root.is_dir():
            _rename_package_dirs(kotlin_root, old_package, new_package)

    # Text replacement in all relevant files
    text_targets = list(dest.rglob("*.kt")) + list(dest.rglob("*.kts"))
    text_targets += list((dest / "src").rglob("*.yml")) if (dest / "src").is_dir() else []
    text_targets += list((dest / "src").rglob("*.yaml")) if (dest / "src").is_dir() else []
    text_targets += list((dest / "src").rglob("*.properties")) if (dest / "src").is_dir() else []

    replaced_files: set[str] = set()
    for fpath in text_targets:
        changed = False
        if _replace_in_file(fpath, old_package, new_package):
            changed = True
        if old_pkg_path != new_pkg_path:
            if _replace_in_file(fpath, old_pkg_path, new_pkg_path):
                changed = True
        if old_project_name != new_project_name:
            if _replace_in_file(fpath, old_project_name, new_project_name):
                changed = True
        if changed:
            replaced_files.add(fpath.name)

    if replaced_files:
        changes.append(f"package/name replaced in {len(replaced_files)} files")

    return changes


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def init(
    project_name: str,
    package_path: str,
    java_version: int | None = None,
    kotlin_version: str | None = None,
    spring_boot_version: str | None = None,
    gradle_version: str | None = None,
    dependencies: list[str] | None = None,
    target_dir: str | None = None,
) -> dict[str, Any]:
    """Clone springboot-kotlin-skeleton and apply project-specific settings."""
    # target_dir should always be passed explicitly by the slash command (pwd-derived).
    # Fallback to ROOT.parent is a last resort for direct MCP tool calls.
    resolved_target = Path(target_dir).expanduser().resolve() if target_dir else ROOT.parent

    # Phase 1
    _validate_inputs(project_name, package_path, resolved_target)

    # Phase 2
    dest = _clone_skeleton(resolved_target, project_name)

    # Phase 3
    current = _detect_current_values(dest)
    old_project_name = current.get("project_name") or "springboot-kotlin-skeleton"
    old_package = current.get("package_path") or "com.example"

    all_changes: list[str] = []

    # Phase 4
    version_changes = _apply_versions(
        dest, java_version, kotlin_version, spring_boot_version, gradle_version, current
    )
    all_changes.extend(version_changes)

    # Phase 5
    if dependencies:
        if _apply_dependencies(dest, dependencies):
            all_changes.append(f"dependencies replaced: {dependencies}")

    # Phase 6
    pkg_changes = _apply_package_rename(
        dest, old_project_name, project_name, old_package, package_path
    )
    all_changes.extend(pkg_changes)

    # Phase 7: persist active project so feature/log tools resolve to target project
    set_active_project(dest)

    summary = (
        f"project_init: created {project_name} at {dest} "
        f"(package={package_path}, changes={all_changes})"
    )
    log_tools.append(summary, agent="backend", feature=project_name)

    return {
        "project_name": project_name,
        "package_path": package_path,
        "destination": str(dest),
        "detected": current,
        "changes": all_changes,
        "status": "success",
    }
