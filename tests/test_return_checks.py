"""Returned content outside Markdown must not disappear during reconciliation."""

from lxml import etree

from quarto_review.word.namespaces import NS, tag
from quarto_review.word.package import WordPackage
from quarto_review.word.return_checks import unsupported_changes


def test_unchanged_package_and_relationship_renumbering_are_not_edits(word_package):
    package = WordPackage(dict(word_package.parts))
    assert unsupported_changes(word_package, package) == []
    root = package.xml("word/document.xml")
    run = root.find(".//w:r", NS)
    drawing = etree.SubElement(run, tag("w", "drawing"))
    picture = etree.SubElement(drawing, "picture")
    picture.set(tag("r", "embed"), "rIdImage")
    package.set_xml("word/document.xml", root)
    name = "word/_rels/document.xml.rels"
    relations = package.xml(name)
    etree.SubElement(
        relations,
        tag("pr", "Relationship"),
        Id="rIdImage",
        Type=NS["r"] + "/image",
        Target="media/retained.bin",
    )
    package.set_xml(name, relations)
    revised = WordPackage(dict(package.parts))
    root = revised.xml("word/document.xml")
    root.find(".//picture").set(tag("r", "embed"), "rId99")
    revised.set_xml("word/document.xml", root)
    relations = revised.xml(name)
    for node in relations:
        if node.get("Id") == "rIdImage":
            node.set("Id", "rId99")
    revised.set_xml(name, relations)
    assert unsupported_changes(package, revised) == []
    revised.parts["word/media/retained.bin"] = b"Changed image content"
    assert unsupported_changes(package, revised)[0]["kind"] == "unsupported-content"


def test_new_header_is_retained_as_a_conflict(word_package):
    returned = WordPackage(dict(word_package.parts))
    returned.parts["word/header1.xml"] = (
        f'<w:hdr xmlns:w="{NS["w"]}"><w:p><w:r><w:t>Changed header</w:t></w:r></w:p></w:hdr>'.encode()
    )
    assert unsupported_changes(word_package, returned)[0]["id"] == "headers"
