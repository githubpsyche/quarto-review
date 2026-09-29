from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from zipfile import ZipFile

import pytest
from lxml import etree

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "quarto_review/extension/word_options.py"
spec = importlib.util.spec_from_file_location("word_options", MODULE)
options = importlib.util.module_from_spec(spec)
spec.loader.exec_module(options)
W = options.W


@pytest.fixture
def document(tmp_path):
    path = tmp_path / "review.docx"
    with ZipFile(path, "w") as z:
        z.writestr(
            "word/settings.xml",
            f'<w:settings xmlns:w="{W}"><w:proofState/><w:doNotTrackMoves/><w:compat/></w:settings>',
        )
        z.writestr(
            "word/document.xml",
            "<document>Pending wording and comment anchors</document>",
        )
        z.writestr(
            "word/comments.xml", "<comments>Author, reply, resolved state</comments>"
        )
    return path


def test_tracking_preserves_all_other_parts_and_is_idempotent(document):
    with ZipFile(document) as z:
        before = {name: z.read(name) for name in z.namelist()}
    assert options.track_changes(document, True)
    once = document.read_bytes()
    assert not options.track_changes(document, True)
    assert document.read_bytes() == once
    with ZipFile(document) as z:
        for name, content in before.items():
            if name != "word/settings.xml":
                assert z.read(name) == content
        root = etree.fromstring(z.read("word/settings.xml"))
        assert [etree.QName(n).localname for n in root] == [
            "proofState",
            "trackRevisions",
            "doNotTrackMoves",
            "compat",
        ]
    assert options.track_changes(document, False)
    with ZipFile(document) as z:
        assert (
            etree.fromstring(z.read("word/settings.xml"))
            .find(f"{{{W}}}trackRevisions")
            .get(f"{{{W}}}val")
            == "false"
        )


def test_omission_and_non_word_outputs_are_untouched(document):
    root = document.parent
    (root / "_quarto.yml").write_text("quarto-review: {}\n")
    before = document.read_bytes()
    options.apply_project_options(root, [document.name])
    assert document.read_bytes() == before
    (root / "_quarto.yml").write_text(
        "quarto-review:\n  word:\n    track-changes: true\n"
    )
    options.apply_project_options(root, ["index.html"])
    assert document.read_bytes() == before


def test_finished_package_is_not_reopened(document):
    root = document.parent
    (root / "_quarto.yml").write_text(
        "quarto-review:\n  word:\n    track-changes: true\n"
    )
    plans = root / ".quarto/review/plans"
    plans.mkdir(parents=True)
    before = document.read_bytes()
    (plans / "a.json").write_text(
        json.dumps(
            {
                "output": document.name,
                "finished_hash": hashlib.sha256(before).hexdigest(),
            }
        )
    )
    options.apply_project_options(root, [document.name])
    assert document.read_bytes() == before


@pytest.mark.parametrize("setting", ["'true'", "1", "null"])
def test_invalid_settings_fail_before_changing_document(document, setting):
    root = document.parent
    (root / "_quarto.yml").write_text(
        f"quarto-review:\n  word:\n    track-changes: {setting}\n"
    )
    before = document.read_bytes()
    with pytest.raises(ValueError, match="true or false"):
        options.apply_project_options(root, [document.name])
    assert document.read_bytes() == before
