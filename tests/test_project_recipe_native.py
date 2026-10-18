"""Narrow native-evidence tests; execution belongs to the acceptance owner."""
import base64
import io
import json

import pytest

from lingtai.adapters.project_recipe_native import (
    NativeFilesystemProjectRecipeAdapter, NativeRecipeExchange,
)
from lingtai.kernel.project.recipe import (
    ProjectRecipeUseCase, RecipeApplyRequest, RecipeLayerStat, RecipeOpaquePath,
    RecipeOperationError, select_recipe_layer,
)


def ack(sequence, operation, evidence):
    return json.dumps(dict(status="recipe_native_observed", sequence=sequence,
                           operation=operation, evidence=evidence, failure=None)) + "\n"


def adapter(tmp_path, replies):
    outgoing = io.StringIO()
    port = NativeFilesystemProjectRecipeAdapter(tmp_path, load_preset=lambda *_: {},
        exchange=NativeRecipeExchange(io.StringIO(replies), outgoing))
    return port, outgoing


def test_opaque_init_never_reaches_python_codec(tmp_path, monkeypatch):
    def forbidden(*_):
        pytest.fail("opaque native owner routed into Python JSON reader")
    monkeypatch.setattr("lingtai.adapters.project_recipe._read_init_bytes", forbidden)
    port, outgoing = adapter(tmp_path,
        ack(1, "skills_observe", dict(present=True, canonical_changed=False,
                                     handle=7, paths=[0, "old", 2])) +
        ack(2, "skills_write", dict(written=True)))
    evidence = port.observe_skills("worker")
    assert evidence.owner_content is None
    assert evidence.paths == (RecipeOpaquePath(0), "old", RecipeOpaquePath(2))
    receipt = port.write_skills("worker", evidence, evidence.paths + ("../../lib",))
    assert receipt.written and receipt.reader_status == "not_read_native"
    commands = [json.loads(line) for line in outgoing.getvalue().splitlines()]
    assert commands[1]["arguments"] == dict(directory_name_b64="d29ya2Vy", handle=7,
                                             paths=[0, "old", 2, "../../lib"])
    assert not list(tmp_path.iterdir())


def test_native_metadata_core_rejects_empty_name_before_greet(tmp_path):
    path = base64.b64encode(b"native/source/.recipe/recipe.json").decode()
    port, outgoing = adapter(tmp_path, ack(1, "metadata", dict(
        name="", library_name=None, library_path_entry="", source_path_b64=path)))
    with pytest.raises(RecipeOperationError) as caught:
        ProjectRecipeUseCase(port).apply(RecipeApplyRequest("", None))
    assert caught.value.error.code == "invalid_recipe"
    assert caught.value.failure.path_b64 == path
    assert len(outgoing.getvalue().splitlines()) == 1


def test_layer_first_nondirectory_selection_is_irrevocable():
    class Port:
        def __init__(self):
            self.calls = []
        def stat_layer(self, layer, language):
            self.calls.append((layer, language))
            return RecipeLayerStat(True, False, b"locale-unreadable")
    port = Port()
    selected = select_recipe_layer(port, "comment", "../odd/lang")
    assert selected == b"locale-unreadable"
    assert port.calls == [("comment", "../odd/lang")]
    # No read attempt or readable-root fallback is hidden inside selection.


@pytest.mark.parametrize("reply", [
    "", "{}\n", ack(2, "metadata", {}), ack(1, "skills_observe", {}),
    '{"status":"recipe_native_observed","status":"recipe_native_observed"}\n',
])
def test_unknown_native_transport_does_not_retry_or_write(tmp_path, reply):
    port, outgoing = adapter(tmp_path, reply)
    with pytest.raises((ValueError, KeyError)):
        port.load_info()
    assert len(outgoing.getvalue().splitlines()) == 1
    assert not list(tmp_path.iterdir())


def test_native_root_bytes_decode_at_filesystem_edge_and_observe(tmp_path):
    import errno
    import os
    import sys
    from pathlib import Path
    from lingtai.adapters.project_recipe import decode_native_recipe_path
    from lingtai.cli_project_recipe import execute

    if os.name != "posix":
        pytest.skip("arbitrary filename bytes are a POSIX filesystem case")
    raw = os.fsencode(tmp_path) + b"/root-\xff"
    root = Path(os.fsdecode(raw))
    try:
        root.mkdir()
    except OSError as exc:
        if sys.platform == "darwin" and exc.errno == errno.EILSEQ:
            pytest.skip("filesystem refuses invalid-byte filename with EILSEQ")
        raise
    encoded = base64.b64encode(raw).decode("ascii")
    assert os.fsencode(decode_native_recipe_path(encoded)) == raw
    (root / ".recipe").mkdir()
    (root / ".recipe/recipe.json").write_bytes(b'{"name":"fixture"}')
    replacement = tmp_path / "root-\ufffd"
    assert not replacement.exists()
    observed = execute("recipe-observe", {"project_dir_b64": encoded})
    assert observed["state"] == "changed" and observed["needs_apply"]
    assert not replacement.exists()
    assert execute("recipe-observe", {"project_dir_b64": ""})["state"] == "absent"


@pytest.mark.parametrize("value", [None, 1, "!", "Zh==", "Zg==\n"])
def test_native_path_bytes_require_canonical_base64(value):
    from lingtai.adapters.project_recipe import decode_native_recipe_path
    from lingtai.kernel.project import ProjectCreationError
    with pytest.raises(ProjectCreationError) as caught:
        decode_native_recipe_path(value)
    assert caught.value.error.code == "invalid_project_request"
