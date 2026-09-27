"""Behavioural checks for a self-contained QMD review source."""

import os
import shutil
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

import pytest

from quarto_review.authoring import annotate
from quarto_review.errors import ReviewError
from quarto_review.markup import parse, project
from quarto_review.metadata import CommentMetadata, ReviewMetadata, SuggestionMetadata
from quarto_review.migration import convert_verified, inventory, migrate
from quarto_review.project import Project, capture_reference, setup
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
THREAD = """:::: {.review-thread #c1 by=R}
Please **clarify** this claim.

::: {.reply #r1 by=A}
I will explain it.
:::
::::
"""
PASSAGE = "The study found [a {~~large~>modest~~}{#s1 by=R} difference]{#c1}.\n"


def write_project(tmp_path, text=HEADER + "\n" + PASSAGE + "\n" + THREAD):
    (tmp_path / "index.qmd").write_text(text)
    (tmp_path / "reference.qmd").write_text(text)
    return Project.read(tmp_path)


def test_compact_spans_thread_order_and_markdown_body():
    first = read(HEADER + THREAD + "\n" + PASSAGE)
    last = read(HEADER + PASSAGE + "\n" + THREAD)
    assert first.metadata == last.metadata
    assert project(first.document.nodes).strip() == project(last.document.nodes).strip()
    assert first.document.annotations()["c1"].body == "Please **clarify** this claim."
    assert first.metadata.comments["c1"].replies[0].parent_id == "c1"


def test_link_in_comment_span_and_literal_code():
    source = (
        HEADER
        + "[a [link](https://example.org) and \x60literal ]\x60]{#c1}.\n\n"
        + THREAD
    )
    model = read(source)
    assert "a [link](https://example.org) and \x60literal ]\x60." in project(
        model.document.nodes
    )
    literal = HEADER + "\n~~~markdown\n" + THREAD + PASSAGE + "~~~\n"
    parsed = read(literal)
    assert parsed.metadata.comments == {}
    assert parsed.metadata.suggestions == {}
    assert project(parsed.document.nodes) == literal


def test_operations_change_only_qmd_and_preserve_reference(tmp_path):
    manuscript = write_project(tmp_path)
    frozen = (tmp_path / "reference.qmd").read_bytes()
    before = project(manuscript.documents["index.qmd"].nodes)
    new_reply = manuscript.reply("r1", "An additional reply.")
    assert manuscript.metadata.comments["c1"].replies[-1].parent_id == "r1"
    assert new_reply.startswith("r")
    manuscript.decide("c1", "resolve")
    assert manuscript.metadata.comments["c1"].status == "resolved"
    manuscript.decide("c1", "reopen")
    manuscript.decide("s1", "reject")
    assert ".rejected" in (tmp_path / "index.qmd").read_text()
    manuscript.decide("s1", "pending")
    manuscript.delete_comment("c1")
    assert set(manuscript.metadata.suggestions) == {"s1"}
    assert manuscript.metadata.comments == {}
    assert project(manuscript.documents["index.qmd"].nodes).strip() == before.strip()
    assert (tmp_path / "reference.qmd").read_bytes() == frozen
    assert not (tmp_path / "review.yml").exists()
    assert manuscript.ordinary_changes()["index.qmd"].automatic_ids == ()


def test_overlap_deletion_retains_other_range_and_revision(tmp_path):
    source = (
        HEADER
        + "A []{#c1-start}{~~large~>small~~}{#s1 by=R} []{#c2-start}difference[]{#c1-end} remains[]{#c2-end}.\n\n"
    )
    source += THREAD + "\n::: {.review-thread #c2 by=R}\nCheck this too.\n:::\n"
    manuscript = write_project(tmp_path, source)
    before = inventory(manuscript.documents["index.qmd"], manuscript.metadata)
    manuscript.delete_comment("c1")
    after = inventory(manuscript.documents["index.qmd"], manuscript.metadata)
    for view in ("original", "proposed"):
        assert before[view]["text"] == after[view]["text"]
        assert before[view]["anchors"]["c2"] == after[view]["anchors"]["c2"]
    assert before["suggestions"] == after["suggestions"]


