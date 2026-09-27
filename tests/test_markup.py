"""Source parsing must retain prose, code, whitespace, and review identities."""

import pytest

from quarto_review.errors import ReviewError
from quarto_review.markup import Change, Comment, parse, project


@pytest.mark.parametrize(
    ("source", "before", "after"),
    [
        ("A{++ modest++}{#s1} effect.", "A effect.", "A modest effect."),
        ("A{-- strong--}{#s1} effect.", "A strong effect.", "A effect."),
        ("A {~~strong~>modest~~}{#s1} effect.", "A strong effect.", "A modest effect."),
        ("{~~old \n\ntext~>new\n\ntext ~~}{#s1}", "old \n\ntext", "new\n\ntext "),
        ("{~~*old* [@one]~>**new** [@two]~~}{#s1}", "*old* [@one]", "**new** [@two]"),
        ("{~~$x^2$~>$x^3$~~}{#s1}", "$x^2$", "$x^3$"),
        ("{~~café~>café 🧠~~}{#s1}", "café", "café 🧠"),
    ],
)
def test_projections_preserve_source_content(source, before, after):
    document = parse(source)
    assert project(document.nodes, "original") == before
    assert project(document.nodes, "proposed") == after
    assert isinstance(document.annotations()["s1"], Change)


def test_comment_body_has_one_home_and_does_not_enter_prose():
    source = "The {==claim [@one]==}{>>Clarify **this** claim.<<}{#c17}."
    document = parse(source)
    comment = document.annotations()["c17"]
    assert isinstance(comment, Comment)
    assert comment.body == "Clarify **this** claim."
    assert project(document.nodes) == "The claim [@one]."
    assert project(comment.content) == "claim [@one]"


def test_comment_on_deleted_text_survives_parsing():
    document = parse("{--{==old==}{>>Explain.<<}{#c1} --}{#s1}new")
    assert set(document.annotations()) == {"s1", "c1"}
    assert project(document.nodes, "original") == "old new"
    assert project(document.nodes) == "new"


def test_point_comment_and_empty_comment():
    document = parse("Text.{>><<}{#c1}")
    assert document.annotations()["c1"].body == ""
    assert project(document.nodes) == "Text."


@pytest.mark.parametrize(
    "source",
    [
        "`{++literal++}`",
        "`` `{>>literal<<}` ``",
        "```markdown\n{~~old~>new~~}\n```\n",
        "~~~\n{==example==}{>>comment<<}\n~~~\n",
        "\\{++literal\\++}",
        "$x_{++literal++}$",
    ],
)
def test_literal_examples_are_not_review_items(source):
    document = parse(source)
    assert document.annotations() == {}
    assert project(document.nodes) == source


def test_decisions_change_projection_without_mutating_source():
    source = "{~~old~>new~~}{#s1}"
    document = parse(source)
    assert project(document.nodes, "original", {"s1": "accepted"}) == "new"
    assert project(document.nodes, "proposed", {"s1": "rejected"}) == "old"
    assert document.source == source


@pytest.mark.parametrize(
    "source", ["{++missing", "{~~old~>missing", "unmatched ++}", "{>>missing"]
)
def test_malformed_marks_report_source_location(source):
    with pytest.raises(ReviewError, match=r"chapter.qmd:2:"):
        parse("Introduction\n" + source, "chapter.qmd")


def test_duplicate_identity_is_rejected():
    with pytest.raises(ReviewError, match="Duplicate review identifier c1"):
        parse("{>>one<<}{#c1}{>>two<<}{#c1}")


def test_math_delimiter_after_a_latex_line_break():
    document = parse(r"{~~$x\\$~>$y$~~}{#s1}")
    assert project(document.nodes, "original") == r"$x\\$"
    assert project(document.nodes) == "$y$"
