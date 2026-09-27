"""Imported comment hyperlinks and lists keep their package dependencies."""

from dataclasses import replace

import pytest
from lxml import etree

from quarto_review import pandoc
from quarto_review.markup import parse
from quarto_review.metadata import CommentMetadata, ReviewMetadata
from quarto_review.rendering import prepare_render
from quarto_review.word.comments import write_comments
from quarto_review.word.exporter import finish_document
from quarto_review.word.importer import import_document
from quarto_review.word.namespaces import NS, tag
from quarto_review.word.package import WordPackage
from quarto_review.word.reader import read_review
from quarto_review.word.relationships import internal_target
from quarto_review.word.validation import validate_package


@pytest.mark.integration
def test_comment_hyperlink_style_and_numbering_survive_round_trip(tmp_path):
    metadata = ReviewMetadata("Writer", "2026-01-01T00:00:00Z")
    metadata.comments["c1"] = CommentMetadata("Reviewer", metadata.created_at)
    prepared = prepare_render(
        parse("A {==claim==}{>>See the study.<<}{#c1}.\n"), metadata
    )
    marked = tmp_path / "marked.docx"
    pandoc.run(
        ["--from=markdown-smart", "--to=docx", "--output", str(marked)],
        source=prepared.markdown,
    )
    package = finish_document(WordPackage.read(marked), prepared, tmp_path)
    root = package.xml("word/comments.xml")
    paragraph = root.find("./w:comment/w:p", NS)
    properties = paragraph.find("./w:pPr", NS)
    if properties is None:
        properties = etree.Element(tag("w", "pPr"))
        paragraph.insert(0, properties)
    style = etree.SubElement(properties, tag("w", "pStyle"))
    style.set(tag("w", "val"), "ReviewList")
    num_properties = etree.SubElement(properties, tag("w", "numPr"))
    level = etree.SubElement(num_properties, tag("w", "ilvl"))
    level.set(tag("w", "val"), "0")
    number = etree.SubElement(num_properties, tag("w", "numId"))
    number.set(tag("w", "val"), "87")
    hyperlink = etree.SubElement(paragraph, tag("w", "hyperlink"))
    hyperlink.set(tag("r", "id"), "rIdStudy")
    for run in list(paragraph.findall("./w:r", NS)):
        paragraph.remove(run)
        hyperlink.append(run)
    comment = read_review(package).comments[0]
    write_comments(
        package, [replace(comment, xml=etree.tostring(root[0], encoding="unicode"))]
    )
    relations = etree.Element(tag("pr", "Relationships"), nsmap={None: NS["pr"]})
    etree.SubElement(
        relations,
        tag("pr", "Relationship"),
        Id="rIdStudy",
        Type=NS["r"] + "/hyperlink",
        Target="https://example.org/study",
        TargetMode="External",
    )
    package.set_xml("word/_rels/comments.xml.rels", relations)
    styles = package.xml("word/styles.xml")
    style = etree.SubElement(styles, tag("w", "style"))
    style.set(tag("w", "type"), "paragraph")
    style.set(tag("w", "styleId"), "ReviewList")
    name = etree.SubElement(style, tag("w", "name"))
    name.set(tag("w", "val"), "Review list")
    package.set_xml("word/styles.xml", styles)
    numbering = package.xml("word/numbering.xml")
    abstract = etree.Element(tag("w", "abstractNum"))
    abstract.set(tag("w", "abstractNumId"), "87")
    level = etree.SubElement(abstract, tag("w", "lvl"))
    level.set(tag("w", "ilvl"), "0")
    for kind, value in (("start", "1"), ("numFmt", "decimal"), ("lvlText", "%1.")):
        item = etree.SubElement(level, tag("w", kind))
        item.set(tag("w", "val"), value)
    numbering.insert(0, abstract)
    number = etree.SubElement(numbering, tag("w", "num"))
    number.set(tag("w", "numId"), "87")
    reference = etree.SubElement(number, tag("w", "abstractNumId"))
    reference.set(tag("w", "val"), "87")
    package.set_xml("word/numbering.xml", numbering)
    incoming = tmp_path / "incoming.docx"
    package.write(incoming)
    directory = tmp_path / "project"
    imported = import_document(incoming, directory, author="Writer")
    prepared = prepare_render(parse((directory / "index.qmd").read_text()), imported)
    pandoc.run(
        ["--from=markdown-smart", "--to=docx", "--output", str(marked)],
        source=prepared.markdown,
    )
    output = finish_document(WordPackage.read(marked), prepared, directory)
    assert validate_package(output)["threads"] == 1
    assert read_review(output).comments[0].text == "See the study."
    root = output.xml("word/comments.xml")
    native_id = root.find(".//w:hyperlink", NS).get(tag("r", "id"))
    assert any(
        item.get("Id") == native_id
        and item.get("Target") == "https://example.org/study"
        for item in output.xml("word/_rels/comments.xml.rels")
    )
    style_id = root.find(".//w:pStyle", NS).get(tag("w", "val"))
    assert any(
        item.get(tag("w", "styleId")) == style_id
        for item in output.xml("word/styles.xml")
    )
    num_id = root.find(".//w:numId", NS).get(tag("w", "val"))
    assert any(
        item.get(tag("w", "numId")) == num_id
        for item in output.xml("word/numbering.xml")
    )
    output.write(tmp_path / "roundtrip.docx")


def test_absolute_and_escaped_relationship_paths_are_package_relative():
    assert (
        internal_target("word/document.xml", "/word/media/a%20b.png")
        == "word/media/a b.png"
    )
