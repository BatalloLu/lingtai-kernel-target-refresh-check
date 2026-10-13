"""Fresh-creation Recipe resources: project-local authority or wheel-owned adaptive."""
from __future__ import annotations

import json
import shutil
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path

from lingtai.kernel.project.interactive_creation import (
    CreationAttempt, CreationRecipePort, RecipeLayers, RecipeSelection, creation_error,
)
from .project_interactive_workspace import FilesystemInteractiveWorkspaceAdapter


class FilesystemCreationRecipeAdapter(CreationRecipePort):
    def __init__(self, workspace: FilesystemInteractiveWorkspaceAdapter) -> None:
        self.workspace = workspace

    @staticmethod
    def _selection(source: str, data: bytes) -> RecipeSelection:
        value = json.loads(data)
        if not isinstance(value, dict) or not isinstance(value.get("name"), str) or not value["name"]:
            raise ValueError("invalid Recipe")
        library = value.get("library_name")
        if library == "":
            library = None
        if library is not None and not isinstance(library, str):
            raise ValueError("invalid Recipe library")
        for key in ("description", "version"):
            if key in value and value[key] is not None and not isinstance(value[key], str):
                raise ValueError("invalid Recipe metadata")
        identity = value.get("id", "")
        if identity is None:
            identity = ""
        if not isinstance(identity, str):
            raise ValueError("invalid Recipe identity")
        return RecipeSelection(source, identity, library)

    def observe_local(self) -> RecipeSelection | None:
        try:
            return self._selection("local", (self.workspace.root / ".recipe" / "recipe.json").read_bytes())
        except (OSError, ValueError, UnicodeError):
            # Baseline: stray/malformed .recipe is not a selected valid bundle.
            return None

    def packaged_default(self) -> RecipeSelection:
        root = files("lingtai.kernel.project").joinpath("recipe_assets", "adaptive")
        return self._selection("packaged", root.joinpath("recipe", "recipe.json").read_bytes())

    @staticmethod
    def _copy_resource(source: Traversable, target: Path) -> None:
        target.mkdir(parents=True, exist_ok=True)
        for child in source.iterdir():
            destination = target / child.name
            if child.is_dir():
                FilesystemCreationRecipeAdapter._copy_resource(child, destination)
            else:
                content = child.read_bytes()
                if child.name.endswith(".md"):
                    from lingtai.kernel._frontmatter import strip_frontmatter
                    content = strip_frontmatter(content.decode("utf-8")).encode("utf-8")
                destination.write_bytes(content)

    def materialize(self, selection: RecipeSelection, attempt: CreationAttempt,
                    language: str) -> RecipeLayers:
        stage = self.workspace.owned_stage(attempt)
        # A parsed local bundle remains authoritative even when its library
        # cannot be represented as a safe project-root sibling. Fail, don't
        # misclassify it as malformed and overwrite it with adaptive.
        library = selection.library_name
        if library and (library in {".", ".."} or any(c in library for c in "/\\\x00")):
            raise creation_error("invalid_recipe_library")
        recipe = self.workspace.root / ".recipe"
        if selection.source == "packaged":
            # Only replace an invalid/unselected Recipe, never valid local bytes.
            if recipe.is_symlink() or (recipe.exists() and not recipe.is_dir()):
                recipe.unlink()
            elif recipe.exists():
                shutil.rmtree(recipe)
            root = files("lingtai.kernel.project").joinpath("recipe_assets", "adaptive", "recipe")
            self._copy_resource(root, recipe)
        elif selection.source != "local":
            raise creation_error("invalid_recipe_selection")
        # No imported .lingtai payload is copied in this fresh-creation slice.
        # Library is already project-local; resources ship adaptive with no library.
        snapshot = stage / ".tui-asset" / ".recipe"
        snapshot.parent.mkdir(exist_ok=True)
        shutil.copytree(recipe, snapshot)
        (snapshot.parent / "recipe-state.json").write_text(
            json.dumps({"recipe": "adaptive"}) + "\n", encoding="utf-8")

        def layer(name: str) -> Path | None:
            for path in (recipe / name / language / (name + ".md"), recipe / name / (name + ".md")):
                if path.is_file():
                    return path
            return None

        comment, covenant, greet = layer("comment"), layer("covenant"), layer("greet")
        return RecipeLayers(
            comment=comment.read_text(encoding="utf-8") if comment else "",
            covenant_file=str(covenant) if covenant else None,
            greet=greet.read_text(encoding="utf-8") if greet else None,
            library_path="../../" + selection.library_name if selection.library_name else None,
        )
