"""Thin regressions for additive, bounded vanilla SKILL.md discovery."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from lingtai.tools import skills


def _skill(root: Path, folder: str, name: str = "same-name") -> Path:
    path = root / folder / "SKILL.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        f"---\nname: {name}\ndescription: Discoverable procedure\n---\n"
        "BODY-MUST-STAY-ON-DISK\n", encoding="utf-8",
    )
    return path


@pytest.mark.parametrize("boundary", ["directory", "worktree-file", "none"])
def test_standard_roots_are_ordered_and_bounded(tmp_path, monkeypatch, boundary):
    home = tmp_path / "home"
    project = tmp_path / "project"
    workdir = project / "nested" / "agent"
    workdir.mkdir(parents=True)
    if boundary == "directory":
        (project / ".git").mkdir()
    elif boundary == "worktree-file":
        (project / ".git").write_text("gitdir: /not-followed\n", encoding="utf-8")
    directories = [workdir, workdir.parent, project, tmp_path, home]
    for directory in directories:
        for convention in (".agents", ".claude"):
            (directory / convention / "skills").mkdir(parents=True)
    # Shell cwd must not replace the Agent's own working directory.
    monkeypatch.chdir(home)
    monkeypatch.setattr(Path, "home", lambda: home)
    eligible = directories[:3] if boundary != "none" else [workdir]
    assert skills._standard_paths(workdir) == [
        directory / convention / "skills"
        for directory in [*eligible, home]
        for convention in (".agents", ".claude")
    ]


@pytest.mark.parametrize("layout", ["initialized", "no-init", "nearer-git"])
def test_lingtai_project_boundary_requires_init_and_respects_nearer_git(
    tmp_path, monkeypatch, layout,
):
    project = tmp_path / "project"
    workdir = project / ".lingtai" / "agent"
    workdir.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "empty-home")
    root = project / ".claude" / "skills"
    _skill(root, "project-procedure")
    _skill(tmp_path / ".claude" / "skills", "outside")
    if layout != "no-init":
        (workdir / "init.json").write_text("{}", encoding="utf-8")
    if layout == "nearer-git":
        (workdir / ".git").mkdir()
    assert skills._standard_paths(workdir) == (
        [root] if layout == "initialized" else []
    )


def test_missing_standard_roots_are_normal_and_explicit_roots_still_report(
    tmp_path, monkeypatch, caplog,
):
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "empty-home")
    agent = SimpleNamespace(
        _working_dir=tmp_path, _config=SimpleNamespace(language="en"),
        update_system_prompt=Mock(),
    )
    result = skills._reconcile(agent, ["missing-explicit"])
    assert result["catalog_size"] == 0
    assert result["paths"] == {
        "missing-explicit": {
            "resolved": str(tmp_path / "missing-explicit"),
            "exists": False, "skills": 0,
        },
    }
    assert "missing-explicit" in caplog.text
    assert ".agents" not in caplog.text
    assert ".claude" not in caplog.text


def test_reconcile_preserves_names_plugins_problems_and_canonical_root_dedup(
    tmp_path, monkeypatch,
):
    home = tmp_path / "home"
    workdir = tmp_path / "project" / "agent"
    workdir.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", lambda: home)
    intrinsic = workdir / ".library" / "intrinsic"
    _skill(intrinsic / "capabilities", "skills", "skills-manual")
    custom = workdir / ".library" / "custom"
    _skill(custom, "custom")
    explicit = workdir / "explicit"
    _skill(explicit, "explicit")
    standard = workdir / ".agents" / "skills"
    _skill(standard, "standard")
    _skill(home / ".claude" / "skills", "personal")
    malformed = standard / "malformed" / "SKILL.md"
    malformed.parent.mkdir()
    malformed.write_text("---\nname: incomplete\n---\n", encoding="utf-8")
    plugin = tmp_path / "plugin" / "skills"
    _skill(plugin, "packaged", "PLUGIN-MUST-STAY-SEPARATE")
    alias = workdir / ".claude" / "skills"
    alias.parent.mkdir()
    try:
        alias.symlink_to(standard, target_is_directory=True)
        (standard / "linked").symlink_to(explicit / "explicit", target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlinks unavailable: {exc}")
    agent = SimpleNamespace(
        _working_dir=workdir, _config=SimpleNamespace(language="en"),
        _plugin_skill_paths=[str(plugin / "packaged")],
        update_system_prompt=Mock(),
        _prompt_manager=SimpleNamespace(write_section=Mock()),
    )
    scan = Mock(wraps=skills._scan)
    monkeypatch.setattr(skills, "_scan", scan)
    roots = ["explicit", str(standard), str(alias), str(custom), "./explicit"]
    result = skills._reconcile(agent, roots, publish=False)
    assert [call.args[0].resolve() for call in scan.call_args_list] == [
        intrinsic.resolve(), custom.resolve(), explicit.resolve(),
        standard.resolve(), (home / ".claude" / "skills").resolve(),
    ]
    assert result["catalog_size"] == 6  # distinct same-name paths are not merged
    assert len(result["problems"]) == 1
    assert "missing required frontmatter field: description" in result["problems"][0]["reason"]
    args, kwargs = agent._prompt_manager.write_section.call_args
    assert args[0] == "skills"
    assert args[1].count("- name: same-name") == 5
    assert "BODY-MUST-STAY-ON-DISK" not in args[1]
    assert "PLUGIN-MUST-STAY-SEPARATE" not in args[1]
    assert str(standard / "linked" / "SKILL.md") in args[1]
    assert kwargs == {"protected": True}
    agent.update_system_prompt.assert_not_called()
    assert agent._token_decomp_dirty is True
    _skill(workdir / ".claude" / "skills", "later", "added-after-rebuild")
    refreshed = skills._reconcile(agent, roots)
    assert refreshed["catalog_size"] == 7
    assert "added-after-rebuild" in agent.update_system_prompt.call_args.args[1]


def test_claude_description_only_skill_uses_directory_name(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "empty-home")
    skill = tmp_path / ".claude" / "skills" / "folder-name" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("---\ndescription: Standard Claude skill\n---\nPRIVATE-BODY\n", encoding="utf-8")
    agent = SimpleNamespace(_working_dir=tmp_path,
        _config=SimpleNamespace(language="en"), update_system_prompt=Mock())
    result = skills._reconcile(agent, [])
    assert result["catalog_size"] == 1
    assert result["problems"] == []
    rendered = agent.update_system_prompt.call_args.args[1]
    assert "- name: folder-name" in rendered and "PRIVATE-BODY" not in rendered
    _, problem = skills.parse_markdown_catalog_file(skill, "folder-name", filename="KNOWLEDGE.md")
    assert "missing required frontmatter field: name" in problem["reason"]


def test_automatic_bad_encoding_does_not_remove_valid_catalog(tmp_path, monkeypatch):
    home = tmp_path / "home"
    workdir = tmp_path / "agent"
    workdir.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    good = _skill(workdir / ".library" / "custom", "good", "retained")
    bad = home / ".claude" / "skills" / "bad" / "SKILL.md"
    bad.parent.mkdir(parents=True)
    bad.write_bytes(b"\xff\xfe not UTF-8")
    agent = SimpleNamespace(
        _working_dir=workdir, _config=SimpleNamespace(language="en"),
        update_system_prompt=Mock(),
        _prompt_manager=SimpleNamespace(write_section=Mock()),
    )
    result = skills._reconcile(agent, [], publish=False)
    assert result["catalog_size"] == 1
    assert len(result["problems"]) == 1
    assert "cannot read SKILL.md" in result["problems"][0]["reason"]
    assert str(good) in agent._prompt_manager.write_section.call_args.args[1]
    assert bad.read_bytes() == b"\xff\xfe not UTF-8"
