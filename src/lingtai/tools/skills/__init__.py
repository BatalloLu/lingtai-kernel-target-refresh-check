"""Skills capability — per-agent skill catalog (pure presentation).

Every agent has its own ``<agent>/.library/``:

- ``intrinsic/capabilities/<cap>/`` and ``intrinsic/addons/<addon>/`` — manual
  bundles installed by the Agent initializer (wipe-and-rewrite on every
  ``_setup_from_init``). The skills capability does NOT create or populate
  this directory.
- ``custom/`` — agent-authored skills. Never touched by any kernel code.

Additional paths come from ``init.json``:

``manifest.capabilities.skills.paths``: list[str] — each entry is scanned
recursively and contributes to the YAML skill catalog injected into the
system prompt's ``skills`` section. Paths may be absolute, relative to the
agent working dir, or tilde-prefixed.

Standard ``.agents/skills`` and ``.claude/skills`` roots are discovered from
the agent working directory through its nearest Git or validated conventional
LingTai project boundary, plus the two user-home roots. Without a boundary,
only the working directory and user roots are considered. Agent Plugin skills remain in the separate ``plugins``
prompt field; they are never composed into this vanilla catalog.

This capability is pure presentation: it scans whatever is on disk and builds
the catalog. It never writes to ``.library/``. File installation is the
initializer's job.

Tool surface: **none**. This capability registers no model-facing tool. The
former public ``skills`` root and its ``info`` action were removed as a clean
break — the one public root for this domain is now ``psyche``, whose
read-only ``psyche(action='skills')`` returns this package's manual. There is
no alias or compatibility wrapper for the old root or for ``skills.info``.

What remains is this capability's private lifecycle ownership, unchanged:
``setup()`` reconciles the catalog and injects the YAML ``skills`` prompt
section, honoring the configured ``paths``; ``_reconcile`` is re-run by
``Agent._install_intrinsic_manuals`` once manuals are on disk and by the one
full-context reconstruction path. Catalog scanning is never reachable from a
model-facing action.

Usage: ``Agent(capabilities={"skills": {"paths": [...]}})`` or via init.json.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from .._catalog import (
    build_catalog_yaml,
    parse_markdown_catalog_file,
    scan_markdown_catalog,
)
from lingtai.kernel.i18n import t

if TYPE_CHECKING:
    from lingtai.kernel.base_agent import BaseAgent

log = logging.getLogger(__name__)

PROVIDERS = {"providers": [], "default": "builtin"}


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

def _resolve_path(p: str, working_dir: Path) -> Path:
    """Resolve a user-declared skills path.

    - Tilde expansion (``~/foo`` → user home).
    - Absolute paths used as-is.
    - Relative paths resolved against the agent working dir.
    """
    expanded = Path(p).expanduser()
    if expanded.is_absolute():
        return expanded
    return (working_dir / expanded).resolve(strict=False)


# ---------------------------------------------------------------------------
# Skill scanner
# ---------------------------------------------------------------------------

def _scan(directory: Path) -> tuple[list[dict], list[dict]]:
    return scan_markdown_catalog(directory, filename="SKILL.md", kind="skill")


def _scan_one_skill(directory: Path) -> tuple[list[dict], list[dict]]:
    """Scan a path that *is* a skill directory rather than a collection of them.

    ``_scan`` looks for ``<child>/SKILL.md`` under the path it is given.
    An explicit or standard root can instead carry its own ``SKILL.md``;
    parse that file directly without scanning its nested reference bundles.
    Plugin registration paths never enter this vanilla path composition.
    """
    entry, problem = parse_markdown_catalog_file(
        directory / "SKILL.md", directory.name, filename="SKILL.md",
    )
    return ([entry] if entry else []), ([problem] if problem else [])


def _standard_paths(working_dir: Path) -> list[Path]:
    """Find conventional roots without scanning arbitrary ancestor contents.

    Ancestors are eligible through the nearest Git boundary (including a
    worktree's .git file), or the project above a literal .lingtai ancestor
    when the current working directory has init.json. Use the nearer boundary;
    otherwise do not infer a project from ordinary parents.
    Missing conventional directories are normal and never produce warnings.
    """
    current = working_dir.resolve()
    ancestry = [current, *current.parents]
    boundary = next(
        (i for i, directory in enumerate(ancestry)
         if (directory / ".git").is_dir() or (directory / ".git").is_file()),
        None,
    )
    if (current / "init.json").is_file():
        lingtai_boundary = next(
            (i + 1 for i, directory in enumerate(ancestry)
             if i > 0 and directory.name == ".lingtai"),
            None,
        )
        if lingtai_boundary is not None:
            boundary = (lingtai_boundary if boundary is None
                        else min(boundary, lingtai_boundary))
    directories = ancestry[:boundary + 1] if boundary is not None else [current]
    roots = [
        directory / convention / "skills"
        for directory in [*directories, Path.home()]
        for convention in (".agents", ".claude")
    ]
    return [root for root in roots if root.is_dir()]


def _compose_paths(agent: "BaseAgent", paths: list[str]) -> list[str]:
    """Compose vanilla roots once by canonical path, preserving source order.

    Intrinsic/custom roots precede configured roots, then standard discovery.
    Plugin registration paths deliberately stay out: the plugins field owns
    their validated, filtered set and its separate namespace.
    """
    working_dir = agent._working_dir
    roots = [
        str(working_dir / ".library" / "intrinsic"),
        str(working_dir / ".library" / "custom"),
        *paths,
        *(str(root) for root in _standard_paths(working_dir)),
    ]
    seen: set[Path] = set()
    unique: list[str] = []
    for raw in roots:
        canonical = _resolve_path(raw, working_dir).resolve()
        if canonical not in seen:
            seen.add(canonical)
            unique.append(raw)
    return unique


# ---------------------------------------------------------------------------
# Core reconciliation (setup/refresh lifecycle and full-context recompose)
# ---------------------------------------------------------------------------

def _reconcile(
    agent: "BaseAgent",
    paths: list[str],
    *,
    publish: bool = True,
) -> dict:
    """Scan built-in, explicit and standard roots, inject catalog, report status.

    The skills capability is pure presentation: it reads whatever the Agent
    initializer wrote to ``.library/intrinsic/`` and the agent wrote to
    ``.library/custom/``. It does NOT create directories or copy files, and it
    performs no migration.

    ``publish=False`` mirrors the Pad/LingTai composers: it writes the section
    without flushing, so full-context reconstruction composes every section
    before the one final prompt publication.
    """
    working_dir = agent._working_dir
    library_dir = working_dir / ".library"
    intrinsic_dir = library_dir / "intrinsic"
    custom_dir = library_dir / "custom"

    problems: list[dict] = []
    status = "ok"
    error: str | None = None

    # Standard discovery is additive; no plugin registration roots enter here.
    all_skills: list[dict] = []
    builtin_roots = {str(intrinsic_dir), str(custom_dir)}
    paths_report: dict[str, dict] = {}
    for raw in _compose_paths(agent, paths):
        resolved = _resolve_path(raw, working_dir)
        exists = resolved.is_dir()
        p_valid: list[dict] = []
        p_problems: list[dict] = []
        if exists:
            # Explicit/standard roots may themselves be one skill; built-in
            # libraries remain collections, preserving their existing scan.
            if raw not in builtin_roots and (resolved / "SKILL.md").is_file():
                p_valid, p_problems = _scan_one_skill(resolved)
            else:
                p_valid, p_problems = _scan(resolved)
            all_skills.extend(p_valid)
            problems.extend(p_problems)
        elif raw not in builtin_roots:
            log.warning("skills: path does not exist: %s (resolved=%s)", raw, resolved)
        if raw not in builtin_roots:
            paths_report[raw] = {
                "resolved": str(resolved),
                "exists": exists,
                "skills": len(p_valid),
            }

    # Build and inject catalog.
    lang = agent._config.language
    catalog_yaml = build_catalog_yaml(all_skills, t(lang, "skills.preamble"))
    if publish:
        agent.update_system_prompt("skills", catalog_yaml or "", protected=True)
    else:
        agent._prompt_manager.write_section(
            "skills", catalog_yaml or "", protected=True,
        )
        agent._token_decomp_dirty = True

    # Health signal: the skills capability's own manual must be present.
    skills_manual_path = intrinsic_dir / "capabilities" / "skills" / "SKILL.md"
    if not skills_manual_path.is_file():
        status = "degraded"
        error = error or (
            "skills manual missing — initializer may have failed or "
            "capability not installed correctly"
        )
        manual_body = ""
    else:
        manual_body = skills_manual_path.read_text(encoding="utf-8")

    result = {
        "status": status,
        "skills_manual": manual_body,
        # Back-compat key kept for callers that have not renamed yet.
        "library_manual": manual_body,
        "skills_dir": str(library_dir),
        # The on-disk directory remains .library for compatibility.
        "library_dir": str(library_dir),
        "catalog_size": len(all_skills),
        "paths": paths_report,
        "problems": problems,
    }
    if error:
        result["error"] = error
    return result


def setup(agent: "BaseAgent", paths: list[str] | None = None, **_ignored) -> None:
    """Set up the skills capability.

    ``paths`` is the Tier 1 list from ``init.json``
    ``manifest.capabilities.skills.paths``. When omitted (e.g. direct
    ``Agent(capabilities=["skills"])`` use without kwargs), the per-agent
    ``.library/`` and automatically discovered standard roots are scanned.

    The capability itself does not create or populate ``.library/``; the Agent
    initializer's ``_install_intrinsic_manuals`` step handles that. Setup just
    scans whatever is on disk and injects the YAML catalog so the first turn
    sees a ready catalog.

    It registers **no** tool. Catalog reconciliation is private lifecycle: it
    runs here at setup/refresh and from the one full-context reconstruction
    path, never from a model-facing action. The public surface for this domain
    is the read-only ``psyche(action='skills')`` manual loader.
    """
    _reconcile(agent, list(paths) if paths else [])
