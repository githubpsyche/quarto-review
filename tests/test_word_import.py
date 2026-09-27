"""Import review bodies and boundaries before a converter can discard them."""

import os
from pathlib import Path

import pytest

from quarto_review.errors import ReviewError
from quarto_review.markup import Boundary, Comment, parse, project, walk
from quarto_review.metadata import ReviewMetadata
from quarto_review.word import WordPackage, read_review
from quarto_review.word.importer import import_document, prepare_import, restore_source


@pytest.mark.integration
def test_word_to_qmd_retains_comments_replies_and_revisions(word_package, tmp_path):
    original = tmp_path / "reviewed.docx"
    word_package.write(original)
    original_bytes = original.read_bytes()
    destination = tmp_path / "manuscript"
    metadata = import_document(original, destination, author="Example Author")
    document = parse((destination / "index.qmd").read_text())
    assert isinstance(document.annotations()["c0"], Comment)
    assert (
        document.annotations()["c0"].body == "Clarify the claim.\nExplain the evidence."
    )
    assert set(metadata.comments) == {"c0", "c2"}
    assert metadata.comments["c0"].replies[0].body == "I have revised the wording."
    assert metadata.comments["c0"].replies[0].parent_id == "c0"
    assert metadata.comments["c2"].status == "resolved"
    assert "An old modest claim." in project(document.nodes)
    assert "An old strong claim." in project(document.nodes, "original")
    assert len(metadata.suggestions) == 2
    assert sum(isinstance(n, Boundary) for n in walk(document.nodes)) == 4
    assert ReviewMetadata.read(destination / "review.yml") == metadata
    assert (destination / "index.qmd").read_bytes() == (
        destination / "review/reference/index.qmd"
    ).read_bytes()
    assert original.read_bytes() == original_bytes


def test_missing_boundary_stops_conversion(word_package):
    prepared = prepare_import(word_package, author="Author", archive="source.docx")
    with pytest.raises(ReviewError, match="Conversion changed review boundaries"):
        restore_source("Text with missing comments.", prepared)


@pytest.mark.integration
def test_import_does_not_replace_an_existing_project(word_package, tmp_path):
    source = tmp_path / "source.docx"
    word_package.write(source)
    destination = tmp_path / "project"
    destination.mkdir()
    existing = destination / "index.qmd"
    existing.write_text("Keep this draft.")
    with pytest.raises(ReviewError, match="already exists"):
        import_document(source, destination, author="Author")
    assert existing.read_text() == "Keep this draft."


@pytest.mark.integration
@pytest.mark.private
def test_private_word_to_qmd_retains_every_review_record(tmp_path):
    source = os.environ.get("QUARTO_REVIEW_PRIVATE_DOCX")
    if source is None:
        pytest.skip("Set QUARTO_REVIEW_PRIVATE_DOCX to use a private local fixture")
    original = read_review(WordPackage.read(Path(source)))
    destination = tmp_path / "private-source"
    metadata = import_document(Path(source), destination, author="Example Author")
    document = parse((destination / "index.qmd").read_text())
    assert len(metadata.comments) == 47
    assert sum(len(comment.replies) for comment in metadata.comments.values()) == 5
    assert len(metadata.suggestions) == 293
    for comment in original.comments:
        identifier = f"c{comment.id}"
        if comment.parent_id is None:
            assert document.annotations()[identifier].body == comment.text
            assert metadata.comments[identifier].author == comment.author
            assert metadata.comments[identifier].date == comment.date
        else:
            replies = [
                reply
                for thread in metadata.comments.values()
                for reply in thread.replies
            ]
            reply = next(reply for reply in replies if reply.id == identifier)
            assert reply.body == comment.text
            assert reply.author == comment.author
            assert reply.parent_id == f"c{comment.parent_id}"


@pytest.mark.integration
def test_import_keeps_bookmarks_between_paragraphs(word_package, tmp_path):
    from lxml import etree

    from quarto_review.word.namespaces import NS, tag

    root = word_package.xml("word/document.xml")
    body = root.find("w:body", NS)
    paragraph = body.find("w:p", NS)
    position = body.index(paragraph)
    start = etree.Element(
        tag("w", "bookmarkStart"),
        {tag("w", "id"): "900", tag("w", "name"): "eq-preserved"},
    )
    end = etree.Element(tag("w", "bookmarkEnd"), {tag("w", "id"): "900"})
    body.insert(position, start)
    body.insert(position + 2, end)
    link = etree.SubElement(
        body.findall("w:p", NS)[1],
        tag("w", "hyperlink"),
        {tag("w", "anchor"): "eq-preserved"},
    )
    run = etree.SubElement(link, tag("w", "r"))
    etree.SubElement(run, tag("w", "t")).text = "Go to equation"
    word_package.set_xml("word/document.xml", root)
    original = tmp_path / "source.docx"
    word_package.write(original)
    original_bytes = original.read_bytes()
    destination = tmp_path / "project"
    import_document(original, destination, author="Example Author")
    source = (destination / "index.qmd").read_text()
    assert "{#eq-preserved" in source
    assert original.read_bytes() == original_bytes