def test_comment_on_deleted_word_and_reply_range():
    source = (
        HEADER
        + "A {~~[large]{#c1}~>small~~}{#s1 by=R} []{#r1-start}difference[]{#r1-end}.\n\n"
        + THREAD
    )
    model = read(source)
    assert set(model.anchors) == {"c1", "r1"}
    assert "A small difference." in project(model.document.nodes)
    assert "A large difference." in project(model.document.nodes, "original")


@pytest.mark.parametrize(
    "replace_from, replace_to, message",
    [
        ("by=R", "by=UNKNOWN", "author alias"),
        ("{#s1 by=R}", "{#s1 .accepted .rejected by=R}", "suggestion attributes"),
        ("#c1}", "#missing}", "has no anchor"),
        (".reply #r1 by=A", ".reply #r1 by=A to=absent", "unavailable parent"),
        (".reply #r1 by=A", ".reply #r1 by=A resolved=maybe", "true or false"),
    ],
)
def test_invalid_review_state_is_located(replace_from, replace_to, message):
    with pytest.raises(ReviewError, match=message):
        read((HEADER + PASSAGE + "\n" + THREAD).replace(replace_from, replace_to))


def test_unpaired_crossing_marker():
    with pytest.raises(ReviewError, match="Unclosed range"):
        read(HEADER + "[]{#c1-start}Claim.\n\n" + THREAD)


def test_source_conflict_does_not_overwrite_newer_work(tmp_path):
    manuscript = write_project(tmp_path)
    newer = (tmp_path / "index.qmd").read_text().replace("The study", "The experiment")
    (tmp_path / "index.qmd").write_text(newer)
    with pytest.raises(ReviewError, match="source changed"):
        manuscript.reply("c1", "A reply.")
    assert (tmp_path / "index.qmd").read_text() == newer


def test_annotation_creation_and_automatic_decision(tmp_path):
    manuscript = write_project(tmp_path, HEADER + "\nThe effect was large.\n")
    comment = annotate(manuscript, "index.qmd", "effect", body="Explain.")
    suggestion = annotate(manuscript, "index.qmd", "large", replacement="small")
    assert manuscript.metadata.comments[comment].author == "Example Author"
    manuscript.decide(suggestion, "accept")
    path = tmp_path / "index.qmd"
    path.write_text(path.read_text().replace("The [", "The observed ["))
    manuscript = Project.read(tmp_path)
    auto = manuscript.ordinary_changes()["index.qmd"].automatic_ids
    assert auto
    manuscript.decide(auto[0], "reject")
    assert auto[0] in manuscript.metadata.suggestions


def test_review_changes_do_not_create_prose_revisions(tmp_path):
    manuscript = write_project(tmp_path)
    manuscript.reply("c1", "A much longer reply.\nA second sentence.")
    manuscript.decide("c1", "resolve")
    assert manuscript.ordinary_changes()["index.qmd"].automatic_ids == ()
    text = (tmp_path / "index.qmd").read_text()
    start = text.index("::::")
    body, thread = text[len(HEADER) : start], text[start:]
    (tmp_path / "index.qmd").write_text(HEADER + thread + "\n" + body)
    assert Project.read(tmp_path).ordinary_changes()["index.qmd"].automatic_ids == ()


