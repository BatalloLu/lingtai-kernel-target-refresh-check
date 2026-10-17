"""One catalog smoke: bounded roots, omitted names and malformed encoding."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from lingtai.tools import skills


def test_standard_skill_discovery_smoke(tmp_path, monkeypatch):
    home = tmp_path / "home"
    project = tmp_path / "project"
    workdir = project / ".lingtai" / "agent"
    workdir.mkdir(parents=True)
    (workdir / "init.json").write_text("{}")
    monkeypatch.setattr(Path, "home", lambda: home)
    paths = [
        workdir / ".library" / "custom" / "retained" / "SKILL.md",
        project / ".agents" / "skills" / "project-skill" / "SKILL.md",
        home / ".claude" / "skills" / "user-skill" / "SKILL.md",
        tmp_path / ".agents" / "skills" / "outside" / "SKILL.md",
    ]
    for path in paths:
        path.parent.mkdir(parents=True)
        path.write_text("---\ndescription: Procedure\n---\nPRIVATE BODY")
    bad = home / ".claude" / "skills" / "bad" / "SKILL.md"
    bad.parent.mkdir()
    bad.write_bytes(b"\xff\xfe not UTF-8")
    agent = SimpleNamespace(
        _working_dir=workdir, _config=SimpleNamespace(language="en"),
        update_system_prompt=Mock(),
        _prompt_manager=SimpleNamespace(write_section=Mock()),
    )
    result = skills._reconcile(agent, [])
    assert result["catalog_size"] == 3
    assert len(result["problems"]) == 1
    assert "cannot read SKILL.md" in result["problems"][0]["reason"]
    rendered = agent.update_system_prompt.call_args.args[1]
    for path in paths[:3]:
        assert str(path) in rendered and f"- name: {path.parent.name}" in rendered
    assert str(paths[3]) not in rendered and "PRIVATE BODY" not in rendered
    assert bad.read_bytes() == b"\xff\xfe not UTF-8"
