"""Word output must retain threaded comments and real acceptance semantics."""

import os
from collections import defaultdict
from dataclasses import replace
from pathlib import Path

import pytest
from lxml import etree

from quarto_review import pandoc
from quarto_review.comparison import compare
from quarto_review.errors import ReviewError
from quarto_review.markup import parse
from quarto_review.metadata import (
    CommentMetadata,
    Reply,
    ReviewMetadata,
    SuggestionMetadata,
)
from quarto_review.rendering import prepare_render
from quarto_review.word.exporter import finish_document
from quarto_review.word.identity import read_identity
from quarto_review.word.importer import import_document
from quarto_review.word.namespaces import NS, tag
from quarto_review.word.package import WordPackage
from quarto_review.word.reader import read_review, visible_text
from quarto_review.word.validation import validate_package


def converted(prepared, path: Path):
    pandoc.run(
        ["--from=markdown-smart", "--to=docx", "--output", str(path)],
        source=prepared.markdown,
    )
    return WordPackage.read(path)


@pytest.mark.integration
def test_native_replacement_comment_and_reply(tmp_path):
    source = "A {=={~~strong~>modest~~}{#s1} effect==}{>>Clarify this.<<}{#c1}.\n"
    metadata = ReviewMetadata("Writer", "2026-01-01T00:00:00Z")
    metadata.suggestions["s1"] = SuggestionMetadata("Writer", metadata.created_at)
    metadata.comments["c1"] = CommentMetadata(
        "Reviewer",
        metadata.created_at,
        replies=(
            Reply("c2", "Done.", "Writer", metadata.created_at, "c1"),
            Reply("c3", "Thanks.", "Reviewer", metadata.created_at, "c2"),
        ),
    )
    prepared = prepare_render(parse(source), metadata)
    output = finish_document(
        converted(prepared, tmp_path / "marked.docx"), prepared, tmp_path
    )
    review = read_review(output)
    root = output.xml("word/document.xml")
    assert visible_text(root, "proposed") == "A modest effect.\n"
    assert visible_text(root, "original") == "A strong effect.\n"
    assert [(r.kind, r.text, r.author) for r in review.revisions] == [
        ("del", "strong", "Writer"),
        ("ins", "modest", "Writer"),
    ]
    assert [c.text for c in review.comments] == ["Clarify this.", "Done.", "Thanks."]
    assert review.comments[2].parent_id == review.comments[1].id
    assert review.comments[2].anchors == review.comments[0].anchors
    assert review.comments[1].parent_id == review.comments[0].id
    assert review.comments[0].anchors[0].text == "strongmodest effect"
    assert review.comments[1].anchors == review.comments[0].anchors
    assert root.xpath(".//w:commentReference/@w:id", namespaces=NS) == [
        comment.id for comment in review.comments
    ]
    settings = output.xml("word/settings.xml")
    assert settings.xpath(
        "./w:compat/w:compatSetting[@w:name='compatibilityMode']/@w:val", namespaces=NS
    ) == ["15"]
    reference = root.find(".//w:commentReference[@w:id='1']", NS)
    reference.getparent().remove(reference)
    output.set_xml("word/document.xml", root)
    with pytest.raises(ReviewError, match="Comment 1 is missing"):
        validate_package(output)
    assert b"QRX" not in output.parts["word/document.xml"]


@pytest.mark.integration
def test_import_export_preserves_crossing_ranges_and_reviewers(word_package, tmp_path):
    incoming = tmp_path / "incoming.docx"
    word_package.write(incoming)
    directory = tmp_path / "source"
    metadata = import_document(incoming, directory, author="Writer")
    prepared = prepare_render(parse((directory / "index.qmd").read_text()), metadata)
    output = finish_document(
        converted(prepared, tmp_path / "marked.docx"), prepared, directory
    )
    before, after = read_review(word_package), read_review(output)
    for left, right in zip(before.comments, after.comments, strict=True):
        assert (
            right.id,
            right.text,
            right.parent_id,
            right.author,
            right.resolved,
        ) == (left.id, left.text, left.parent_id, left.author, left.resolved)
        expected = left.anchors or next(
            comment.anchors
            for comment in before.comments
            if comment.id == left.parent_id
        )
        assert [anchor.text for anchor in right.anchors] == [
            anchor.text for anchor in expected
        ]
    for view in ("original", "proposed"):
        assert visible_text(output.xml("word/document.xml"), view) == visible_text(
            word_package.xml("word/document.xml"), view
        )


