"""Discussion formatting preserves literal imports and isolates message Markdown."""

from dataclasses import asdict, replace

import pytest
from lxml import html

from quarto_review import pandoc
from quarto_review.discussion import render_messages
from quarto_review.errors import ReviewError
from quarto_review.html import review_panel
from quarto_review.markup import parse
from quarto_review.metadata import CommentMetadata, Reply, ReviewMetadata
from quarto_review.migration import convert_verified, inventory
from quarto_review.project import Project
from quarto_review.rendering import prepare_render
from quarto_review.source import read

HEADER = """---
review:
  schema: 2
  author: A
  authors:
    A: Example Author
    R: Example Reviewer
---
"""


@pytest.mark.integration
def test_rich_bodies_are_batched_and_keep_independent_markdown(monkeypatch):
    calls = []
    original = pandoc.run

    def counted(*args, **kwargs):
        calls.append(kwargs["source"])
        return original(*args, **kwargs)

    monkeypatch.setattr(pandoc, "run", counted)
    messages = {
        "c1": (
            "A **strong** and *qualified* claim with `literal * code`.\n"
            "Same paragraph.\n\n- first\n- second\n\n> A quotation.\n\n"
            '[paper](https://example.org/paper "Paper")\n\n'
            "[shared]: https://example.org/first\n\n[shared]",
            "markdown",
        ),
        "r1": ('[shared]\n\n~~~python\nx = "*literal*"\n~~~', "markdown"),
        "r2": ("~~~\nunclosed", "markdown"),
        "r3": ("Still **formatted**.", "markdown"),
    }
    result = render_messages(messages)
    assert len(calls) == 1
    root = html.fragment_fromstring(result["c1"])
    assert root.xpath(".//strong")[0].text == "strong"
    assert root.xpath(".//em")[0].text == "qualified"
    assert root.xpath(".//code")[0].text == "literal * code"
    assert [li.text for li in root.xpath(".//li")] == ["first", "second"]
    assert root.xpath(".//blockquote/p")[0].text == "A quotation."
    assert root.xpath(".//a/@href") == [
        "https://example.org/paper",
        "https://example.org/first",
    ]
    assert "Same paragraph." in root.xpath(".//p")[0].text_content()
    reply = html.fragment_fromstring(result["r1"])
    assert not reply.xpath(".//a")
    assert "[shared]" in reply.text_content()
    assert 'x = "*literal*"' in reply.xpath(".//pre")[0].text_content()
    assert "<strong>formatted</strong>" in result["r3"]


@pytest.mark.integration
def test_markup_and_links_cannot_add_active_content():
    body = (
        "<script>alert(1)</script>\n\n<img src=x onerror=alert(1)>\n\n"
        '<iframe src="https://example.org"></iframe>\n\n'
        "[bad](javascript:alert%281%29) "
        "[data](data:text/html,evil) [file](file:///tmp/secret) "
        "[encoded](jav&#x61;script:alert%281%29) "
        "[safe](https://example.org) [email](mailto:author@example.org) "
        "[local](../section.html#claim)\n\n"
        "![Alternative text](https://example.org/tracker.png)"
    )
    result = render_messages({"c1": (body, "markdown")})["c1"]
    root = html.fragment_fromstring(result)
    assert not root.xpath(".//script|.//img|.//iframe|.//style|.//object")
    assert root.xpath(".//a/@href") == [
        "https://example.org",
        "mailto:author@example.org",
        "../section.html#claim",
    ]
    assert "<script>alert(1)</script>" in root.text_content()
    assert "Alternative text" in root.text_content()
    for node in root.iterdescendants():
        assert not any(
            key.startswith("on") or key in {"style", "id", "src"} for key in node.attrib
        )


def test_plain_bodies_need_no_converter_and_keep_exact_text(monkeypatch):
    def unexpected(*args, **kwargs):
        raise AssertionError("Plain discussions should not invoke Pandoc")

    monkeypatch.setattr(pandoc, "run", unexpected)
    body = "*literal* _underscores_ [brackets] <tag>\n  Second line.\n\nLast."
    result = render_messages({"c1": (body, "plain")})["c1"]
    root = html.fragment_fromstring(result)
    assert root.text_content() == body
    assert not len(root)
    assert "qr-body-plain" in root.get("class")
    with pytest.raises(ReviewError, match="unsupported body format"):
        render_messages({"c1": (body, "html")})


