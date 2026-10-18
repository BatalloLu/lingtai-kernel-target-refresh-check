"""Filesystem discovery for Project inspection; no filesystem writes."""
from __future__ import annotations

import base64
import os
from pathlib import Path

from lingtai.adapters.posix.agent_presence import PosixAgentPresenceStoreAdapter
from lingtai.kernel.agent_presence import ManifestObservation
from lingtai.kernel.project import ProjectCreationError, ProjectError
from lingtai.kernel.project.inspection import (
    ProjectDirectoryObservation,
    ProjectInspectionPort,
    ProjectMemberEvidence,
    ProjectInitObservation,
    ProjectInitPresence,
    ProjectInitStatFailure,
)


class FilesystemProjectInspectionAdapter(ProjectInspectionPort):
    def __init__(self, root: Path) -> None:
        self._root = root

    def observe_members(self) -> ProjectDirectoryObservation:
        target = self._root / ".lingtai"
        try:
            if not self._root.is_dir():
                raise ProjectCreationError(ProjectError(
                    "invalid_project_root", "project root must be an existing directory",
                ))
            try:
                target.stat()
            except FileNotFoundError:
                return ProjectDirectoryObservation(False, ())
            # iterdir fails loudly if .lingtai exists but is not a directory.
            entries = sorted(target.iterdir(), key=lambda entry: entry.name)
            members: list[ProjectMemberEvidence] = []
            for entry in entries:
                # Go ReadDir's IsDir excludes symlink directory entries.
                if entry.is_symlink() or not entry.is_dir():
                    continue
                manifest_path = entry / ".agent.json"
                try:
                    manifest_path.stat()
                except FileNotFoundError:
                    continue
                except OSError:
                    manifest = ManifestObservation.malformed()
                else:
                    # The shared presence adapter parses regular files. Go
                    # discovery additionally preserves non-file manifests as
                    # present-but-malformed repair targets.
                    manifest = (
                        PosixAgentPresenceStoreAdapter(entry).observe_manifest()
                        if manifest_path.is_file()
                        else ManifestObservation.malformed()
                    )
                members.append(ProjectMemberEvidence(entry.name, manifest))
            return ProjectDirectoryObservation(True, tuple(members))
        except OSError as exc:
            raise ProjectCreationError(ProjectError(
                "project_inspect_failed", "project members could not be observed",
            )) from exc

    def observe_init_presence(self, directory_name: str) -> ProjectInitObservation:
        path = self._root / ".lingtai" / directory_name / "init.json"
        try:
            path.stat()
        except FileNotFoundError:
            return ProjectInitObservation(ProjectInitPresence.ABSENT)
        except OSError as exc:
            # No exception string, filename supplied by the exception, or file
            # contents cross this boundary. Preserve actual requested path bytes.
            failure = ProjectInitStatFailure(
                base64.b64encode(os.fsencode(path)).decode("ascii"),
                exc.errno, getattr(exc, "winerror", None),
            )
            return ProjectInitObservation(ProjectInitPresence.STAT_FAILED, failure)
        return ProjectInitObservation(ProjectInitPresence.PRESENT)