@pytest.mark.integration
def test_point_comment_survives_word_qmd_word(tmp_path):
    metadata = ReviewMetadata("Writer", "2026-01-01T00:00:00Z")
    metadata.comments["c1"] = CommentMetadata("Reviewer", metadata.created_at)
    prepared = prepare_render(parse("A point.{>>Explain this.<<}{#c1}\n"), metadata)
    first = finish_document(
        converted(prepared, tmp_path / "marked.docx"), prepared, tmp_path
    )
    source = tmp_path / "first.docx"
    first.write(source)
    directory = tmp_path / "project"
    imported = import_document(source, directory, author="Writer")
    second = prepare_render(parse((directory / "index.qmd").read_text()), imported)
    output = finish_document(
        converted(second, tmp_path / "marked-again.docx"), second, directory
    )
    comments = read_review(output).comments
    assert len(comments) == 1
    assert len(comments[0].anchors) == 1
    assert comments[0].anchors[0].text == ""


@pytest.mark.integration
def test_paragraph_replacement_has_correct_acceptance_views(tmp_path):
    metadata = ReviewMetadata("Writer", "2026-01-01T00:00:00Z")
    metadata.suggestions["s1"] = SuggestionMetadata("Writer", metadata.created_at)
    document = parse(
        "{~~Old first.\n\nOld second.~>New first.\n\nNew second.~~}{#s1}\n"
    )
    prepared = prepare_render(document, metadata)
    output = finish_document(
        converted(prepared, tmp_path / "marked.docx"), prepared, tmp_path
    )
    root = output.xml("word/document.xml")
    assert visible_text(root, "original") == "Old first.\nOld second.\n"
    assert visible_text(root, "proposed") == "New first.\nNew second.\n"
    assert validate_package(output)["revisions"] > 0


@pytest.mark.integration
@pytest.mark.parametrize("status", ["accepted", "rejected"])
def test_comments_on_discarded_wording_keep_an_active_point_anchor(tmp_path, status):
    metadata = ReviewMetadata("Writer", "2026-01-01T00:00:00Z")
    metadata.suggestions["s1"] = SuggestionMetadata(
        "Writer", metadata.created_at, status=status
    )
    metadata.comments["c1"] = CommentMetadata("Reviewer", metadata.created_at)
    source = (
        "A {~~{==strong==}{>>Explain this choice.<<}{#c1}~>modest~~}{#s1} effect.\n"
    )
    if status == "rejected":
        source = (
            "A {~~strong~>{==modest==}{>>Explain this choice.<<}{#c1}~~}{#s1} effect.\n"
        )
    prepared = prepare_render(parse(source), metadata)
    output = finish_document(
        converted(prepared, tmp_path / "marked.docx"), prepared, tmp_path
    )
    assert validate_package(output)["threads"] == 1
    comment = read_review(output).comments[0]
    assert comment.text == "Explain this choice."
    assert comment.anchors[0].text == ""


