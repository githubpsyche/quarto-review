"""A generated cache must agree with parsing and invalidate on source edits."""

from unittest.mock import patch

from quarto_review.cache import parse_cached
from quarto_review.markup import parse


def test_cached_ast_matches_fresh_parse_and_invalidates(tmp_path):
    source = "A {=={~~strong~>modest~~}{#s1} effect==}{>>Clarify this.<<}{#c1}."
    expected = parse(source, "index.qmd")
    assert parse_cached(source, "index.qmd", tmp_path) == expected
    with patch(
        "quarto_review.markup.parse", side_effect=AssertionError("Cache missed")
    ):
        assert parse_cached(source, "index.qmd", tmp_path) == expected
    edited = source.replace("modest", "small")
    assert parse_cached(edited, "index.qmd", tmp_path) == parse(edited, "index.qmd")
    assert len(list(tmp_path.glob("*.json"))) == 2


def test_corrupted_cache_is_rebuilt(tmp_path):
    source = "A {++word++}{#s1}."
    first = parse_cached(source, "index.qmd", tmp_path)
    next(tmp_path.glob("*.json")).write_text('{"truncated":')
    assert parse_cached(source, "index.qmd", tmp_path) == first
