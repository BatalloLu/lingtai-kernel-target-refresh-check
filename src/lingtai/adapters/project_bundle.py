"""Installed Recipe resources, projected to the old operational byte tree."""
from __future__ import annotations

from importlib.resources import files

from lingtai.kernel._frontmatter import strip_frontmatter

# This is the shipped source manifest, not traversal of an operator filesystem.
# Logical roots retain the native Go io/fs spelling for metadata/error parity.
_BUNDLES = {
    b"recipe_assets/recommended/adaptive": "adaptive",
    b"recipe_assets/intrinsic/greeter": "greeter",
    b"recipe_assets/intrinsic/plain": "plain",
    b"recipe_assets/examples/tutorial": "tutorial",
}
_BEHAVIOR = (
    b".recipe/comment/comment.md", b".recipe/comment/wen/comment.md",
    b".recipe/comment/zh/comment.md", b".recipe/greet/greet.md",
    b".recipe/greet/wen/greet.md", b".recipe/greet/zh/greet.md",
    b".recipe/recipe.json",
)


class PackagedRecipeBundleAdapter:
    def __init__(self) -> None:
        self._files = {
            root + b"/" + relative: (name, relative)
            for root, name in _BUNDLES.items()
            for relative in ((b".recipe/recipe.json",) if name == "plain" else _BEHAVIOR)
        }
        self._directories = {b"."} | {
            b"/".join(path.split(b"/")[:i])
            for path in self._files for i in range(1, len(path.split(b"/")))
        }

    def has_directory(self, root: bytes) -> bool:
        return root in self._directories

    def metadata(self, root: bytes) -> bytes | None:
        relative = b".recipe/recipe.json"
        return self.read(root, relative) if root + b"/" + relative in self._files else None

    def members(self, root: bytes) -> tuple[bytes, ...]:
        prefix = root + b"/"
        # WalkDir sorts immediate entries, then descends depth-first. A sort of
        # whole path strings is NOT equivalent for e.g. a/child versus a.txt.
        return tuple(sorted((path[len(prefix):] for path in self._files
                             if path.startswith(prefix)), key=lambda path: tuple(path.split(b"/"))))

    def read(self, root: bytes, relative: bytes) -> bytes:
        name, member = self._files[root + b"/" + relative]
        resource = files("lingtai.kernel.project").joinpath(
            "recipe_assets", name, "recipe", *member.decode("ascii").split("/")[1:])
        content = resource.read_bytes()
        if member.endswith(b".md"):
            # Developer metadata is source-only; bytes delivered to Go are the
            # exact pre-migration prompt body, never a raw source-file export.
            return strip_frontmatter(content.decode("utf-8")).encode("utf-8")
        return content
