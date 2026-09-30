"""Native citation syntax must compose with existing review operations."""

import pytest

from quarto_review.markup import project
from quarto_review.source import read

HEADER = """---
review:
  schema: 2
  author: A
  authors:
    A: Example Author
  reference: reference.qmd
---

"""


@pytest.mark.parametrize(
    ("body", "before", "after"),
    [
        (
            "[@smith2020]{--, an aside--}{#s1 by=A}.",
            "[@smith2020], an aside.",
            "[@smith2020].",
        ),
        (
            "[@smith2020]{++; @brown2021++}{#s1 by=A}",
            "[@smith2020]",
            "[@smith2020]; @brown2021",
        ),
        (
            "[@smith2020]{~~ old~> new~~}{#s1 by=A}",
            "[@smith2020] old",
            "[@smith2020] new",
        ),
    ],
)
def test_citation_adjacent_to_criticmarkup(body, before, after):
    model = read(HEADER + body)
    assert project(model.document.nodes, "original").endswith(before)
    assert project(model.document.nodes, "proposed").endswith(after)
    assert model.metadata.suggestions["s1"].author == "Example Author"


def test_bracketed_comment_on_a_citation_remains_supported():
    model = read(
        HEADER
        + "[[@smith2020]]{#c1}\n\n::: {.review-thread #c1 by=A}\nCheck this citation.\n:::\n"
    )
    assert model.metadata.comments["c1"].author == "Example Author"
    assert "[@smith2020]" in project(model.document.nodes)