def test_legacy_candidate_checks_both_current_and_frozen(tmp_path):
    original, candidate = tmp_path / "legacy", tmp_path / "candidate"
    original.mkdir()
    (original / "index.qmd").write_text(
        "The effect was {~~large~>small~~}{#s1}.\n\n{==effect==}{>>Explain.<<}{#c1}\n"
    )
    old = setup(original, author="Example Author")
    capture_reference(old)
    old.reply("c1", "A response.")
    before = {
        str(p.relative_to(original)): p.read_bytes()
        for p in original.rglob("*")
        if p.is_file()
    }
    result = migrate(original, candidate)
    assert result["switched"] is False
    assert read((candidate / "index.qmd").read_text()).metadata.comments["c1"].replies
    assert (
        read((candidate / "reference.qmd").read_text()).metadata.comments["c1"].replies
        == ()
    )
    assert not (candidate / "review.yml").exists()
    assert all(
        (original / name).read_bytes() == content for name, content in before.items()
    )


def test_known_dates_identity_and_distinct_reply_status_survive():
    from quarto_review.metadata import Reply

    doc = parse("{==Claim==}{>>Question?<<}{#c1}")
    metadata = ReviewMetadata(
        "Example Author",
        "2026-01-01T12:00:00+01:00",
        comments={
            "c1": CommentMetadata(
                "Reviewer",
                "2026-01-02T13:15:16.123+02:00",
                "open",
                (Reply("r1", "A reply.", None, None, "c1", {"word_id": "8"}, True),),
                {"word_id": "7", "durable_id": "AABBCCDD"},
            )
        },
    )
    converted = read(convert_verified(doc, metadata))
    assert asdict(converted.metadata.comments["c1"]) == asdict(metadata.comments["c1"])


def test_property_revision_boundaries_convert():
    source = '[]{.review-start data-review="s1"}Bold[]{.review-end data-review="s1"}{~~~>~~}{#s1}'
    metadata = ReviewMetadata(
        "Author",
        "",
        suggestions={
            "s1": SuggestionMetadata("Reviewer", None, provenance={"kind": "rPrChange"})
        },
    )
    assert (
        read(convert_verified(parse(source), metadata))
        .metadata.suggestions["s1"]
        .provenance["kind"]
        == "rPrChange"
    )


