"""Review actions must retain a fixed reference and one home for each body."""

import json

import pytest

from quarto_review.errors import ReviewError
from quarto_review.project import Project, capture_reference, setup


def test_setup_reply_decision_and_reference(tmp_path):
    (tmp_path / "index.qmd").write_text(
        "A {==claim==}{>>Explain this.<<} and {~~old~>new~~}.\n"
    )
    project = setup(tmp_path, author="Example Author")
    assert set(project.metadata.comments) == {"c1"}
    assert set(project.metadata.suggestions) == {"s1"}
    manifest = capture_reference(project)
    reference = tmp_path / "review/reference"
    frozen = {path.name: path.read_bytes() for path in reference.iterdir()}
    reply = project.reply("c1", "Here is the explanation.")
    project.reply(reply, "A further detail.")
    project.decide("c1", "resolve")
    project.decide("s1", "reject")
    reread = Project.read(tmp_path)
    assert reread.metadata.comments["c1"].status == "resolved"
    assert reread.metadata.comments["c1"].replies[1].parent_id == reply
    assert reread.metadata.suggestions["s1"].status == "rejected"
    assert reread.feedback()[0]["anchors"] == ["claim"]
    assert "Explain this." not in (tmp_path / "review.yml").read_text()
    assert {path.name: path.read_bytes() for path in reference.iterdir()} == frozen
    with pytest.raises(ReviewError, match="must be explicit"):
        capture_reference(reread)
    capture_reference(reread, new_round=True)
    assert (
        tmp_path / "review/rounds" / manifest["id"] / "index.qmd"
    ).read_bytes() == frozen["index.qmd"]


def test_reference_copies_bibliography_and_assets(tmp_path):
    (tmp_path / "index.qmd").write_text(
        "---\nbibliography: references.bib\n---\n\n![Caption](figure.svg)\n"
    )
    (tmp_path / "references.bib").write_text("@article{example, title={Example}}")
    (tmp_path / "figure.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
    (tmp_path / "_quarto.yml").write_text("format: html\n")
    project = setup(tmp_path, author="Example Author")
    manifest = capture_reference(project)
    assert set(manifest["files"]) == {
        "index.qmd",
        "review.yml",
        "references.bib",
        "figure.svg",
        "_quarto.yml",
    }
    assert (
        json.loads((tmp_path / "review/reference/manifest.json").read_text())["id"]
        == manifest["id"]
    )


def test_setup_validation_precedes_source_edits(tmp_path):
    source = "{>>Keep this comment.<<}"
    (tmp_path / "index.qmd").write_text(source)
    with pytest.raises(ReviewError, match="explicit author"):
        setup(tmp_path, author="")
    assert (tmp_path / "index.qmd").read_text() == source
    assert not (tmp_path / "review.yml").exists()