@pytest.mark.integration
def test_migrated_plain_threads_and_new_markdown_replies_keep_state(tmp_path):
    body = "*literal* [link](https://example.org) <tag>"
    metadata = ReviewMetadata(
        "Example Author",
        "",
        comments={
            "c1": CommentMetadata(
                "Example Reviewer",
                "2026-01-02",
                "resolved",
                (
                    Reply(
                        "r1",
                        "**literal reply**",
                        "Example Author",
                        "2026-01-03",
                        "c1",
                        {"word_id": "11"},
                        True,
                    ),
                ),
                {"word_id": "10", "durable_id": "AABBCCDD"},
            ),
        },
    )
    from quarto_review.authoring import escape_comment

    document = parse("{==Claim==}{>>" + escape_comment(body) + "<<}{#c1}")
    original = inventory(document, metadata)
    source = convert_verified(document, metadata)
    assert source.count("format=plain") == 2
    model = read(source)
    assert inventory(model.document, model.metadata) == original
    for name in ("index.qmd", "reference.qmd"):
        (tmp_path / name).write_text(source)
    project = Project.read(tmp_path)
    identifier = project.reply("r1", "A **formatted** reply.\n\n- evidence")
    project.decide("c1", "reopen")
    project.decide("c1", "resolve")
    loaded = Project.read(tmp_path)
    thread = loaded.metadata.comments["c1"]
    assert thread.provenance == metadata.comments["c1"].provenance
    assert thread.replies[0].provenance == {"word_id": "11"}
    assert thread.body_format == thread.replies[0].body_format == "plain"
    assert thread.replies[-1].id == identifier
    assert thread.replies[-1].parent_id == "r1"
    assert thread.replies[-1].body_format == "markdown"
    assert loaded.ordinary_changes()["index.qmd"].automatic_ids == ()
    assert (tmp_path / "reference.qmd").read_text() == source
    prepared = prepare_render(loaded.documents["index.qmd"], loaded.metadata)
    before = asdict(loaded.metadata)
    panel = html.fragment_fromstring(review_panel(prepared))
    bodies = panel.xpath('.//article[@class="qr-thread"]//div[contains(concat(" ", @class, " "), " qr-body ")]')
    assert bodies[0].text_content() == body
    assert bodies[1].text_content() == "**literal reply**"
    assert bodies[2].xpath(".//strong")[0].text == "formatted"
    assert bodies[2].xpath(".//li")[0].text == "evidence"
    assert asdict(loaded.metadata) == before


def test_older_word_provenance_defaults_to_plain_with_explicit_opt_in():
    source = (
        HEADER
        + """
[Claim]{#c1}.

:::: {.review-thread #c1 by=R}
<!-- review-data: {"provenance":{"word_id":"12"}} -->
**Literal**

::: {.reply #r1 by=A}
<!-- review-data: {"provenance":{"word_id":"13"}} -->
*Also literal*
:::
::::
"""
    )
    model = read(source)
    assert model.metadata.comments["c1"].body_format == "plain"
    assert model.metadata.comments["c1"].replies[0].body_format == "plain"
    opt_in = read(
        source.replace("#c1 by=R", "#c1 by=R format=markdown").replace(
            "#r1 by=A", "#r1 by=A format=markdown"
        )
    )
    assert opt_in.metadata.comments["c1"].body_format == "markdown"
    assert opt_in.document.annotations()["c1"].body == "**Literal**"
    changed = ReviewMetadata.from_mapping(asdict(opt_in.metadata))
    changed.comments["c1"] = replace(changed.comments["c1"], status="resolved")
    saved = read(opt_in.updated(changed))
    assert saved.metadata.comments["c1"].body_format == "markdown"
    assert saved.metadata.comments["c1"].replies[0].body_format == "markdown"
    assert saved.metadata.comments["c1"].provenance == {"word_id": "12"}
    with pytest.raises(ReviewError, match="format must be plain or markdown"):
        read(source.replace("#c1 by=R", "#c1 by=R format=html"))
    metadata = model.metadata
    metadata.comments["c1"] = replace(metadata.comments["c1"], body_format="html")
    with pytest.raises(ReviewError, match="unsupported body format"):
        metadata.validate()


@pytest.mark.integration
def test_word_import_punctuation_stays_literal_in_html(tmp_path, word_package):
    from quarto_review.word.comments import write_comments
    from quarto_review.word.importer import import_document
    from quarto_review.word.reader import read_review

    original = read_review(word_package)
    comments = [
        replace(c, text="*literal* [x](https://example.org) <tag>")
        for c in original.comments
    ]
    write_comments(word_package, comments)
    path = tmp_path / "review.docx"
    word_package.write(path)
    destination = tmp_path / "candidate"
    import_document(path, destination, author="Example Author", single_source=True)
    project = Project.read(destination)
    panel = html.fragment_fromstring(
        review_panel(prepare_render(project.documents["index.qmd"], project.metadata))
    )
    bodies = panel.xpath('.//article[@class="qr-thread"]//div[contains(concat(" ", @class, " "), " qr-body ")]')
    assert len(bodies) == len(comments)
    assert {node.text_content() for node in bodies} == {comments[0].text}
    assert not panel.xpath(
        './/div[contains(@class, "qr-body")]//em|.//div[contains(@class, "qr-body")]//a'
    )
