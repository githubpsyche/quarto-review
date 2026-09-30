"""Settled prose can leave QMD without changing the next Word review round."""

from pathlib import Path

import pytest

from quarto_review.compaction import compact, plan
from quarto_review.errors import ReviewError
from quarto_review.markup import project
from quarto_review.project import Project
from quarto_review.source import read

HEADER = """---
title: Example
review:
  schema: 2
  author: A
  authors:
    A: Example Author
    R: Example Reviewer
---
"""
THREAD = """:::: {.review-thread #c1 .resolved by=R at=2026-01-01}
Please clarify the **claim**.

::: {.reply #r1 by=A at=2026-01-02}
I have clarified it.
:::
::::
"""


def setup(tmp_path, source, reference=None):
    (tmp_path / "index.qmd").write_text(source)
    (tmp_path / "reference.qmd").write_text(
        reference if reference is not None else source
    )
    return Project.read(tmp_path)


def test_retire_title_history_preserves_pending_title_and_provenance(tmp_path):
    pending = "{~~Old title~>New title~~}{#s1 by=A at=2026-01-02}"
    history = "{++ unwanted qualification++}{#s2 .rejected by=R at=2026-01-01}"
    history += '<!-- review-data: {"provenance":{"word_id":"2","kind":"ins"}} -->'
    source = HEADER + "\n# " + pending + history + "\n\nA [claim]{#c1}.\n\n" + THREAD
    setup(tmp_path, source)
    before = Project.read(tmp_path).metadata
    result = compact(tmp_path)
    current = Project.read(tmp_path)
    assert result == {
        "removed": ["s2"],
        "retained": {},
        "dry_run": False,
        "changed": True,
    }
    assert current.source.text == source.replace(history, "")
    assert current.metadata.suggestions == {"s1": before.suggestions["s1"]}
    assert current.metadata.comments == before.comments
    assert current.ordinary_changes()["index.qmd"].automatic_ids == ()
    assert compact(tmp_path)["changed"] is False


@pytest.mark.parametrize("state, expected", [("accepted", "new"), ("rejected", "old")])
@pytest.mark.parametrize("in_reference", [True, False])
def test_decision_does_not_resurface_or_accept_other_work(
    tmp_path, state, expected, in_reference
):
    change = "{~~old~>new~~}{#s1 by=R}"
    original = HEADER + f"\nAn {change} claim.\n\nAn unrelated original paragraph.\n"
    reference = original if in_reference else original.replace(change, "old")
    current = original.replace("#s1 by=R", f"#s1 .{state} by=R").replace(
        "unrelated original", "unrelated revised"
    )
    setup(tmp_path, current, reference)
    compact(tmp_path)
    manuscript = Project.read(tmp_path)
    comparison = manuscript.ordinary_changes()["index.qmd"]
    assert f"An {expected} claim." in manuscript.source.text
    assert "unrelated revised" in manuscript.source.text
    assert "unrelated original" in (tmp_path / "reference.qmd").read_text()
    assert len(comparison.automatic_ids) == 1
    node = comparison.document.annotations()[comparison.automatic_ids[0]]
    assert (project(node.before), project(node.after)) == ("original", "revised")


def test_can_edit_retired_wording_normally_and_track_again(tmp_path):
    manuscript = setup(tmp_path, HEADER + "\nA {~~large~>small~~}{#s1 by=R} effect.\n")
    manuscript.decide("s1", "accept")
    compact(tmp_path)
    path = tmp_path / "index.qmd"
    path.write_text(path.read_text().replace("small", "modest"))
    comparison = Project.read(tmp_path).ordinary_changes()["index.qmd"]
    node = comparison.document.annotations()[comparison.automatic_ids[0]]
    assert (project(node.before), project(node.after)) == ("small", "modest")


@pytest.mark.parametrize(
    "kind, expected",
    [
        (
            "{~~[large]{#c1}~>small~~}{#s1 .accepted by=A}",
            "[]{#c1-start}[]{#c1-end}small",
        ),
        (
            "{~~large~>[small]{#c1}~~}{#s1 .rejected by=A}",
            "large[]{#c1-start}[]{#c1-end}",
        ),
        ("[A {--large--}{#s1 .accepted by=A} effect]{#c1}", "[A  effect]{#c1}"),
        (
            "{~~[]{#c1-start}large~>small~~}{#s1 .accepted by=A} effect[]{#c1-end}",
            "[]{#c1-start}small effect[]{#c1-end}",
        ),
    ],
)
def test_comment_ranges_and_resolved_replies_survive(tmp_path, kind, expected):
    source = HEADER + "\n" + kind + ".\n\n" + THREAD
    setup(tmp_path, source)
    result = compact(tmp_path)
    current = Project.read(tmp_path)
    assert result["removed"] == ["s1"]
    assert current.source.text == HEADER + "\n" + expected + ".\n\n" + THREAD
    assert current.metadata.comments["c1"].status == "resolved"
    assert current.metadata.comments["c1"].replies[0].id == "r1"


