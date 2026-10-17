"""Private Pad composition over the durable body and pinned reference list.

Everything here is internal. There is no public ``pad`` tool root and no
``append`` action; the pinned reference list is a durable *source* that this
module reads and composes, and that the agent edits through ``shell`` like any
other durable text.
"""
from __future__ import annotations

import json
import os
import stat
import tempfile
from pathlib import Path


# ---------------------------------------------------------------------------
# Pad append-file reading
# ---------------------------------------------------------------------------

_APPEND_LIST_PATH = "system/pad_append.json"


def _append_list_file(agent) -> Path:
    return agent._working_dir / _APPEND_LIST_PATH


def _load_append_list(agent) -> list[str]:
    """Read the persisted append file list (empty list if missing)."""
    path = _append_list_file(agent)
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return [str(p) for p in data]
    except (json.JSONDecodeError, OSError):
        pass
    return []


def _resolve_path(agent, fpath: str) -> Path:
    if os.path.isabs(fpath):
        return Path(fpath)
    return agent._working_dir / fpath


def _read_append_content(agent, files: list[str]) -> tuple[str, list[str]]:
    """Read all append files. Returns (combined content, not_found list)."""
    parts: list[str] = []
    not_found: list[str] = []
    for fpath in files:
        resolved = _resolve_path(agent, fpath)
        if not resolved.is_file():
            not_found.append(fpath)
            continue
        parts.append(f"[append: {fpath}]\n{resolved.read_text(encoding='utf-8')}")
    return "\n\n".join(parts), not_found


# ---------------------------------------------------------------------------
# Pad composition
# ---------------------------------------------------------------------------


def _seed_pad(system_dir: Path, seed: str) -> None:
    """Materialize an initial seed before any legacy memory can fill Pad."""
    if not isinstance(seed, str):
        raise RuntimeError("resolved pad must be a string or null")
    path = system_dir / "pad.md"
    if seed and (not path.is_file() or path.read_bytes() == b""):
        system_dir.mkdir(exist_ok=True)
        path.write_text(seed, encoding="utf-8")


def _legacy_memory_seed(workdir: Path, data: dict) -> str | None:
    """Resolve old init input once, preserving file bytes and inline fallback.

    A completed migration never reopens the old configured source. This keeps
    accepted old init data from becoming an ongoing forced-identity binding.
    """
    if (workdir / "system" / "lingtai-merged-into-pad").exists():
        return None
    if "lingtai" not in data and "lingtai_file" not in data:
        return None
    value = data.get("lingtai", "")
    pointer = data.get("lingtai_file")
    if pointer:
        path = Path(pointer).expanduser()
        if not path.is_absolute():
            path = workdir / path
        if path.is_file():
            return path.read_bytes().decode("utf-8")
    return value


def _merge_legacy_memory(system_dir: Path, seed: str | None = None) -> None:
    """Preserve legacy character bytes once, without an ongoing source binding.

    The marker survives deliberate Pad rewrites and deep Avatar copies. If a
    process stops after Pad replacement but before marking, exact containment
    avoids appending the same legacy body again. The workdir lease serializes
    runtime writers; this is not a concurrent external-edit merge protocol.
    """
    legacy = system_dir / "lingtai.md"
    marker = system_dir / "lingtai-merged-into-pad"
    if marker.exists() or (not legacy.is_file() and seed is None):
        return
    pad = system_dir / "pad.md"
    if pad.is_symlink():
        raise ValueError("legacy memory merge requires a regular system/pad.md")
    legacy_body = legacy.read_bytes() if legacy.is_file() else b""
    pad_body = pad.read_bytes() if pad.exists() else b""
    # Decode before any write: invalid UTF-8 is an error, never lossy memory.
    legacy_body.decode("utf-8")
    pad_body.decode("utf-8")
    merged = pad_body
    # Preserve disk-authored character AND a distinct configured value. Neither
    # may overwrite existing Pad or the other legacy source during upgrade.
    for body in (legacy_body, seed.encode("utf-8") if seed is not None else b""):
        if body and body not in merged:
            merged += (b"\n\n" if merged else b"") + body
    if merged != pad_body:
        temporary: Path | None = None
        try:
            # Binary write preserves both owners' bytes, including CRLF on
            # Windows. Replace atomically rather than risking a partial append.
            with tempfile.NamedTemporaryFile(dir=system_dir, delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(merged)
                stream.flush()
                os.fsync(stream.fileno())
            if pad.exists():
                temporary.chmod(stat.S_IMODE(pad.stat().st_mode))
            temporary.replace(pad)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    # This records a completed one-time preservation, not a source digest to
    # follow. Later edits to legacy character do not re-enter private memory.
    with marker.open("xb") as stream:
        stream.write(b"Legacy memory inputs preserved in system/pad.md.\n")
        stream.flush()
        os.fsync(stream.fileno())


def _pad_load(
    agent, args: dict, *, publish: bool = True, migrate_legacy: bool = True,
) -> dict:
    """Compose system/pad.md plus pinned references into the prompt.

    ``publish=False`` is used only by canonical full-context reconstruction so
    every section is composed before one final prompt publication.
    """
    system_dir = agent._working_dir / "system"
    system_dir.mkdir(exist_ok=True)
    pad_path = system_dir / "pad.md"
    if not pad_path.is_file():
        pad_path.write_text("", encoding="utf-8")

    if migrate_legacy:
        _merge_legacy_memory(system_dir)
    # A stale in-memory character slot must not duplicate the unified memory.
    agent._prompt_manager.delete_section("character")

    content = pad_path.read_text(encoding="utf-8")
    size_bytes = len(content.encode("utf-8"))

    if content.strip():
        agent._prompt_manager.write_section("pad", content)
    else:
        agent._prompt_manager.delete_section("pad")

    # Append-files layering — pinned read-only reference appended to pad section
    append_files = _load_append_list(agent)
    append_meta: dict = {}
    if append_files:
        append_content, not_found = _read_append_content(agent, append_files)
        if append_content:
            existing = agent._prompt_manager.read_section("pad") or ""
            combined = existing + "\n\n---\n# 📎 Reference (read-only)\n\n" + append_content
            agent._prompt_manager.write_section("pad", combined)
        if not_found:
            append_meta["append_not_found"] = not_found
        append_meta["append_files"] = append_files
        append_meta["append_count"] = len(append_files)

    agent._token_decomp_dirty = True
    if publish:
        agent._flush_system_prompt()

    agent._log("psyche_pad_load", size_bytes=size_bytes)

    result: dict = {
        "status": "ok",
        "path": str(pad_path),
        "size_bytes": size_bytes,
        "content_preview": content[:200],
    }
    result.update(append_meta)
    return result
