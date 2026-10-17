---
name: skills-behavior-tests
behavior_version: 1
labt_version: 2
contract: CONTRACT.md
anatomy: ANATOMY.md
related_files:
  - src/lingtai/tools/skills/CONTRACT.md
  - src/lingtai/tools/skills/ANATOMY.md
  - src/lingtai/tools/skills/__init__.py
  - src/lingtai/tools/_catalog.py
  - src/lingtai/tools/skills/manual/SKILL.md
  - tests/test_standard_skill_discovery.py
maintenance: |
  Created during the every-contract-needs-behaviors sweep. Keep this file
  reciprocal with CONTRACT.md and ANATOMY.md (tridirectional loop): when a
  skills tool behavior clause changes, update the guarding LABT here in the
  same change.
---
> Test-reference maintenance (2026-10-12): `retired-test:` identifiers below name removed pytest coverage, not runnable selectors or replacement conformance. Product promises are unchanged; manual acceptance remains necessary where automated coverage was surrendered.

# Skills Capability Behavior Tests

Self-contained agent behavior tasks guarding the observable behavior clauses of
`src/lingtai/tools/skills/CONTRACT.md` (info/manual only, strict-empty input,
canonical degraded shape, action separation). Pinned pytest commands must run
from the repo root with the project's Python.

## Behavior SK001 — info only refreshes the catalogue and manual only reads the installed manual

- **id**: SK001
- **title**: info only refreshes the catalogue and manual only reads the installed manual
- **guards**: `skills-contract` § Tool surface
- **runner**: any LingTai agent with `shell` access to this repository
- **prerequisites**: a clean checkout of `<repo>`; a scratch agent working directory `<scratch>` with a skills catalog
- **estimate**: ≈ 15 minutes

### Steps
1. From `<repo>`, **Automated step unavailable: pytest recipe retired (2026-10-12); no replacement conformance claimed** and capture the outcome.
2. Call `skills(action="info", input={}, reasoning="probe")` and record the result; confirm it reconciles the catalog and re-injects the prompt without authoring, pinning, publishing, installing, or executing a skill.
3. Call `skills(action="manual", input={}, reasoning="probe")` and record the result; confirm no catalogue scan or prompt injection occurred, and that an extra `input` key fails with `INVALID_ARGUMENT` before any handler I/O.

### Expected evidence
- [ ] Step 1: the skills suite passes, pinning catalog behavior, prompt injection, and the skills/knowledge boundary.
- [ ] Step 2: `info` returns `{status, skills_dir, library_dir, catalog_size, paths, problems}` with no manual body and performs no side effect beyond reconciliation.
- [ ] Step 3: `manual` returns `{status, skills_manual, library_manual, manual_path}` (or the degraded shape when the manual is missing); any `input` key is rejected before handler I/O; unknown actions yield `ACTION_REQUIRED`.

### Pass / Fail
Pass when the suite passes and the action-separation observations hold. Fail on `info` installing/executing a skill, on `manual` performing a catalogue scan, or on an accepted input field; record the evidence trail in the task report.

## Behavior SK002 — Standard folders are discovered without changing plugin ownership

- **id**: SK002
- **title**: Bounded vanilla folder discovery composes metadata without installation
- **guards**: `skills-contract` § [Standard folder discovery](CONTRACT.md#standard-folder-discovery)
- **runner**: any LingTai coding agent with shell access to a source checkout
- **prerequisites**: a source checkout at `<repo>` with its repository Python environment; an authorized scratch directory `<scratch>`; no live agent directories are used
- **estimate**: 10 minutes

### Steps
From the checkout root, run this with the repository Python. It constructs a
real Agent using a mock service (no provider/network calls) and leaves its
scratch evidence on disk. Set `PYTHONPATH=src` if the checkout is not installed.

```python
from pathlib import Path
from tempfile import mkdtemp
from unittest.mock import patch
from lingtai.agent import Agent
from lingtai.llm.service import CONSERVATIVE_CONTEXT_WINDOW
from lingtai.tools.skills import _reconcile, _standard_paths
from tests._service_helpers import make_mock_llm_service

scratch = Path(mkdtemp(prefix="skills-SK002-"))
project = scratch / "project"
workdir = project / "nested" / "agent"
workdir.mkdir(parents=True)
(project / ".git").mkdir()
home = scratch / "home"
home.mkdir()
def skill(root, folder):
    path = root / folder / "SKILL.md"
    path.parent.mkdir(parents=True)
    path.write_text("---\nname: demo\ndescription: Demo procedure\n---\nBODY-ONLY\n",
                    encoding="utf-8")
    return path
local = skill(workdir / ".claude" / "skills", "local")
shared = skill(project / ".agents" / "skills", "shared")
outside = skill(scratch / ".agents" / "skills", "outside")
service = make_mock_llm_service()
service._base_url = None
service._context_window = CONSERVATIVE_CONTEXT_WINDOW
service._provider_defaults = {"anthropic": {"max_rpm": 60}}
with patch.object(Path, "home", return_value=home):
    agent = Agent(service=service, agent_name="skills-probe",
                  working_dir=workdir, capabilities=["skills"])
    prompt = agent._build_system_prompt()
    assert str(local) in prompt and str(shared) in prompt
    assert str(outside) not in prompt and "BODY-ONLY" not in prompt
    (scratch / "prompt-before.txt").write_text(prompt, encoding="utf-8")
    # The fake marker was made by this isolated scenario, never a real repo.
    (project / ".git").rmdir()
    (project / ".git").write_text("gitdir: /unused\n", encoding="utf-8")
    _reconcile(agent, [])
    assert str(shared) in agent._build_system_prompt()
    (project / ".git").unlink()
    _reconcile(agent, [str(local.parent.parent), str(local.parent.parent / ".")])
    section = agent._prompt_manager.read_section("skills")
    assert section.count(str(local)) == 1 and str(shared) not in section
    (scratch / "prompt-after.txt").write_text(agent._build_system_prompt(), encoding="utf-8")
    conventional = project / ".lingtai" / "probe"
    conventional.mkdir(parents=True)
    assert project / ".agents" / "skills" not in _standard_paths(conventional)
    (conventional / "init.json").write_text("{}", encoding="utf-8")
    assert project / ".agents" / "skills" in _standard_paths(conventional)
    assert scratch / ".agents" / "skills" not in _standard_paths(conventional)
    (conventional / ".git").mkdir()
    assert project / ".agents" / "skills" not in _standard_paths(conventional)
print(scratch)
```

### Expected evidence
- [ ] Script exits successfully and prints the retained scratch evidence path.
- [ ] `prompt-before.txt` contains both project/current skill locations, neither
      the outside location nor `BODY-ONLY`.
- [ ] Git directory and worktree-file markers both include the project root.
- [ ] Literal `.lingtai` ancestry requires current-workdir `init.json`, includes
      only its project, and yields to a nearer Git boundary.
- [ ] `prompt-after.txt` excludes the project skill without a boundary; explicit
      canonical aliases retain one local entry.
- [ ] Discovery/reconciliation never installs, copies, or executes skill files.

### Pass / Fail
Pass only when every observation holds. Fail on any assertion, unexpected file
mutation outside scratch, or provider/network activity. This scenario guards
runtime composition; `tests/test_standard_skill_discovery.py` additionally locks
plugin registration exclusion, malformed metadata, symlink roots/folders, user
roots, name collisions, missing-root reporting and subsequent rescans. Do not
claim plugin runtime conformance solely from this vanilla scenario.