def test_retire_child_preserves_pending_parent_syntax(tmp_path):
    text = (
        HEADER + "\n{++A {~~large~>small~~}{#s1 .rejected by=R} effect.++}{#s2 by=A}\n"
    )
    setup(tmp_path, text)
    compact(tmp_path)
    assert (
        tmp_path / "index.qmd"
    ).read_text() == HEADER + "\n{++A large effect.++}{#s2 by=A}\n"


def test_keep_parent_if_discarding_it_would_lose_pending_child(tmp_path):
    text = (
        HEADER + "\n{--A {~~large~>small~~}{#s1 by=R} effect.--}{#s2 .accepted by=A}\n"
    )
    setup(tmp_path, text)
    result = compact(tmp_path)
    assert result["removed"] == []
    assert "s1" in result["retained"]["s2"]
    assert (tmp_path / "index.qmd").read_text() == text


def test_compaction_retains_native_property_decision(tmp_path):
    native = "[]{#f1-start}Formatted text[]{#f1-end}{~~~>~~}{#f1 .rejected by=R}"
    native += '<!-- review-data: {"provenance":{"kind":"rPrChange"}} -->'
    text = HEADER + "\n" + native + " {~~old~>new~~}{#s1 .accepted by=A}.\n"
    setup(tmp_path, text)
    result = compact(tmp_path)
    assert result["removed"] == ["s1"]
    assert "native Word" in result["retained"]["f1"]
    assert native in (tmp_path / "index.qmd").read_text()


def test_dry_run_and_compiled_reference_fail_without_writes(tmp_path):
    text = HEADER + "\n{~~old~>new~~}{#s1 .accepted by=A}.\n"
    setup(tmp_path, text)
    assert compact(tmp_path, dry_run=True)["removed"] == ["s1"]
    assert (tmp_path / "index.qmd").read_text() == text
    assert (tmp_path / "reference.qmd").read_text() == text
    reference = read(text)
    reference.settings["compiled"] = {"html": "executed Markdown"}
    with pytest.raises(ReviewError, match="executed references"):
        plan(read(text), reference)


def test_second_write_failure_restores_reference(tmp_path, monkeypatch):
    import quarto_review.compaction as module

    text = HEADER + "\n{~~old~>new~~}{#s1 .accepted by=A}.\n"
    setup(tmp_path, text)
    original = module.write_text

    def fail_current(path, content):
        if path.name == "index.qmd":
            raise OSError("disk error")
        original(path, content)

    monkeypatch.setattr(module, "write_text", fail_current)
    with pytest.raises(OSError, match="disk error"):
        compact(tmp_path)
    assert (tmp_path / "index.qmd").read_text() == text
    assert (tmp_path / "reference.qmd").read_text() == text


def test_concurrent_edit_is_preserved(tmp_path, monkeypatch):
    import quarto_review.compaction as module

    text = HEADER + "\n{~~old~>new~~}{#s1 .accepted by=A}.\n"
    setup(tmp_path, text)
    original = module.write_text

    def interleave(path, content):
        original(path, content)
        if path.name == "reference.qmd":
            (tmp_path / "index.qmd").write_text(text + "\nNew work.\n")

    monkeypatch.setattr(module, "write_text", interleave)
    with pytest.raises(ReviewError, match="source changed"):
        compact(tmp_path)
    assert (tmp_path / "index.qmd").read_text() == text + "\nNew work.\n"
    assert (tmp_path / "reference.qmd").read_text() == text


