"""Existing local Recipe observation/apply contract; no fresh-creation attempt."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum

from . import ProjectCreationError, ProjectError


def recipe_error(code: str) -> ProjectCreationError:
    return ProjectCreationError(ProjectError(code, "Project Recipe operation could not complete"))


class RecipeState(str, Enum):
    ABSENT = "absent"
    EQUAL = "equal"
    CHANGED = "changed"
    READ_FAILURE = "read_failure"


@dataclass(frozen=True, slots=True)
class RecipeTree:
    present: bool
    files: tuple[tuple[str, bytes], ...] = ()
    read_failed: bool = False


@dataclass(frozen=True, slots=True)
class RecipeObservation:
    state: RecipeState
    needs_apply: bool


@dataclass(frozen=True, slots=True)
class RecipeInfo:
    name: str
    library_name: str | None = None
    library_path_entry: str = ""  # native relative spelling supplied by adapter
    invalid_failure: RecipeFailure | None = None


@dataclass(frozen=True, slots=True)
class GreetLayer:
    selected: bool = False
    content: bytes = b""
    read_failed: bool = False


@dataclass(frozen=True, slots=True)
class RecipeRendering:
    # Exact public strings resolved by Go's existing callback. None = identity
    # rendering, as used by headless plain; never a cross-language function.
    time: str
    address: str
    location: str
    commands: str


@dataclass(frozen=True, slots=True)
class RecipeApplyRequest:
    language: str
    rendering: RecipeRendering | None


@dataclass(frozen=True, slots=True)
class RecipeFailure:
    """Factual native failure evidence, never an exception message."""
    phase: str
    operation: str
    path_b64: str = ""
    errno: int | None = None
    winerror: int | None = None
    parse_offset: int | None = None  # byte offset, zero-based when known


class RecipeOperationError(ProjectCreationError):
    def __init__(self, code: str, failure: RecipeFailure) -> None:
        super().__init__(ProjectError(code, "Project Recipe operation could not complete"))
        self.failure = failure


@dataclass(frozen=True, slots=True)
class RecipeMemberGreet:
    sequence: int
    directory_name: bytes
    template: bytes


class RecipeRenderingStopped(Exception):
    """Exchange stopped; contains no caller data or arbitrary exception text."""


class RecipeGreetRenderingPort(ABC):
    @abstractmethod
    def render(self, member: RecipeMemberGreet) -> bytes: ...


@dataclass(frozen=True, slots=True)
class RecipeSkills:
    # Adapter-owned normalized bytes, never an effective/materialized init dump.
    owner_content: bytes | None = None
    present: bool = False
    paths: tuple[object, ...] = ()
    canonical_changed: bool = False
    code: str = ""
    failure: RecipeFailure | None = None
    document_handle: int = 0  # operation-local opaque owner identity


@dataclass(frozen=True, slots=True)
class RecipeWrite:
    written: bool = False
    reader_status: str = "not_read"
    code: str = ""
    failure: RecipeFailure | None = None


@dataclass(frozen=True, slots=True)
class RecipeMemberReceipt:
    directory_name: str
    prompt_written: bool = False
    init_written: bool = False
    reader_status: str = "not_read"
    code: str = ""
    legacy_counted: bool = False
    prompt_code: str = ""
    init_code: str = ""
    directory_identity: bytes = b""


@dataclass(frozen=True, slots=True)
class RecipeSnapshotReceipt:
    attempted: bool = False
    removal_succeeded: bool = False
    copied: bool = False
    code: str = ""
    failure: RecipeFailure | None = None


@dataclass(frozen=True, slots=True)
class RecipeApplyResult:
    outcome: str
    members: tuple[RecipeMemberReceipt, ...] = ()
    snapshot: RecipeSnapshotReceipt = RecipeSnapshotReceipt()
    greet_status: str = "absent"
    code: str = ""
    legacy_failure: RecipeFailure | None = None


class RecipeExchangeStopped(Exception):
    def __init__(self, result: RecipeApplyResult, pending: RecipeMemberGreet) -> None:
        super().__init__("Project Recipe rendering exchange stopped")
        self.result = result
        self.pending = pending


class ProjectRecipePort(ABC):
    """Bound to an existing project root; evidence and specialized writes only."""

    @abstractmethod
    def observe_trees(self) -> tuple[RecipeTree, RecipeTree]: ...

    @abstractmethod
    def load_info(self) -> RecipeInfo: ...

    @abstractmethod
    def observe_greet(self, language: str) -> GreetLayer: ...

    @abstractmethod
    def observe_directories(self) -> tuple[str, ...]: ...

    def directory_identity(self, directory_name: str) -> bytes:
        # Memory adapters' ordinary Unicode identity. Filesystems override with
        # their lossless native encoding, never replace malformed name bytes.
        return directory_name.encode("utf-8")

    @abstractmethod
    def write_prompt(self, directory_name: str, content: bytes) -> RecipeWrite: ...

    @abstractmethod
    def observe_skills(self, directory_name: str) -> RecipeSkills: ...

    @abstractmethod
    def write_skills(self, directory_name: str, evidence: RecipeSkills,
                     paths: tuple[object, ...]) -> RecipeWrite: ...

    @abstractmethod
    def replace_snapshot(self) -> RecipeSnapshotReceipt: ...


def render_greet(content: bytes, language: str, rendering: RecipeRendering | None) -> bytes:
    if rendering is None:
        return content
    # bytes replacement preserves arbitrary Go string bytes in local templates.
    for token, value in (("time", rendering.time), ("addr", rendering.address),
                         ("lang", language), ("location", rendering.location),
                         ("commands", rendering.commands)):
        content = content.replace(("{{" + token + "}}").encode(), value.encode("utf-8"))
    return content


class ProjectRecipeUseCase:
    def __init__(self, port: ProjectRecipePort, rendering_port: RecipeGreetRenderingPort | None = None) -> None:
        self.port = port
        self.rendering_port = rendering_port

    def observe(self) -> RecipeObservation:
        selected, snapshot = self.port.observe_trees()
        if not selected.present:
            return RecipeObservation(RecipeState.READ_FAILURE if selected.read_failed else RecipeState.ABSENT, False)
        if selected.read_failed or snapshot.read_failed:
            return RecipeObservation(RecipeState.READ_FAILURE, True)
        if not snapshot.present:
            return RecipeObservation(RecipeState.CHANGED, True)
        state = RecipeState.EQUAL if dict(selected.files) == dict(snapshot.files) else RecipeState.CHANGED
        return RecipeObservation(state, state is RecipeState.CHANGED)

    def _load_info(self) -> RecipeInfo:
        info = self.port.load_info()
        if not info.name:
            if info.invalid_failure is not None:
                raise RecipeOperationError("invalid_recipe", info.invalid_failure)
            raise recipe_error("invalid_recipe")
        return info

    def apply(self, request: RecipeApplyRequest) -> RecipeApplyResult:
        info = self._load_info()
        greet = self.port.observe_greet(request.language)
        # The old helper re-loads metadata AFTER the single greet read, and only
        # when the FIRST load declared a library. Failure here is not fatal.
        library_path = ""
        if info.library_name:
            try:
                library_info = self._load_info()
                if library_info.library_name:
                    library_path = library_info.library_path_entry or "../../" + library_info.library_name
            except ProjectCreationError:
                pass
        greet_status = ("unreadable" if greet.read_failed else "empty" if greet.selected and not greet.content
                        else "selected" if greet.selected else "absent")
        directories = self.port.observe_directories()
        members: list[RecipeMemberReceipt] = []
        first_code = legacy_first = ""
        legacy_failure = None
        sequence = 0
        for name in sorted(directories, key=self.port.directory_identity):
            if not name or name.startswith(".") or name == "human":
                continue
            prompt = RecipeWrite()
            init = RecipeWrite()
            member_code = ""
            skip = False
            if greet.content and not greet.read_failed:
                content = greet.content
                if self.rendering_port is not None:
                    sequence += 1
                    pending = RecipeMemberGreet(sequence, self.port.directory_identity(name), content)
                    try:
                        content = self.rendering_port.render(pending)
                    except RecipeRenderingStopped:
                        known_writes = any(m.prompt_written or m.init_written for m in members)
                        result = RecipeApplyResult("partial" if known_writes else "rejected",
                                                   tuple(members), greet_status=greet_status,
                                                   code=legacy_first, legacy_failure=legacy_failure)
                        raise RecipeExchangeStopped(result, pending) from None
                else:
                    content = render_greet(content, request.language, request.rendering)
                # ORIGINAL presence controls write: an empty result truncates.
                prompt = self.port.write_prompt(name, content)
                if prompt.code:
                    member_code = prompt.code
                    if not legacy_first:
                        legacy_first = prompt.code
                        legacy_failure = prompt.failure
                        skip = True
            if library_path and not skip:
                evidence = self.port.observe_skills(name)
                if evidence.code:
                    init = RecipeWrite(code=evidence.code, failure=evidence.failure)
                elif evidence.present:
                    has_path = library_path in evidence.paths
                    if not has_path or evidence.canonical_changed:
                        paths = evidence.paths if has_path else evidence.paths + (library_path,)
                        init = self.port.write_skills(name, evidence, paths)
                if init.code:
                    member_code = member_code or init.code
                    # Reader failure follows a successful old-style write; it is
                    # real partial failure, not a legacy AppendSkillsPath failure.
                    if init.code != "recipe_reader_failed" and not legacy_first:
                        legacy_first = init.code
                        legacy_failure = init.failure
                        skip = True
            first_code = first_code or member_code
            members.append(RecipeMemberReceipt(name, prompt.written, init.written,
                                                init.reader_status, member_code, not skip,
                                                prompt.code, init.code, self.port.directory_identity(name)))
        # Explicitly retain old ALWAYS-after-traversal behavior, even on partial.
        snapshot = self.port.replace_snapshot()
        first_code = first_code or snapshot.code
        # Top-level code/exit preserves old ApplyRecipe error behavior. Actual
        # postwrite reader failure is receipt evidence, not a new launch block.
        legacy_code = legacy_first or snapshot.code
        return RecipeApplyResult("partial" if first_code else "complete", tuple(members),
                                 snapshot, greet_status, legacy_code,
                                 legacy_failure if legacy_first else snapshot.failure)


@dataclass(frozen=True, slots=True)
class RecipeOpaquePath:
    """An original non-text path entry; never its unknown owner subtree."""
    entry: int


@dataclass(frozen=True, slots=True)
class RecipeLayerStat:
    exists: bool
    directory: bool = False
    identity: bytes = b""


class RecipeLayerPort(ABC):
    @abstractmethod
    def stat_layer(self, layer: str, language: str) -> RecipeLayerStat: ...


def select_recipe_layer(port: RecipeLayerPort, layer: str, language: str) -> bytes:
    # A successful non-directory stat selects irrevocably. Reading, when needed,
    # is a separate effect; read failure must not resume the fallback chain.
    for locale in ((language, "") if language else ("",)):
        evidence = port.stat_layer(layer, locale)
        if evidence.exists and not evidence.directory:
            return evidence.identity
    return b""
