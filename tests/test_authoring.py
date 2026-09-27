"""Review operations must preserve source ownership and the fixed reference."""

import pytest

from quarto_review.authoring import annotate, synchronize
from quarto_review.comparison import compare
from quarto_review.errors import ReviewError
from quarto_review.markup import parse
from quarto_review.markup import project as project_text
from quarto_review.project import Project, capture_reference, setup


def test_grouping_an_existing_edit_does_not_duplicate_it(tmp_path):
    original = "A strong effect.\n"
    (tmp_path / "index.qmd").write_text(original)
    manuscript = setup(tmp_path, author="Writer")
    capture_reference(manuscript)
    (tmp_path / "index.qmd").write_text("A modest effect.\n")
    manuscript = Project.read(tmp_path)
    identifier = annotate(manuscript, "index.qmd", "modest", before="strong")
    comparison = compare(
        manuscript.documents["index.qmd"],
        parse(original),
        manuscript.metadata,
        reference_id="reference",
        date=manuscript.metadata.created_at,
    )
    assert comparison.automatic_ids == ()
    manuscript.decide(identifier, "accept")
    comparison = compare(
        manuscript.documents["index.qmd"],
        parse(original),
        manuscript.metadata,
        reference_id="reference",
        date=manuscript.metadata.created_at,
    )
    assert comparison.automatic_ids == ()
    assert project_text(manuscript.documents["index.qmd"].nodes) == "A modest effect.\n"
    assert (tmp_path / "review/reference/index.qmd").read_text() == original


def test_new_typed_annotations_are_registered_once(tmp_path):
    (tmp_path / "index.qmd").write_text("A claim.\n")
    setup(tmp_path, author="Writer")
    (tmp_path / "index.qmd").write_text("A {==claim==}{>>Why?<<}.\n")
    assert synchronize(tmp_path, author="Reviewer")["added"] == ["c1"]
    assert synchronize(tmp_path)["added"] == []
    manuscript = Project.read(tmp_path)
    assert manuscript.feedback()[0]["body"] == "Why?"
    assert manuscript.metadata.comments["c1"].author == "Reviewer"
    assert "Why?" not in (tmp_path / "review.yml").read_text()


def test_rewritten_decided_suggestion_requires_reopening(tmp_path):
    (tmp_path / "index.qmd").write_text("A {~~strong~>modest~~}{#s1} effect.\n")
    manuscript = setup(tmp_path, author="Writer")
    manuscript.decide("s1", "accept")
    (tmp_path / "index.qmd").write_text("A {~~strong~>weak~~}{#s1} effect.\n")
    with pytest.raises(ReviewError, match="was rewritten"):
        Project.read(tmp_path)
    manuscript = Project.read(tmp_path, validate_decisions=False)
    manuscript.decide("s1", "pending")
    assert Project.read(tmp_path).metadata.suggestions["s1"].status == "pending"