@pytest.mark.integration
def test_native_word_export_matches_before_cleanup(word_package, tmp_path):
    from quarto_review import pandoc
    from quarto_review.rendering import prepare_render
    from quarto_review.word.exporter import finish_document
    from quarto_review.word.importer import import_document
    from quarto_review.word.package import WordPackage
    from quarto_review.word.reader import read_review, visible_text

    incoming = tmp_path / "input.docx"
    word_package.write(incoming)
    directory = tmp_path / "project"
    import_document(incoming, directory, author="Example Author", single_source=True)
    manuscript = Project.read(directory)
    first, pending = tuple(manuscript.metadata.suggestions)
    manuscript.decide(first, "accept")
    archives = {str(p): p.read_bytes() for p in directory.rglob("*.docx")}
    pending_record = manuscript.metadata.suggestions[pending]

    def export():
        current = Project.read(directory).ordinary_changes()["index.qmd"]
        prepared = prepare_render(current.document, current.metadata)
        output = tmp_path / "rendered.docx"
        pandoc.run(
            ["--from=markdown-smart", "--to=docx", "--output", str(output)],
            source=prepared.markdown,
        )
        return finish_document(WordPackage.read(output), prepared, directory)

    before = export()
    compact(directory)
    after = export()
    for view in ("original", "proposed"):
        assert visible_text(before.xml("word/document.xml"), view) == visible_text(
            after.xml("word/document.xml"), view
        )
    old, new = read_review(before), read_review(after)
    assert [(r.id, r.kind, r.text, r.author, r.date) for r in new.revisions] == [
        (r.id, r.kind, r.text, r.author, r.date) for r in old.revisions
    ]
    assert [
        (
            c.id,
            c.text,
            c.author,
            c.date,
            c.parent_id,
            c.resolved,
            [a.text for a in c.anchors],
        )
        for c in new.comments
    ] == [
        (
            c.id,
            c.text,
            c.author,
            c.date,
            c.parent_id,
            c.resolved,
            [a.text for a in c.anchors],
        )
        for c in old.comments
    ]
    assert Project.read(directory).metadata.suggestions == {pending: pending_record}
    assert all(Path(name).read_bytes() == data for name, data in archives.items())


