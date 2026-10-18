"""Recipe bundle selection and ordered materialization; no filesystem mechanism."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol


@dataclass(frozen=True, slots=True)
class DiskBundleCopy:
    source: bytes
    destination: bytes


@dataclass(frozen=True, slots=True)
class PackagedBundleCopy:
    recipe_name: bytes
    destination: bytes


@dataclass(frozen=True, slots=True)
class WizardBundleStage:
    recipe_name: bytes
    destination: bytes
    global_dir: bytes


BundleRequest = DiskBundleCopy | PackagedBundleCopy | WizardBundleStage


class BundleDirectory(str, Enum):
    DIRECTORY = "directory"
    ABSENT = "absent"
    NOT_DIRECTORY = "not_directory"
    STAT_FAILED = "stat_failed"


class BundleSource(str, Enum):
    EXPLICIT = "explicit"
    LOCAL = "local"
    GLOBAL = "global"
    PACKAGED = "packaged"


@dataclass(frozen=True, slots=True)
class BundleFailure:
    """Opaque operation correlation, not a serialized operating-system error."""
    sequence: int
    operation: str


@dataclass(frozen=True, slots=True)
class BundleMetadata:
    name: bytes
    library: bytes | None


class BundleIOError(Exception):
    def __init__(self, failure: BundleFailure, code: str = "") -> None:
        super().__init__(code)
        self.failure = failure
        self.code = code


@dataclass(frozen=True, slots=True)
class BundleResult:
    source: BundleSource
    outcome: str
    code: str = ""
    failure: BundleFailure | None = None


class RecipeBundlePort(Protocol):
    """Bound to the request's roots. Every call performs its phase once only."""
    def observe_local_recipe(self) -> BundleDirectory: ...
    def find_global(self) -> bool: ...
    def load_metadata(self, source: BundleSource) -> BundleMetadata: ...
    def absolute_locations(self, source: BundleSource) -> tuple[bytes | None, bytes | None]: ...
    def remove_recipe(self) -> None: ...
    def copy_recipe(self, source: BundleSource) -> None: ...
    def observe_library(self, source: BundleSource, library: bytes) -> BundleDirectory: ...
    def copy_library(self, source: BundleSource, library: bytes) -> None: ...
    def observe_network(self, source: BundleSource) -> BundleDirectory: ...
    def copy_network(self, source: BundleSource) -> None: ...
    def packaged_candidates(self) -> tuple[bytes, ...]: ...
    def decode_packaged_metadata(self, root: bytes, content: bytes | None) -> BundleMetadata: ...
    def prepare_packaged_file(self, relative: bytes) -> None: ...
    def write_packaged_file(self, relative: bytes, content: bytes) -> None: ...


class RecipeBundleResourcesPort(Protocol):
    """Read-only installed catalog, independent of caller disk and bootstrap."""
    def has_directory(self, root: bytes) -> bool: ...
    def metadata(self, root: bytes) -> bytes | None: ...
    def members(self, root: bytes) -> tuple[bytes, ...]: ...
    def read(self, root: bytes, relative: bytes) -> bytes: ...


class RecipeBundleUseCase:
    def __init__(self, io: RecipeBundlePort, resources: RecipeBundleResourcesPort) -> None:
        self.io = io
        self.resources = resources

    @staticmethod
    def _phase(code, call, *args):
        try:
            return call(*args)
        except BundleIOError as exc:
            raise BundleIOError(exc.failure, code) from None

    def materialize(self, request: BundleRequest) -> BundleResult:
        source = (BundleSource.EXPLICIT if isinstance(request, DiskBundleCopy)
                  else BundleSource.PACKAGED)
        try:
            if isinstance(request, WizardBundleStage):
                # A valid local bundle wins even when the requested name is empty.
                if self.io.observe_local_recipe() is BundleDirectory.DIRECTORY:
                    try:
                        local = self.io.load_metadata(BundleSource.LOCAL)
                    except BundleIOError:
                        pass
                    else:
                        if local.name:
                            return BundleResult(BundleSource.LOCAL, "unchanged")
                if self.io.find_global():
                    source = BundleSource.GLOBAL
            if source is BundleSource.PACKAGED:
                return self._packaged(request)
            if not request.destination or (isinstance(request, DiskBundleCopy) and not request.source):
                return BundleResult(source, "rejected", "empty_paths")
            metadata = self._phase("source_invalid", self.io.load_metadata, source)
            if not metadata.name:
                return BundleResult(source, "rejected", "source_empty_name")
            library = metadata.library
            # Metadata precedes both Abs calls; failed Abs observations are not refusals.
            src, dst = self.io.absolute_locations(source)
            if src is not None and dst is not None and src == dst:
                return BundleResult(source, "unchanged")
            self._phase("remove_recipe_failed", self.io.remove_recipe)
            self._phase("copy_recipe_failed", self.io.copy_recipe, source)
            if library and self.io.observe_library(source, library) is BundleDirectory.DIRECTORY:
                self._phase("copy_library_failed", self.io.copy_library, source, library)
            if self.io.observe_network(source) is BundleDirectory.DIRECTORY:
                self._phase("copy_network_failed", self.io.copy_network, source)
            return BundleResult(source, "complete")
        except BundleIOError as exc:
            # Any failed I/O can have partial effects. Never infer zero writes.
            return BundleResult(source, "failed", exc.code, exc.failure)

    def _packaged(self, request: PackagedBundleCopy | WizardBundleStage) -> BundleResult:
        source = BundleSource.PACKAGED
        if not request.recipe_name or not request.destination:
            return BundleResult(source, "rejected", "empty_paths")
        # Native lexical joining only; catalog/category preference remains here.
        root = next((candidate for candidate in self.io.packaged_candidates()
                     if self.resources.has_directory(candidate)), None)
        if root is None:
            return BundleResult(source, "rejected", "packaged_not_found")
        metadata = self._phase("source_invalid", self.io.decode_packaged_metadata,
                               root, self.resources.metadata(root))
        if not metadata.name:
            return BundleResult(source, "rejected", "source_empty_name")
        self._phase("remove_recipe_failed", self.io.remove_recipe)
        for relative in self.resources.members(root):
            # Old embedded copy creates parent BEFORE reading that resource.
            self._phase("packaged_create_failed", self.io.prepare_packaged_file, relative)
            content = self.resources.read(root, relative)
            self._phase("packaged_write_failed", self.io.write_packaged_file, relative, content)
        return BundleResult(source, "complete")
