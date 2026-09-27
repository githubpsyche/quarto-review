"""Preserve review content, attribution, ranges, and native reply relationships."""

import os
from collections import Counter
from dataclasses import replace
from pathlib import Path

import pytest
from lxml import etree

from quarto_review.errors import ReviewError
from quarto_review.word.comments import write_comments
from quarto_review.word.namespaces import COMMENT_PARTS, NS, tag
from quarto_review.word.package import WordPackage
from quarto_review.word.reader import read_review, visible_text


def test_overlapping_ranges_and_reply_without_own_range(word_package):
    review = read_review(word_package)
    comments = {comment.id: comment for comment in review.comments}
    assert comments["0"].text == "Clarify the claim.\nExplain the evidence."
    assert comments["0"].anchors[0].text == "old strong modest"
    assert comments["2"].anchors[0].text == " strong modest claim"
    assert comments["1"].parent_id == "0"
    assert comments["1"].anchors == ()
    assert comments["2"].resolved


def test_revision_views_and_authors(word_package):
    root = word_package.xml("word/document.xml")
    assert visible_text(root, "proposed") == "An old modest claim.\nSecond paragraph.\n"
    assert visible_text(root, "original") == "An old strong claim.\nSecond paragraph.\n"
    review = read_review(word_package)
    assert [(r.kind, r.text, r.author) for r in review.revisions] == [
        ("del", " strong", "A. Reviewer"),
        ("ins", " modest", "A. Reviewer"),
    ]


def test_native_thread_roundtrip_preserves_records_and_other_parts(
    word_package, tmp_path
):
    before = read_review(word_package)
    original_parts = dict(word_package.parts)
    write_comments(word_package, before.comments)
    path = tmp_path / "roundtrip.docx"
    word_package.write(path)
    reopened = WordPackage.read(path)
    after = read_review(reopened)
    assert [replace(c, xml=None) for c in after.comments] == [
        replace(c, xml=None) for c in before.comments
    ]
    assert after.revisions == before.revisions
    assert after.stories == before.stories
    changed_parts = {value[0] for value in COMMENT_PARTS.values()} | {
        "word/_rels/document.xml.rels",
        "[Content_Types].xml",
    }
    for name, data in original_parts.items():
        if name not in changed_parts:
            assert reopened.parts[name] == data


def test_reply_edit_resolve_and_reopen(word_package):
    before = read_review(word_package)
    changed = [
        replace(c, resolved=True)
        if c.id == "0"
        else replace(c, text="New reply.\nSecond line.")
        if c.id == "1"
        else c
        for c in before.comments
    ]
    write_comments(word_package, changed)
    after = {c.id: c for c in read_review(word_package).comments}
    assert after["0"].resolved
    assert after["1"].text == "New reply.\nSecond line."
    assert after["1"].parent_id == "0"
    assert after["1"].author == "B. Author"
    assert after["0"].anchors == before.comments[0].anchors
    write_comments(word_package, [replace(c, resolved=False) for c in after.values()])
    assert not any(c.resolved for c in read_review(word_package).comments)


def test_comment_extension_uses_last_paragraph(word_package):
    root = word_package.xml("word/comments.xml")
    paragraphs = root[0].findall("./w:p", NS)
    paragraphs[0].set(tag("w14", "paraId"), "12345678")
    word_package.set_xml("word/comments.xml", root)
    assert read_review(word_package).comments[1].parent_id == "0"


def test_empty_comment_is_not_dropped(word_package):
    comments = list(read_review(word_package).comments)
    comments[0] = replace(comments[0], text="")
    write_comments(word_package, comments)
    assert read_review(word_package).comments[0].text == ""


def test_unknown_extension_attributes_survive(word_package):
    path = "word/commentsExtensible.xml"
    root = word_package.xml(path)
    root[0].set("{urn:future-word}retained", "yes")
    word_package.set_xml(path, root)
    write_comments(word_package, read_review(word_package).comments)
    assert word_package.xml(path)[0].get("{urn:future-word}retained") == "yes"


def test_broken_range_is_reported(word_package):
    root = word_package.xml("word/document.xml")
    start = root.find(".//w:commentRangeStart", NS)
    start.getparent().remove(start)
    word_package.set_xml("word/document.xml", root)
    with pytest.raises(ReviewError, match="ends without a start"):
        read_review(word_package)


def test_cyclic_reply_is_rejected(word_package):
    comments = list(read_review(word_package).comments)
    comments[0] = replace(comments[0], parent_id="1")
    with pytest.raises(ReviewError, match="cyclic reply"):
        write_comments(word_package, comments)


def test_footnote_anchor_and_unicode(word_package):
    root = etree.fromstring(
        f'''<w:footnotes xmlns:w="{NS["w"]}"><w:footnote w:id="1"><w:p>
      <w:commentRangeStart w:id="2"/><w:r><w:t>café 🧠</w:t></w:r>
      <w:commentRangeEnd w:id="2"/><w:r><w:commentReference w:id="2"/></w:r>
    </w:p></w:footnote></w:footnotes>'''.encode()
    )
    word_package.set_xml("word/footnotes.xml", root)
    anchors = read_review(word_package).comments[2].anchors
    assert anchors[-1].story == "word/footnotes.xml"
    assert anchors[-1].text == "café 🧠"


@pytest.mark.private
def test_private_native_review_roundtrip(tmp_path):
    source = os.environ.get("QUARTO_REVIEW_PRIVATE_DOCX")
    if source is None:
        pytest.skip("Set QUARTO_REVIEW_PRIVATE_DOCX to test a private local fixture")
    path = Path(source)
    original = path.read_bytes()
    package = WordPackage.read(path)
    before = read_review(package)
    assert len(before.comments) == 52
    assert sum(c.parent_id is not None for c in before.comments) == 5
    assert Counter(r.kind for r in before.revisions) == {
        "ins": 227,
        "del": 52,
        "rPrChange": 7,
        "pPrChange": 3,
        "conflictIns": 4,
    }
    write_comments(package, before.comments)
    output = tmp_path / "private-roundtrip.docx"
    package.write(output)
    after = read_review(WordPackage.read(output))
    assert [replace(c, xml=None) for c in after.comments] == [
        replace(c, xml=None) for c in before.comments
    ]
    assert before.revisions == after.revisions
    assert before.stories == after.stories
    assert path.read_bytes() == original
