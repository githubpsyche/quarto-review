"""Net changes must avoid duplicated suggestions and review-body noise."""

import pytest

from quarto_review.comparison import align_automatic_ids, compare
from quarto_review.errors import ReviewError
from quarto_review.markup import parse, project
from quarto_review.metadata import CommentMetadata, ReviewMetadata, SuggestionMetadata


def compared(current, reference, metadata=None):
    metadata = metadata or ReviewMetadata("Writer", "2026-01-01T00:00:00Z")
    return compare(
        parse(current, "index.qmd"),
        parse(reference, "index.qmd"),
        metadata,
        reference_id="round-one",
        date="2026-01-02T00:00:00Z",
    )


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ("A strong effect.\n", "A modest effect.\n"),
        ("First.\n\nLast.\n", "First.\n\nAdded paragraph.\n\nLast.\n"),
        ("First.\n\nDeleted paragraph.\n\nLast.\n", "First.\n\nLast.\n"),
        ("See [@one] and $x^2$.\n", "See [@two] and $x^3$.\n"),
        ("A *strong* effect.\n", "A **modest** effect.\n"),
        ("A café result.\n", "A café 🧠 result.\n"),
    ],
)
def test_ordinary_edits_preserve_both_views(before, after):
    result = compared(after, before)
    assert result.automatic_ids
    assert project(result.document.nodes, "original") == before
    assert project(result.document.nodes) == after
    assert result.document.source == after
    assert compared(after, before).automatic_ids == result.automatic_ids


def test_soft_line_breaks_are_not_prose_changes():
    before = "One sentence. Another sentence.\n"
    after = "One sentence.\nAnother sentence.\n"
    assert compared(after, before).automatic_ids == ()
    assert compared(before, after).automatic_ids == ()


def test_explicit_markdown_line_break_is_still_a_change():
    before = "One sentence. Another sentence.\n"
    after = "One sentence.  \nAnother sentence.\n"
    assert compared(after, before).automatic_ids


def test_sentence_line_breaks_do_not_hide_wording_edits():
    before = "One sentence. Another sentence.\n"
    after = "One sentence.\nA different sentence.\n"
    result = compared(after, before)
    assert len(result.automatic_ids) == 1
    assert project(result.document.nodes, "original").replace("\n", " ").strip() == before.strip()
    assert project(result.document.nodes).strip() == after.strip()


def test_comment_body_changes_are_not_prose_changes():
    metadata = ReviewMetadata("Writer", "2026-01-01T00:00:00Z")
    metadata.comments["c1"] = CommentMetadata("Reviewer", metadata.created_at)
    result = compared(
        "A {==claim==}{>>Revised comment.<<}{#c1}.\n",
        "A {==claim==}{>>Old comment.<<}{#c1}.\n",
        metadata,
    )
    assert result.automatic_ids == ()


def test_new_explicit_replacement_is_not_detected_twice():
    metadata = ReviewMetadata("Writer", "2026-01-01T00:00:00Z")
    metadata.suggestions["s1"] = SuggestionMetadata("Writer", metadata.created_at)
    result = compared(
        "A {~~strong~>modest~~}{#s1} effect.\n", "A strong effect.\n", metadata
    )
    assert result.automatic_ids == ()


def test_rendered_suggestions_use_authored_ids_after_metadata_is_removed():
    header = "---\ntitle: A manuscript\n---\n\n"
    original = "A strong effect.\n\nAnother strong effect.\n"
    revised = original.replace("strong", "modest")
    authored = compared(header + revised, header + original)
    rendered = compared(revised, original)
    aligned = align_automatic_ids(rendered, authored)
    assert aligned.automatic_ids == authored.automatic_ids
    assert project(aligned.document.nodes, "original") == original
    assert project(aligned.document.nodes) == revised


@pytest.mark.parametrize("decision", ["pending", "accepted", "rejected"])
def test_decisions_apply_to_reference_in_memory(decision):
    metadata = ReviewMetadata("Writer", "2026-01-01T00:00:00Z")
    metadata.suggestions["s1"] = SuggestionMetadata(
        "Reviewer", metadata.created_at, status=decision
    )
    source = "A {~~strong~>modest~~}{#s1} effect.\n"
    assert compared(source, source, metadata).automatic_ids == ()


def test_edit_inside_a_resolved_suggestion_is_new_author_work():
    metadata = ReviewMetadata("Writer", "2026-01-01T00:00:00Z")
    metadata.suggestions["s1"] = SuggestionMetadata(
        "Reviewer", metadata.created_at, status="accepted"
    )
    result = compared(
        "A {~~strong~>small~~}{#s1} effect.\n",
        "A {~~strong~>modest~~}{#s1} effect.\n",
        metadata,
    )
    assert len(result.automatic_ids) == 1
    assert result.metadata.suggestions[result.automatic_ids[0]].author == "Writer"


def test_crossing_review_boundary_requires_explicit_grouping():
    metadata = ReviewMetadata("Writer", "2026-01-01T00:00:00Z")
    metadata.comments["c1"] = CommentMetadata("Reviewer", metadata.created_at)
    with pytest.raises(ReviewError, match="crosses a review annotation"):
        compared(
            "An {==entirely new==}{>>Explain.<<}{#c1} sentence.\n",
            "A {==small==}{>>Explain.<<}{#c1} claim.\n",
            metadata,
        )


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ("A claim.\n", "[]{#ref-example .anchor}A claim.\n"),
        ("[]{#ref-example .anchor}A claim.\n", "A claim.\n"),
        ("[]{#old}A claim.\n", "[]{#new .anchor}A claim.\n"),
        ("A claim.\n", "A []{#point}claim.\n"),
        ("A claim.\n", "A claim.[]{#end}\n"),
        ("", "[]{#point}"),
    ],
)
def test_empty_navigation_anchors_are_not_prose_edits(before, after):
    result = compared(after, before)
    assert result.automatic_ids == ()
    assert project(result.document.nodes, "original") == after
    assert project(result.document.nodes) == after


def test_new_navigation_anchor_does_not_hide_adjacent_wording_change():
    before = "A strong claim.\n"
    after = "A []{#point .anchor}modest claim.\n"
    result = compared(after, before)
    assert len(result.automatic_ids) == 1
    change = result.document.annotations()[result.automatic_ids[0]]
    assert project(change.before) == "strong"
    assert project(change.after) == "modest"
    assert project(result.document.nodes) == after
    assert project(result.document.nodes, "original") == "A []{#point .anchor}strong claim.\n"


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ("Use `[]{#old}`.\n", "Use `[]{#new}`.\n"),
        ("```markdown\n[]{#old}\n```\n", "```markdown\n[]{#new}\n```\n"),
        (r"Use \[]{#old}.", r"Use \[]{#new}."),
        ("[Old label]{#point}\n", "[New label]{#point}\n"),
        ("[See](#old).\n", "[See](#new).\n"),
    ],
)
def test_visible_anchor_syntax_and_link_changes_still_track(before, after):
    result = compared(after, before)
    assert result.automatic_ids
    assert project(result.document.nodes, "original") == before
    assert project(result.document.nodes) == after
