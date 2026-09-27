"""Exercise manuscript structures and execution through real Quarto renders."""

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from quarto_review.project import capture_reference, setup
from quarto_review.quarto import enable
from quarto_review.word.namespaces import NS
from quarto_review.word.package import WordPackage
from quarto_review.word.reader import read_review, visible_text
from quarto_review.word.validation import validate_package

SOURCE = """---
title: Synthetic manuscript
author: Manuscript Author
bibliography: references.bib
format: docx
---

# Results

An {~~**old**~>**new**~~}{#s1} finding follows {==Smith's account [@smith2020]==}{>>Check the citation.<<}{#c1}.

The estimate was {~~$x^2$~>$x^3$~~}{#s2}. See @tbl-results and this note.{==[^detail]==}{>>Check this note.<<}{#c3}

| Measure | Value |
|:--------|------:|
| Score   | {~~3~>4~~}{#s3} |

: {==Observed values==}{>>Clarify this caption.<<}{#c2} {#tbl-results}

[^detail]: A {~~footnote~>revised footnote~~}{#s4} passage with Unicode café and α.
"""


@pytest.mark.integration
def test_citations_equations_table_caption_and_footnote(tmp_path):
    if not shutil.which("quarto"):
        pytest.skip("Quarto is not installed")
    (tmp_path / "index.qmd").write_text(SOURCE)
    (tmp_path / "references.bib").write_text(
        "@book{smith2020, author={Smith, Alex}, title={An Example}, year={2020}, publisher={Example Press}}\n"
    )
    manuscript = setup(tmp_path, author="Writer")
    enable(tmp_path)
    capture_reference(manuscript)
    result = subprocess.run(
        ["quarto", "render", "index.qmd"], cwd=tmp_path, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout + result.stderr
    package = WordPackage.read(tmp_path / "index.docx")
    inventory = validate_package(package)
    assert inventory["threads"] == 3
    review = read_review(package)
    assert {comment.text for comment in review.comments} == {
        "Check the citation.",
        "Clarify this caption.",
        "Check this note.",
    }
    assert any(revision.story == "word/footnotes.xml" for revision in review.revisions)
    root = package.xml("word/document.xml")
    assert root.find(".//w:tbl", NS) is not None
    assert root.find(".//m:oMath", NS) is not None
    assert "An Example" in visible_text(root)
    assert "new" in visible_text(root, "proposed")
    assert "old" in visible_text(root, "original")


@pytest.mark.integration
def test_existing_apa_format(tmp_path):
    extension = os.environ.get("QUARTO_REVIEW_APA_EXTENSION")
    if not extension or not shutil.which("quarto"):
        pytest.skip(
            "Set QUARTO_REVIEW_APA_EXTENSION to an installed apaquarto extension"
        )
    destination = tmp_path / "_extensions/wjschne/apaquarto"
    destination.parent.mkdir(parents=True)
    shutil.copytree(Path(extension), destination)
    (tmp_path / "index.qmd").write_text(
        "---\ntitle: APA review fixture\nshorttitle: REVIEW FIXTURE\nauthor:\n  - name: Manuscript Author\n    affiliations:\n      - name: Example University\nformat: apaquarto-docx\nsuppress-author-note: true\n---\n\nA {=={~~strong~>modest~~}{#s1} effect==}{>>Check wording.<<}{#c1}.\n"
    )
    manuscript = setup(tmp_path, author="Reviewer")
    enable(tmp_path)
    capture_reference(manuscript)
    result = subprocess.run(
        ["quarto", "render", "index.qmd"], cwd=tmp_path, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout + result.stderr
    output = WordPackage.read(tmp_path / "index.docx")
    review = read_review(output)
    assert len(review.comments) == 1
    assert [(revision.kind, revision.author) for revision in review.revisions] == [
        ("del", "Reviewer"),
        ("ins", "Reviewer"),
    ]
    text = visible_text(output.xml("word/document.xml"), "proposed")
    assert "Manuscript Author" in text
    assert "Example University" in text
    assert "A modest effect." in text


@pytest.mark.integration
def test_real_jupyter_reference_and_prose_edit(tmp_path, monkeypatch):
    if not shutil.which("quarto") or importlib.util.find_spec("nbclient") is None:
        pytest.skip("Install the execution-tests dependency group and Quarto")
    source = '---\nformat: docx\njupyter: python3\nexecute:\n  echo: false\n---\n\nA strong effect.\n\n```{python}\nprint("Calculated value:", 6 * 7)\n```\n'
    (tmp_path / "index.qmd").write_text(source)
    manuscript = setup(tmp_path, author="Writer")
    enable(tmp_path)
    monkeypatch.setenv("QUARTO_PYTHON", sys.executable)
    manifest = capture_reference(manuscript, execute=True, formats=("docx",))
    assert (
        "Calculated value: 42"
        in (
            tmp_path / "review/reference" / manifest["compiled"]["index.qmd:docx"]
        ).read_text()
    )
    (tmp_path / "index.qmd").write_text(source.replace("strong", "modest"))
    result = subprocess.run(
        ["quarto", "render", "index.qmd", "--to", "docx"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=os.environ,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    package = WordPackage.read(tmp_path / "index.docx")
    text = visible_text(package.xml("word/document.xml"), "proposed")
    assert "A modest effect." in text
    assert "Calculated value: 42" in text
    assert {
        (revision.kind, revision.text) for revision in read_review(package).revisions
    } == {("del", "strong"), ("ins", "modest")}


@pytest.mark.integration
def test_pdf_uses_clean_proposed_text(tmp_path):
    if (
        not shutil.which("quarto")
        or not shutil.which("lualatex")
        or not shutil.which("pdftotext")
    ):
        pytest.skip("Quarto, LuaLaTeX and pdftotext are required")
    (tmp_path / "index.qmd").write_text(
        "---\ntitle: Clean review output\nformat:\n  pdf:\n    pdf-engine: lualatex\n---\n\nA {=={~~strong~>modest~~}{#s1} effect==}{>>Private reviewer discussion.<<}{#c1}.\n"
    )
    manuscript = setup(tmp_path, author="Reviewer")
    enable(tmp_path)
    capture_reference(manuscript)
    result = subprocess.run(
        ["quarto", "render", "index.qmd"], cwd=tmp_path, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout + result.stderr
    text = subprocess.check_output(
        ["pdftotext", str(tmp_path / "index.pdf"), "-"], text=True
    )
    assert "A modest effect." in text
    assert "strong" not in text
    assert "Private reviewer discussion" not in text
    assert "QRX" not in text


@pytest.mark.integration
@pytest.mark.private
def test_private_import_renders_through_quarto(tmp_path):
    source = os.environ.get("QUARTO_REVIEW_PRIVATE_DOCX")
    if not source or not shutil.which("quarto"):
        pytest.skip("Set QUARTO_REVIEW_PRIVATE_DOCX to run the private Quarto check")
    from quarto_review.word.importer import import_document

    directory = tmp_path / "project"
    import_document(Path(source), directory, author="Example Author")
    enable(directory)
    result = subprocess.run(
        ["quarto", "render", "index.qmd", "--to", "docx"],
        cwd=directory,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    package = WordPackage.read(directory / "index.docx")
    assert validate_package(package)["comments"] == 52
    review = read_review(package)
    assert len([item for item in review.comments if item.parent_id is not None]) == 5
