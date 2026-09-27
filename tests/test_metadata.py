"""Metadata keeps discussion history separate from manuscript prose."""

from dataclasses import replace

import pytest

from quarto_review.errors import ReviewError
from quarto_review.markup import parse
from quarto_review.metadata import (
    CommentMetadata,
    Reply,
    ReviewMetadata,
    SuggestionMetadata,
)


def test_metadata_roundtrip_and_comment_body_ownership(tmp_path):
    source = "{==text==}{>>Initial comment.<<}{#c1} {~~old~>new~~}{#s1}"
    metadata = ReviewMetadata(
        author="Example Author",
        created_at="2026-01-01T12:00:00Z",
        comments={
            "c1": CommentMetadata(
                "Reviewer",
                "2026-01-02T12:00:00Z",
                replies=(
                    Reply(
                        "r1",
                        "Reply body.",
                        "Example Author",
                        "2026-01-03T12:00:00Z",
                        "c1",
                    ),
                ),
            )
        },
        suggestions={"s1": SuggestionMetadata("Reviewer", "2026-01-02T12:00:00Z")},
    )
    metadata.validate({"index.qmd": parse(source)})
    path = tmp_path / "review.yml"
    metadata.write(path)
    assert "Initial comment." not in path.read_text()
    assert "Reply body." in path.read_text()
    assert ReviewMetadata.read(path) == metadata


def test_duplicate_yaml_keys_are_rejected(tmp_path):
    path = tmp_path / "review.yml"
    path.write_text("author: One\nauthor: Two\ncreated_at: now\n")
    with pytest.raises(ReviewError, match="Duplicate YAML key"):
        ReviewMetadata.read(path)


def test_unknown_reply_parent_is_rejected():
    metadata = ReviewMetadata(
        "Author",
        "date",
        comments={
            "c1": CommentMetadata(
                "Reviewer",
                None,
                replies=(Reply("r1", "Body", "Author", None, "missing"),),
            )
        },
    )
    with pytest.raises(ReviewError, match="unavailable parent"):
        metadata.validate()


def test_comment_edit_does_not_require_duplicated_yaml_text():
    metadata = ReviewMetadata(
        "Author", "date", comments={"c1": CommentMetadata("Reviewer", None)}
    )
    for body in ["Initial wording", "Revised wording"]:
        metadata.validate({"index.qmd": parse(f"{{==text==}}{{>>{body}<<}}{{#c1}}")})


def test_reopening_retains_replies():
    thread = CommentMetadata(
        "Reviewer",
        None,
        status="resolved",
        replies=(Reply("r1", "Body", "Author", None, "c1"),),
    )
    reopened = replace(thread, status="open")
    assert reopened.replies == thread.replies


def test_missing_source_comment_is_reported():
    metadata = ReviewMetadata(
        "Author", "date", comments={"c1": CommentMetadata("Reviewer", None)}
    )
    with pytest.raises(ReviewError, match="no initial body"):
        metadata.validate({"index.qmd": parse("Text.")})
