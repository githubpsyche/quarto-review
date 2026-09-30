"""One-time citation recovery preserves working edits and review identities."""

from dataclasses import asdict

import pytest

from quarto_review.citations import normalize_project, normalize_source
from quarto_review.project import Project
from quarto_review.source import read

HEADER = """---
bibliography: refs.json
review:
  schema: 2
  author: A
  authors:
    A: Example Author
    R: Example Reviewer
  reference: reference.qmd
---

"""
LINK = "[Smith, 2020](#ref-smith2020)"
KEYS = {"smith2020", "smith2022", "brown2021"}


@pytest.mark.parametrize(
    ("before", "after"),
    [
        (f"Evidence ({LINK}).", "Evidence [@smith2020]."),
        (
            f"Evidence (see {LINK}; [Brown, 2021](#ref_brown2021), pp. 2–3).",
            "Evidence [see @smith2020; @brown2021, pp. 2–3].",
        ),
        ("[Smith (2020)](#ref-smith2020) found this.", "@smith2020 found this."),
        ("[Smith’s (2020)](#ref-smith2020) study.", "Smith’s [-@smith2020] study."),
        (
            "Smith ([2020](#ref-smith2020), [2022](#ref-smith2022)).",
            "Smith [-@smith2020; -@smith2022].",
        ),
        (
            "[Smith’s (2020](#ref-smith2020), [2022)](#ref-smith2022) studies.",
            "Smith’s [-@smith2020; -@smith2022] studies.",
        ),
        ("[Smith, 2020](#ref-smith2020)", "[Smith, 2020](#ref-smith2020)"),
    ],
)
def test_recovery_requires_identity_and_preserves_citation_role(before, after):
    result = normalize_source(read(HEADER + before), KEYS)
    assert result.text == HEADER + after
    assert normalize_source(read(result.text), KEYS).text == result.text


def test_group_with_unknown_key_is_not_partially_rewritten():
    source = HEADER + f"({LINK}; [Brown, 2021](#ref-unknown))."
    result = normalize_source(read(source), KEYS)
    assert result.text == source
    assert len(result.retained) == 2
    assert all(record["line"] == 12 for record in result.retained)


def test_review_syntax_discussions_and_literal_regions_are_preserved():
    body = f"Evidence ({{=={LINK}==}}{{>>unused<<}}{{#c1}}{{++; [Brown, 2021](#ref-brown2021)++}}{{#s1 by=R}})."
    # Single-source threads own bodies, not the legacy inline comment syntax.
    body = body.replace("{==", "[]{#c1-start}").replace(
        "==}{>>unused<<}{#c1}", "[]{#c1-end}"
    )
    thread = f"\n\n::: {{.review-thread #c1 .resolved by=R}}\nKeep ({LINK}) literal here.\n\n::: {{.reply #r1 by=A}}\nAgreed.\n:::\n:::\n"
    source = (
        HEADER
        + body
        + f"\n\n`({LINK})`\n\n~~~markdown\n({LINK})\n~~~\n\n$({LINK})$"
        + thread
    )
    old = read(source)
    result = normalize_source(old, KEYS)
    assert (
        "Evidence [[]{#c1-start}@smith2020[]{#c1-end}{++; @brown2021++}{#s1 by=R}]."
        in result.text
    )
    assert result.text.endswith(thread)
    assert f"`({LINK})`" in result.text and f"$({LINK})$" in result.text
    assert asdict(read(result.text).metadata) == asdict(old.metadata)


def test_ambiguous_member_replacement_is_retained_and_reported():
    source = HEADER + f"({{~~{LINK}~>[Brown, 2021](#ref-brown2021)~~}}{{#s1 by=A}})."
    result = normalize_source(read(source), KEYS)
    assert result.text == source
    assert all("replacement" in item["reason"] for item in result.retained)


def project_fixture(tmp_path):
    source = HEADER + f"An original claim ({LINK}).\n"
    (tmp_path / "reference.qmd").write_text(source)
    (tmp_path / "index.qmd").write_text(source.replace("original", "revised"))
    bib = tmp_path / "refs.json"
    bib.write_text(
        '[{"id":"smith2020", "type":"article-journal", "title":"Study", "issued":{"date-parts":[[2020]]}}]'
    )
    return bib


def test_normalize_project_updates_both_without_accepting_unrelated_edits(tmp_path):
    bib = project_fixture(tmp_path)
    before = {file.name: file.read_bytes() for file in tmp_path.iterdir()}
    report = normalize_project(tmp_path, bib)
    assert report["applied"] is False and len(report["source"]["converted"]) == 1
    assert before == {file.name: file.read_bytes() for file in tmp_path.iterdir()}
    normalize_project(tmp_path, bib, apply=True)
    project = Project.read(tmp_path)
    assert "revised claim [@smith2020]" in project.source.text
    assert "original claim [@smith2020]" in (tmp_path / "reference.qmd").read_text()
    changes = project.ordinary_changes()["index.qmd"]
    assert len(changes.automatic_ids) == 1
    assert normalize_project(tmp_path, bib, apply=True)["source"]["converted"] == []


def test_failed_second_write_rolls_back_reference(tmp_path, monkeypatch):
    bib = project_fixture(tmp_path)
    before = {file.name: file.read_bytes() for file in tmp_path.iterdir()}

    def fail(*args, **kwargs):
        raise OSError("disk error")

    monkeypatch.setattr("quarto_review.source.Source.save", fail)
    with pytest.raises(OSError, match="disk error"):
        normalize_project(tmp_path, bib, apply=True)
    assert before == {file.name: file.read_bytes() for file in tmp_path.iterdir()}