@pytest.mark.integration
@pytest.mark.parametrize("citation_decision", ["accept", "reject"])
def test_citation_cleanup_preserves_reviewed_entries_and_newer_edits(
    tmp_path, citation_decision
):
    import os
    import shutil
    import subprocess
    import sys

    from quarto_review.quarto import enable
    from quarto_review.word.package import WordPackage
    from quarto_review.word.reader import read_review, visible_text
    from quarto_review.word.validation import validate_package

    fixtures = Path(__file__).parent / "fixtures"
    source = (fixtures / "native-word-citations.qmd").read_text()
    setup(tmp_path, source)
    bib = tmp_path / "native-word-citations.bib"
    shutil.copyfile(fixtures / bib.name, bib)
    bibliography = bib.read_bytes()
    manuscript = Project.read(tmp_path)
    manuscript.decide("s1", "accept")
    Project.read(tmp_path).decide("s2", citation_decision)
    manuscript = Project.read(tmp_path)
    manuscript.reply("c2", "The second reference is correct.")
    manuscript.decide("c2", "resolve")
    path = tmp_path / "index.qmd"
    path.write_text(
        path.read_text().replace(
            "The follow-up was brief.", "The follow-up lasted two days."
        )
    )
    enable(tmp_path)
    environment = {
        **os.environ,
        "PATH": str(Path(sys.executable).parent) + os.pathsep + os.environ["PATH"],
    }
    for name in ("QUARTO_PANDOC", "QUARTO_REVIEW_PROJECT", "QUARTO_REVIEW_COMMAND"):
        environment.pop(name, None)

    def export():
        result = subprocess.run(
            ["quarto", "render", "index.qmd", "--to", "all", "--quiet"],
            cwd=tmp_path,
            env=environment,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        package = WordPackage.read(tmp_path / "index.docx")
        validate_package(package)
        review = read_review(package)
        return (
            [
                visible_text(package.xml("word/document.xml"), view)
                for view in ("original", "proposed")
            ],
            [(r.id, r.kind, r.text, r.author) for r in review.revisions],
            [
                (
                    c.id,
                    c.text,
                    c.author,
                    c.date,
                    c.parent_id,
                    c.resolved,
                    [a.text for a in c.anchors],
                )
                for c in review.comments
            ],
        )

    before = export()
    assert compact(tmp_path)["removed"] == ["s0", "s1", "s2"]
    assert export() == before
    final = Project.read(tmp_path)
    assert not final.metadata.suggestions
    assert final.ordinary_changes()["index.qmd"].automatic_ids
    assert "The follow-up was brief." in (tmp_path / "reference.qmd").read_text()
    assert "The follow-up lasted two days." in final.source.text
    assert ("@smith2022" in final.source.text) == (citation_decision == "accept")
    assert "A reviewed reference entry" in final.source.text
    assert bib.read_bytes() == bibliography
    member = next(c for c in before[2] if c[1] == "Please check the second reference.")
    assert member[5] and member[6] == ["Smith 2021"]


def test_cli_reports_cleanup_and_dry_run(tmp_path, capsys):
    import json

    from quarto_review.cli import main

    text = HEADER + "\n{~~old~>new~~}{#s1 .accepted by=A}.\n"
    setup(tmp_path, text)
    assert main(["compact", "--project", str(tmp_path), "--dry-run"]) == 0
    preview = json.loads(capsys.readouterr().out)
    assert preview["removed"] == ["s1"] and preview["changed"] is False
    assert (tmp_path / "index.qmd").read_text() == text
    assert main(["compact", "--project", str(tmp_path)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["changed"] is True
    assert (tmp_path / "index.qmd").read_text() == HEADER + "\nnew.\n"


@pytest.mark.integration
def test_html_only_keeps_pending_cards_and_resolved_discussion_after_cleanup(tmp_path):
    from lxml import html

    from quarto_review.html import review_panel
    from quarto_review.rendering import prepare_render

    text = (
        HEADER
        + "\n{--Draft note.--}{#s1 .accepted by=A}\n\n[A {~~large~>small~~}{#s2 by=R} effect]{#c1}.\n\n"
        + THREAD
    )
    setup(tmp_path, text)
    compact(tmp_path)
    model = Project.read(tmp_path)
    prepared = prepare_render(
        model.source.document, model.metadata, native_objects=False
    )
    panel = html.fromstring(review_panel(prepared))
    assert not panel.xpath('//*[@id="qr-suggestion-s1"]')
    assert "s1" not in prepared.suggestions
    assert "Draft note." not in prepared.markdown
    assert panel.get_element_by_id("qr-suggestion-s2").get("data-status") == "pending"
    assert panel.get_element_by_id("qr-thread-c1").get("data-status") == "resolved"
    assert (
        "I have clarified it." in panel.get_element_by_id("qr-reply-r1").text_content()
    )


@pytest.mark.integration
@pytest.mark.parametrize("decision, bold", [("accept", True), ("reject", False)])
def test_settled_native_formatting_still_exports_after_prose_cleanup(
    word_package, tmp_path, decision, bold
):
    from lxml import etree

    from quarto_review import pandoc
    from quarto_review.rendering import prepare_render
    from quarto_review.word.exporter import finish_document
    from quarto_review.word.importer import import_document
    from quarto_review.word.namespaces import NS, tag
    from quarto_review.word.package import WordPackage
    from quarto_review.word.reader import read_review

    root = word_package.xml("word/document.xml")
    run = root.find('.//w:r[w:t="old"]', NS)
    props = etree.Element(tag("w", "rPr"))
    etree.SubElement(props, tag("w", "b"))
    revision = etree.SubElement(props, tag("w", "rPrChange"))
    revision.set(tag("w", "id"), "30")
    revision.set(tag("w", "author"), "A. Reviewer")
    revision.set(tag("w", "date"), "2026-01-02T09:00:00Z")
    etree.SubElement(revision, tag("w", "rPr"))
    run.insert(0, props)
    word_package.set_xml("word/document.xml", root)
    incoming = tmp_path / "formatting.docx"
    word_package.write(incoming)
    directory = tmp_path / "project"
    import_document(incoming, directory, author="Example Author", single_source=True)
    model = Project.read(directory)
    native = next(
        key
        for key, item in model.metadata.suggestions.items()
        if item.provenance.get("kind") == "rPrChange"
    )
    prose = next(
        key
        for key, item in model.metadata.suggestions.items()
        if item.provenance.get("kind") == "del"
    )
    model.decide(native, decision)
    model.decide(prose, "accept")
    result = compact(directory)
    assert native in result["retained"] and prose in result["removed"]
    current = Project.read(directory).ordinary_changes()["index.qmd"]
    prepared = prepare_render(current.document, current.metadata)
    output = tmp_path / "rendered.docx"
    pandoc.run(
        ["--from=markdown-smart", "--to=docx", "--output", str(output)],
        source=prepared.markdown,
    )
    package = finish_document(WordPackage.read(output), prepared, directory)
    out = package.xml("word/document.xml")
    actual = out.xpath('.//w:r[w:t="old"]/w:rPr/w:b', namespaces=NS)
    assert bool(actual) == bold
    assert all(r.kind != "rPrChange" for r in read_review(package).revisions)


def test_missing_reference_stops_before_changing_source(tmp_path):
    text = HEADER + "\n{~~old~>new~~}{#s1 .accepted by=A}.\n"
    (tmp_path / "index.qmd").write_text(text)
    with pytest.raises(ReviewError, match="existing comparison reference"):
        compact(tmp_path)
    assert (tmp_path / "index.qmd").read_text() == text


def test_overlap_and_independent_reply_ranges_survive(tmp_path):
    from quarto_review.migration import inventory

    text = (
        HEADER
        + "\n[]{#c1-start}An {~~old~>new~~}{#s1 .accepted by=A} []{#r1-start}claim[]{#c1-end} remains[]{#r1-end}.\n\n"
        + THREAD
    )
    setup(tmp_path, text)
    before = read(text)
    compact(tmp_path)
    after = Project.read(tmp_path)
    old = inventory(before.document, before.metadata)
    new = inventory(after.source.document, after.metadata)
    assert old["original"] == new["original"]
    assert old["proposed"] == new["proposed"]