@pytest.mark.integration
def test_quarto_html_and_docx_from_single_source(tmp_path):
    from quarto_review.quarto import enable
    from quarto_review.word.package import WordPackage
    from quarto_review.word.reader import read_review

    if not shutil.which("quarto"):
        pytest.skip("Quarto is unavailable")
    write_project(tmp_path)
    (tmp_path / "_quarto.yml").write_text(
        "project:\n  type: default\nformat:\n  html: default\n  docx: default\n"
    )
    enable(tmp_path)
    env = {
        **os.environ,
        "PATH": str(Path(sys.executable).parent) + os.pathsep + os.environ["PATH"],
    }
    for name in (
        "QUARTO_REVIEW_PROJECT",
        "QUARTO_REVIEW_COMMAND",
        "QUARTO_PANDOC",
        "QUARTO_REVIEW_PRIVATE_DOCX",
    ):
        env.pop(name, None)
    result = subprocess.run(
        ["quarto", "render", "index.qmd", "--to", "all"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    html = (tmp_path / "index.html").read_text()
    assert "qr-thread-c1" in html
    assert "I will explain it." in html
    assert "<strong>clarify</strong>" in html
    assert "Please **clarify**" not in html
    assert "review-thread #c1" not in html
    native = read_review(WordPackage.read(tmp_path / "index.docx"))
    assert len(native.comments) == 2
    assert {c.author for c in native.comments} == {"Example Author", "Example Reviewer"}
    assert any(c.parent_id is not None for c in native.comments)
    assert not (tmp_path / "review/exchanges").exists()
    assert not (tmp_path / "review.yml").exists()


def test_conversion_does_not_ignore_lost_word_separators():
    metadata = ReviewMetadata("Author", "")
    assert inventory(parse("Two words."), metadata) != inventory(
        parse("Twowords."), metadata
    )


def test_unicode_attribution_conversion():
    metadata = ReviewMetadata(
        "李 明", "", comments={"c1": CommentMetadata("Émilie Müller", None)}
    )
    model = read(convert_verified(parse("{==Claim==}{>>Question?<<}{#c1}"), metadata))
    assert model.metadata.author == "李 明"
    assert model.metadata.comments["c1"].author == "Émilie Müller"


def test_multiple_ranges_and_reply_code_block():
    source = (
        HEADER
        + "[]{#c1-start}First[]{#c1-end}; []{#c1-2-start}second[]{#c1-2-end}.\n\n"
        + THREAD
    )
    model = read(source)
    assert len(model.anchors["c1"]) == 4


def test_compact_executed_reference_is_self_contained(tmp_path):
    from quarto_review.execution import record_execution
    from quarto_review.quarto import prepare

    source = HEADER + "\nA strong effect.\n\n~~~{python}\nprint(42)\n~~~\n"
    manuscript = write_project(tmp_path, source)
    executed = HEADER + "\nA strong effect.\n\n::: {.cell-output}\n42\n:::\n"
    record_execution(manuscript, "index.qmd", "html", executed)
    capture_reference(manuscript, new_round=True)
    reference = (tmp_path / "reference.qmd").read_bytes()
    assert read(reference.decode()).settings["compiled"]["html"] == executed
    (tmp_path / "index.qmd").write_text(source.replace("strong", "modest"))
    result = prepare(
        tmp_path,
        executed.replace("strong", "modest"),
        path="index.qmd",
        output="index.html",
        format="html",
    )
    assert len(result["automatic_suggestions"]) == 1
    assert "42" in result["markdown"]
    assert (tmp_path / "reference.qmd").read_bytes() == reference


@pytest.mark.integration
def test_native_word_import_to_compact_source_preserves_overlap(tmp_path, word_package):
    from quarto_review.word.importer import import_document
    from quarto_review.word.reader import read_review

    document = tmp_path / "returned.docx"
    word_package.write(document)
    destination = tmp_path / "candidate"
    metadata = import_document(
        document, destination, author="Example Author", single_source=True
    )
    source = read((destination / "index.qmd").read_text())
    native = read_review(word_package)
    assert len(source.metadata.comments) == 2
    assert sum(len(c.replies) for c in source.metadata.comments.values()) == 1
    assert {
        n.body for n in source.document.annotations().values() if hasattr(n, "body")
    } == {c.text for c in native.comments if c.parent_id is None}
    assert asdict(source.metadata) == asdict(metadata)
    assert not (destination / "review.yml").exists()


def test_new_round_allows_further_edits_to_decided_wording(tmp_path):
    manuscript = write_project(tmp_path)
    manuscript.decide("s1", "accept")
    capture_reference(manuscript, new_round=True)
    path = tmp_path / "index.qmd"
    path.write_text(path.read_text().replace("large~>modest", "large~>small"))
    manuscript = Project.read(tmp_path)
    assert manuscript.ordinary_changes()["index.qmd"].automatic_ids


def test_recorded_decision_requires_reopening_in_same_round(tmp_path):
    manuscript = write_project(tmp_path)
    manuscript.decide("s1", "accept")
    path = tmp_path / "index.qmd"
    path.write_text(path.read_text().replace("large~>modest", "large~>small"))
    with pytest.raises(ReviewError, match="Decided suggestion"):
        Project.read(tmp_path)
    manuscript = Project.read(tmp_path, validate_decisions=False)
    manuscript.decide("s1", "pending")
    assert Project.read(tmp_path).metadata.suggestions["s1"].status == "pending"


def test_receive_guard_does_not_read_or_stage_a_return(tmp_path):
    from quarto_review.returns import receive

    write_project(tmp_path)
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    with pytest.raises(ReviewError, match="explicit"):
        receive(tmp_path, tmp_path / "missing-return.docx")
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before


def test_receive_cli_uses_the_same_guard(tmp_path, capsys):
    from quarto_review.cli import main

    write_project(tmp_path)
    assert (
        main(["receive", str(tmp_path / "missing.docx"), "--project", str(tmp_path)])
        == 1
    )
    assert "Single-source return review is explicit" in capsys.readouterr().err