@pytest.mark.integration
def test_partial_equation_decisions_agree_in_word_and_clean_source(tmp_path):
    metadata = ReviewMetadata("Writer", "2026-01-01T00:00:00Z")
    package = converted(
        prepare_render(parse("$x + y$\n"), metadata), tmp_path / "equation.docx"
    )
    root = package.xml("word/document.xml")
    equation = root.find(".//m:oMath", NS)
    number = 20
    for run in list(equation):
        if "".join(run.itertext()) not in {"x", "y"}:
            continue
        position = equation.index(run)
        equation.remove(run)
        revision = etree.Element(tag("w", "ins"))
        revision.set(tag("w", "id"), str(number))
        revision.set(tag("w", "author"), "Reviewer")
        revision.set(tag("w", "date"), metadata.created_at)
        revision.append(run)
        equation.insert(position, revision)
        number += 1
    assert number == 22
    package.set_xml("word/document.xml", root)
    incoming = tmp_path / "equation.docx"
    package.write(incoming)
    directory = tmp_path / "source"
    imported = import_document(incoming, directory, author="Writer")
    members = next(iter(imported.objects.values())).revisions
    imported.suggestions[members[0]] = replace(
        imported.suggestions[members[0]], status="rejected"
    )
    imported.suggestions[members[1]] = replace(
        imported.suggestions[members[1]], status="accepted"
    )
    document = parse((directory / "index.qmd").read_text())
    clean = prepare_render(document, imported, view="proposed", directory=directory)
    assert "x" not in clean.markdown
    assert "y" in clean.markdown
    prepared = prepare_render(document, imported)
    output = finish_document(
        converted(prepared, tmp_path / "marked.docx"), prepared, directory
    )
    assert "x" not in visible_text(output.xml("word/document.xml"))
    assert "y" in visible_text(output.xml("word/document.xml"))
    assert read_review(output).revisions == ()


@pytest.mark.integration
def test_word_comment_inside_footnote_has_an_explicit_diagnostic(tmp_path):
    metadata = ReviewMetadata("Writer", "2026-01-01T00:00:00Z")
    metadata.comments["c1"] = CommentMetadata("Reviewer", metadata.created_at)
    prepared = prepare_render(
        parse("A note.[^a]\n\n[^a]: {==Text==}{>>Explain this.<<}{#c1}\n"), metadata
    )
    with pytest.raises(ReviewError, match="footnotes.xml"):
        finish_document(
            converted(prepared, tmp_path / "marked.docx"), prepared, tmp_path
        )


@pytest.mark.integration
@pytest.mark.private
def test_private_qmd_word_round_trip_preserves_review_records(tmp_path):
    source = os.environ.get("QUARTO_REVIEW_PRIVATE_DOCX")
    if source is None:
        pytest.skip("Set QUARTO_REVIEW_PRIVATE_DOCX to use a private local fixture")
    original = WordPackage.read(Path(source))
    directory = tmp_path / "project"
    metadata = import_document(Path(source), directory, author="Example Author")
    document = parse((directory / "index.qmd").read_text())
    prepared = prepare_render(document, metadata)
    marked = tmp_path / "marked.docx"
    pandoc.run(
        ["--from=markdown-smart", "--to=docx", "--output", str(marked)],
        source=prepared.markdown,
        directory=directory,
    )
    output = finish_document(WordPackage.read(marked), prepared, directory)
    before, after = read_review(original), read_review(output)
    comments = {comment.id: comment for comment in after.comments}
    assert len(comments) == len(before.comments) == 52
    for comment in before.comments:
        result = comments[comment.id]
        for field in (
            "id",
            "text",
            "author",
            "date",
            "resolved",
            "parent_id",
            "paragraph_id",
            "durable_id",
            "date_utc",
        ):
            assert getattr(result, field) == getattr(comment, field), (
                comment.id,
                field,
            )
        assert [anchor.text for anchor in result.anchors] == [
            anchor.text for anchor in comment.anchors
        ]
    text = defaultdict(str)
    identities = read_identity(output)
    aliases = {
        (item["story"], item["word_id"]): metadata.suggestions[
            item["id"]
        ].provenance.get("word_id", item["word_id"])
        for item in identities["revisions"]
    }
    for revision in after.revisions:
        native_id = aliases[revision.story, revision.id]
        text[(native_id, revision.kind, revision.author, revision.date)] += (
            revision.text
        )
    for revision in before.revisions:
        key = revision.id, revision.kind, revision.author, revision.date
        assert key in text, (revision.id, "missing")
        assert text[key] == revision.text, (revision.id, "text")


