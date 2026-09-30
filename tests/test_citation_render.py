"""Citation formatting and review identities use the same rendered passages."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from lxml import html

from quarto_review.errors import ReviewError
from quarto_review.html_finish import finish_html
from quarto_review.markers import marker
from quarto_review.project import capture_reference, setup
from quarto_review.quarto import enable, finish_outputs
from quarto_review.word.package import WordPackage
from quarto_review.word.reader import read_review, visible_text

BIB = """@article{brown2020, author={Brown, Beth}, title={Context}, year={2020}, journal={Memory}}
@article{smith2021, author={Smith, Alex}, title={Memory Search}, year={2021}, journal={Memory}}
@article{smith2022, author={Smith, Alex}, title={Recall}, year={2022}, journal={Memory}}
"""
NUMERIC = """<style xmlns="http://purl.org/net/xbiblio/csl" version="1.0" class="in-text">
<info><title>Synthetic numeric</title><id>https://example.org/numeric</id><updated>2026-01-01T00:00:00Z</updated></info>
<citation><layout prefix="[" suffix="]" delimiter="; "><text variable="citation-number"/></layout></citation>
<bibliography><layout><text variable="title"/></layout></bibliography></style>"""


def _environment():
    env = {
        **os.environ,
        "PATH": str(Path(sys.executable).parent) + os.pathsep + os.environ["PATH"],
    }
    for name in ("QUARTO_REVIEW_PROJECT", "QUARTO_REVIEW_COMMAND", "QUARTO_PANDOC"):
        env.pop(name, None)
    return env


@pytest.mark.integration
@pytest.mark.parametrize("numeric", [False, True])
def test_grouped_citations_keep_comment_target_and_pending_addition(tmp_path, numeric):
    source = """---
format:
  html: default
  docx: default
bibliography: refs.bib
link-citations: true
---