@pytest.mark.integration
def test_import_recovers_link_identities_without_accepting_word_edits(
    word_package, tmp_path
):
    import json

    from lxml import etree

    from quarto_review.word.importer import import_document
    from quarto_review.word.namespaces import NS, tag

    document = word_package.xml("word/document.xml")
    paragraph = document.find("w:body/w:p", NS)
    for child in list(paragraph):
        paragraph.remove(child)

    def text(parent, value):
        run = etree.SubElement(parent, tag("w", "r"))
        etree.SubElement(
            run, tag("w", "t"), {tag("xml", "space"): "preserve"}
        ).text = value

    def edge(kind, identifier):
        etree.SubElement(paragraph, tag("w", kind), {tag("w", "id"): identifier})

    def link(parent, key, label):
        target = etree.SubElement(
            parent, tag("w", "hyperlink"), {tag("w", "anchor"): "ref-" + key}
        )
        text(target, label)

    text(paragraph, "Evidence (")
    edge("commentRangeStart", "2")
    edge("commentRangeStart", "0")
    link(paragraph, "smith2020", "Smith, 2020")
    edge("commentRangeEnd", "0")
    insertion = etree.SubElement(
        paragraph,
        tag("w", "ins"),
        {
            tag("w", "id"): "4",
            tag("w", "author"): "A. Reviewer",
            tag("w", "date"): "2026-01-02T09:00:00Z",
        },
    )
    text(insertion, "; ")
    link(insertion, "brown2021", "Brown, 2021")
    edge("commentRangeEnd", "2")
    text(paragraph, ").")
    word_package.set_xml("word/document.xml", document)
    source = tmp_path / "source.docx"
    word_package.write(source)
    original = source.read_bytes()
    bib = tmp_path / "refs.json"
    bib.write_text(
        json.dumps(
            [{"id": key, "type": "article-journal", "title": key} for key in KEYS]
        )
    )
    destination = tmp_path / "imported"
    import_document(
        source,
        destination,
        author="Example Author",
        single_source=True,
        bibliography=bib,
    )
    project = Project.read(destination)
    assert "@smith2020" in project.source.text and "@brown2021" in project.source.text
    assert project.metadata.suggestions["s1"].status == "pending"
    assert project.metadata.suggestions["s1"].author == "A. Reviewer"
    assert project.metadata.suggestions["s1"].provenance["word_id"] == "4"
    assert project.metadata.comments["c0"].replies[0].parent_id == "c0"
    assert project.metadata.comments["c2"].status == "resolved"
    assert next(destination.glob("assets/review/*.docx")).read_bytes() == original
    assert source.read_bytes() == original
    report = json.loads(
        (destination / ".quarto/review/citation-import.json").read_text()
    )
    assert len(report["converted"]) == 2 and not report["retained"]


def test_apply_requires_configured_bibliography_without_changing_source(tmp_path):
    from quarto_review.errors import ReviewError

    bib = project_fixture(tmp_path)
    current = tmp_path / "index.qmd"
    current.write_text(current.read_text().replace("bibliography: refs.json\n", ""))
    frozen = current.read_bytes()
    assert normalize_project(tmp_path, bib)["bibliography_configured"] is False
    with pytest.raises(ReviewError, match="Declare the supplied bibliography"):
        normalize_project(tmp_path, bib, apply=True)
    assert current.read_bytes() == frozen


def test_decided_citation_source_is_not_rewritten(tmp_path):
    bib = project_fixture(tmp_path)
    path = tmp_path / "index.qmd"
    path.write_text(HEADER + f"{{++A claim ({LINK}).++}}{{#s1 by=R}}")
    project = Project.read(tmp_path)
    project.decide("s1", "accept")
    original = path.read_bytes()
    from quarto_review.errors import ReviewError

    frozen = (tmp_path / "reference.qmd").read_bytes()
    report = normalize_project(tmp_path, bib)
    assert report["blocked"]
    with pytest.raises(ReviewError, match="Settled citation suggestions"):
        normalize_project(tmp_path, bib, apply=True)
    assert path.read_bytes() == original
    assert (tmp_path / "reference.qmd").read_bytes() == frozen
    assert "Decided suggestion s1" in report["source"]["retained"][0]["reason"]
    assert Project.read(tmp_path).metadata.suggestions["s1"].status == "accepted"


def test_cli_dry_run_and_invalid_bibliography_are_actionable(tmp_path, capsys):
    from quarto_review.cli import main

    bib = project_fixture(tmp_path)
    assert (
        main(
            [
                "normalize-citations",
                "--project",
                str(tmp_path),
                "--bibliography",
                str(bib),
            ]
        )
        == 0
    )
    assert '"applied": false' in capsys.readouterr().out
    original = (tmp_path / "index.qmd").read_bytes()
    bib.write_text("not valid JSON")
    assert (
        main(
            [
                "normalize-citations",
                "--project",
                str(tmp_path),
                "--bibliography",
                str(bib),
                "--apply",
            ]
        )
        == 1
    )
    assert "Cannot read bibliography" in capsys.readouterr().err
    assert (tmp_path / "index.qmd").read_bytes() == original