@pytest.mark.integration
def test_new_reply_follows_existing_imported_reply(tmp_path):
    metadata = ReviewMetadata("Writer", "2026-01-01T00:00:00Z")
    metadata.comments["c1"] = CommentMetadata(
        "Reviewer",
        metadata.created_at,
        replies=(Reply("r1", "First reply.", "Writer", metadata.created_at, "c1"),),
    )
    prepared = prepare_render(
        parse("A {==claim==}{>>Explain this.<<}{#c1}.\n"), metadata
    )
    first = finish_document(
        converted(prepared, tmp_path / "marked.docx"), prepared, tmp_path
    )
    incoming = tmp_path / "incoming.docx"
    first.write(incoming)
    directory = tmp_path / "imported"
    metadata = import_document(incoming, directory, author="Writer")
    identifier, thread = next(iter(metadata.comments.items()))
    metadata.comments[identifier] = replace(
        thread,
        replies=(
            *thread.replies,
            Reply(
                "new_reply", "Second reply.", "Writer", metadata.created_at, identifier
            ),
        ),
    )
    prepared = prepare_render(parse((directory / "index.qmd").read_text()), metadata)
    second = finish_document(
        converted(prepared, tmp_path / "again.docx"), prepared, directory
    )
    comments = {comment.id: comment.text for comment in read_review(second).comments}
    ids = second.xml("word/document.xml").xpath(
        ".//w:commentReference/@w:id", namespaces=NS
    )
    assert [comments[identifier] for identifier in ids] == [
        "Explain this.",
        "First reply.",
        "Second reply.",
    ]


@pytest.mark.integration
@pytest.mark.parametrize(
    ("before_anchor", "after_anchor"),
    [
        ("", "[]{#ref-example .anchor}"),
        ("[]{#previous .anchor}", "[]{#ref-example .anchor}"),
        ("[]{#previous .anchor}", ""),
    ],
)
def test_navigation_anchor_edits_preserve_word_review(
    tmp_path, before_anchor, after_anchor
):
    metadata = ReviewMetadata("Writer", "2026-01-01T00:00:00Z")
    metadata.suggestions["s1"] = SuggestionMetadata("Reviewer", metadata.created_at)
    metadata.comments["c1"] = CommentMetadata(
        "Reviewer", metadata.created_at, status="resolved",
        replies=(Reply("r1", "Done.", "Writer", metadata.created_at, "c1"),),
    )
    prose = "A {=={~~old~>better~~}{#s1} claim==}{>>Explain.<<}{#c1}.\n\nA strong result.\n"
    before = parse(before_anchor + prose)
    after = parse(after_anchor + prose.replace("strong", "modest"))
    result = compare(
        after, before, metadata,
        reference_id="test-round", date="2026-01-02T00:00:00Z",
    )
    prepared = prepare_render(result.document, result.metadata)
    output = finish_document(
        converted(prepared, tmp_path / "anchored.docx"), prepared, tmp_path
    )
    assert len(result.automatic_ids) == 1
    assert validate_package(output)["threads"] == 1
    root = output.xml("word/document.xml")
    assert visible_text(root, "original") == "A old claim.\nA strong result.\n"
    assert visible_text(root, "proposed") == "A better claim.\nA modest result.\n"
    bookmarks = root.xpath(".//w:bookmarkStart/@w:name", namespaces=NS)
    assert ("ref-example" in bookmarks) == bool(after_anchor)
    assert "previous" not in bookmarks
    review = read_review(output)
    assert [(r.kind, r.text, r.author) for r in review.revisions] == [
        ("del", "old", "Reviewer"), ("ins", "better", "Reviewer"),
        ("del", "strong", "Writer"), ("ins", "modest", "Writer"),
    ]
    assert [c.text for c in review.comments] == ["Explain.", "Done."]
    assert review.comments[0].resolved
    assert review.comments[1].parent_id == review.comments[0].id
    assert review.comments[0].anchors[0].text == "oldbetter claim"