Evidence [@brown2020; {==@smith2021==}{>>Check this reference.<<}{#c1}{++; @smith2022++}{#s1}].

A {~~claim [@brown2020]~>stronger claim [@smith2021]~~}{#s2}.
"""
    if numeric:
        source = source.replace(
            "bibliography: refs.bib", "bibliography: refs.bib\ncsl: numeric.csl"
        )
        (tmp_path / "numeric.csl").write_text(NUMERIC)
    (tmp_path / "index.qmd").write_text(source)
    (tmp_path / "refs.bib").write_text(BIB)
    project = setup(tmp_path, author="Example Author")
    project.reply("c1", "Reference checked.")
    enable(tmp_path)
    capture_reference(project)
    frozen = (tmp_path / "index.qmd").read_bytes()
    result = subprocess.run(
        ["quarto", "render", "index.qmd", "--to", "all"],
        cwd=tmp_path,
        env=_environment(),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    page = html.fromstring((tmp_path / "index.html").read_text())
    card = page.get_element_by_id("qr-suggestion-s1")
    addition = card.xpath('.//*[@class="qr-change-after"]')[0].text_content()
    assert "@smith" not in addition
    assert ("3" if numeric else "2022") in addition
    second = page.get_element_by_id("qr-suggestion-s2")
    assert (
        "@brown" not in second.text_content() and "@smith" not in second.text_content()
    )
    assert (
        "claim" in second.text_content() and "stronger claim" in second.text_content()
    )
    assert not page.xpath('//*[starts-with(@id,"qr_cite_")]')
    package = WordPackage.read(tmp_path / "index.docx")
    review = read_review(package)
    thread = next(c for c in review.comments if c.parent_id is None)
    assert len(thread.anchors) == 1
    target = thread.anchors[0].text
    assert ("2" if numeric else "2021") in target
    assert ("3" if numeric else "2022") not in target
    assert next(c for c in review.comments if c.parent_id).parent_id == thread.id
    additions = [v for v in review.revisions if v.kind == "ins"]
    assert any(("3" if numeric else "2022") in v.text for v in additions)
    assert all(v.author == "Example Author" for v in additions)
    assert "QRX" not in visible_text(package.xml("word/document.xml"))
    assert (tmp_path / "index.qmd").read_bytes() == frozen
    assert finish_outputs(tmp_path, ("index.html", "index.docx")) == []


def test_html_finisher_detects_lost_citation_boundary():
    with pytest.raises(ReviewError, match="changed review boundaries"):
        finish_html(
            "<html><body><main><p>Citation</p></main></body></html>",
            {marker("C", "c1", "S"): 1},
        )


@pytest.mark.integration
def test_ordinary_narrative_edit_formats_both_alternatives_without_splitting_key(
    tmp_path,
):
    (tmp_path / "index.qmd").write_text(
        "---\nformat:\n  html: default\n  docx: default\nbibliography: refs.bib\n---\n\n@smith2021 found an effect.\n"
    )
    (tmp_path / "refs.bib").write_text(BIB)
    project = setup(tmp_path, author="Example Author", single_source=True)
    capture_reference(project)
    enable(tmp_path)
    source = tmp_path / "index.qmd"
    source.write_text(source.read_text().replace("@smith2021", "@smith2022"))
    from quarto_review.markup import project as reading
    from quarto_review.project import Project

    compared = Project.read(tmp_path).ordinary_changes()["index.qmd"]
    change = compared.document.annotations()[compared.automatic_ids[0]]
    assert reading(change.before) == "@smith2021"
    assert reading(change.after) == "@smith2022"
    frozen = source.read_bytes()
    result = subprocess.run(
        ["quarto", "render", "index.qmd", "--to", "all"],
        cwd=tmp_path,
        env=_environment(),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    page = html.fromstring((tmp_path / "index.html").read_text())
    card = page.xpath('//*[@class="qr-suggestion"]')[0]
    assert (
        "Smith" in card.text_content()
        and "2021" in card.text_content()
        and "2022" in card.text_content()
    )
    assert "@smith" not in card.text_content()
    review = read_review(WordPackage.read(tmp_path / "index.docx"))
    assert any(
        "2021" in revision.text
        for revision in review.revisions
        if revision.kind == "del"
    )
    assert any(
        "2022" in revision.text
        for revision in review.revisions
        if revision.kind == "ins"
    )
    assert source.read_bytes() == frozen


@pytest.mark.integration
@pytest.mark.parametrize("numeric", [False, True])
def test_markers_do_not_change_csl_text_or_locator_formatting(tmp_path, numeric):
    from quarto_review import pandoc

    (tmp_path / "refs.bib").write_text(BIB)
    if numeric:
        (tmp_path / "numeric.csl").write_text(NUMERIC)
    extra = "csl: numeric.csl\n" if numeric else ""
    body = "Evidence [see @brown2020, pp. 4–6; @smith2021; @smith2022]."
    annotated = body.replace(
        "@smith2021", "{==@smith2021==}{>>Check reference.<<}{#c1}"
    )
    source = (
        "---\nformat:\n  html: default\n  docx: default\nbibliography: refs.bib\n"
        + extra
        + "---\n\n"
        + annotated
        + "\n"
    )
    (tmp_path / "index.qmd").write_text(source)
    project = setup(tmp_path, author="Example Author")
    enable(tmp_path)
    capture_reference(project)
    result = subprocess.run(
        ["quarto", "render", "index.qmd", "--to", "all"],
        cwd=tmp_path,
        env=_environment(),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    page = html.fromstring((tmp_path / "index.html").read_text())
    actual = page.xpath("//main/p")[0].text_content()
    args = ["--from=markdown", "--to=html", "--citeproc", "--bibliography=refs.bib"]
    if numeric:
        args.append("--csl=numeric.csl")
    clean = html.fragment_fromstring(
        pandoc.run(args, source=body, directory=tmp_path), create_parent=True
    )
    expected = clean.xpath("./p")[0].text_content()
    assert " ".join(actual.split()) == " ".join(expected.split())
    word = WordPackage.read(tmp_path / "index.docx")
    anchor = read_review(word).comments[0].anchors[0].text
    assert ("2" if numeric else "2021") in anchor
    assert "pp." not in anchor and "2022" not in anchor


@pytest.mark.integration
def test_source_bibliography_retains_review_and_formats_native_citations(tmp_path):
    source = """---
format:
  html: default
  docx: default
bibliography: refs.bib
quarto-review:
  bibliography: source
---

Evidence [@brown2020; {==@smith2021==}{>>Check reference.<<}{#c1}].

# References

::: {#refs}

[]{#ref-brown2020}Brown, Beth. {==A retained source entry==}{>>Check this entry.<<}{#c2}.

[]{#ref-smith2021}Smith, Alex. A {~~short~>long~~}{#s1} title.

:::
"""
    (tmp_path / "index.qmd").write_text(source)
    (tmp_path / "refs.bib").write_text(BIB)
    project = setup(tmp_path, author="Example Author")
    enable(tmp_path)
    capture_reference(project)
    result = subprocess.run(
        ["quarto", "render", "index.qmd", "--to", "all"],
        cwd=tmp_path,
        env=_environment(),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    page = html.fromstring((tmp_path / "index.html").read_text())
    assert len(page.xpath('//*[@id="refs"]')) == 1
    assert "A retained source entry" in page.get_element_by_id("refs").text_content()
    assert "Memory Search" not in page.get_element_by_id("refs").text_content()
    assert len(page.xpath('//*[@id="ref-smith2021"]')) == 1
    review = read_review(WordPackage.read(tmp_path / "index.docx"))
    assert any(
        comment.anchors[0].text == "A retained source entry"
        for comment in review.comments
    )
    assert any(comment.anchors[0].text == "Smith 2021" for comment in review.comments)
    assert any(
        revision.text == "long"
        for revision in review.revisions
        if revision.kind == "ins"
    )


@pytest.mark.integration
def test_citation_comment_in_figure_caption_keeps_one_anchor(tmp_path):
    (tmp_path / "plot.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20"><rect width="20" height="20" fill="blue"/></svg>'
    )
    source = """---
format: html
bibliography: refs.bib
---

![Evidence [@brown2020; {==@smith2021==}{>>Check this reference.<<}{#c1}].](plot.svg){#fig-evidence}
"""
    (tmp_path / "index.qmd").write_text(source)
    (tmp_path / "refs.bib").write_text(BIB)
    project = setup(tmp_path, author="Example Author")
    enable(tmp_path)
    capture_reference(project)
    result = subprocess.run(
        ["quarto", "render", "index.qmd"],
        cwd=tmp_path,
        env=_environment(),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    page = html.fromstring((tmp_path / "index.html").read_text())
    assert len(page.xpath('//figcaption//span[@data-review-id="c1"]')) == 2
    assert not page.xpath('//img[contains(@alt,"QRX")]')


def test_range_recovery_refuses_reordered_or_collapsed_keys():
    from quarto_review.citation_ranges import _positions

    plan = {"id": "qr_cite_1", "keys": ["first", "second"], "markers": []}
    with pytest.raises(ReviewError, match="reordered, collapsed"):
        _positions("second; first", [("second", 0, 6), ("first", 8, 13)], plan)
    with pytest.raises(ReviewError, match="reordered, collapsed"):
        _positions("1–2", [("first", 0, 3)], plan)


def test_preview_chooses_nested_reading_and_strips_active_markup():
    from quarto_review.discussion import _safe_html
    from quarto_review.html_finish import _range_body

    def edge(kind, identifier, side):
        return f'<span class="qr-boundary" data-review-kind="{kind}" data-review-id="{identifier}" data-review-edge="{side}"></span>'

    markup = (
        "<main><p>"
        + edge("I", "s1", "S")
        + "A "
        + edge("D", "s2", "S")
        + "small"
        + edge("D", "s2", "E")
        + edge("I", "s2", "S")
        + "large"
        + edge("I", "s2", "E")
        + ' <a href="#ref-x" id="duplicate" onclick="alert(1)">Smith 2020</a> effect.'
        + edge("I", "s1", "E")
        + "</p></main>"
    )
    copied, count = _range_body([html.fromstring(markup)], "I", "s1")
    assert count == 1 and copied.text_content() == "A large Smith 2020 effect."
    safe = _safe_html(copied)
    assert (
        'href="#ref-x"' in safe
        and "onclick" not in safe
        and 'id="duplicate"' not in safe
    )
