"""Run ordinary Quarto rendering and verify native review output."""

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from quarto_review.project import capture_reference, setup
from quarto_review.quarto import enable, finish_outputs
from quarto_review.word.package import WordPackage
from quarto_review.word.reader import read_review, visible_text


@pytest.mark.integration
def test_quarto_docx_preserves_sources_and_native_review(tmp_path):
    if not shutil.which("quarto"):
        pytest.skip("Quarto is not installed")
    (tmp_path / "index.qmd").write_text(
        "---\ntitle: Review example\nauthor: Manuscript Author\nformat: docx\n---\n\nAn {=={~~old~>improved~~}{#s1} claim==}{>>Explain it.<<}{#c1}.\n"
    )
    project = setup(tmp_path, author="Example Author")
    project.reply("c1", "Updated.")
    enable(tmp_path)
    capture_reference(project)
    sources = {
        str(path.relative_to(tmp_path)): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
        and path.name != ".gitignore"
        and not path.is_relative_to(tmp_path / ".quarto")
    }
    environment = {
        **os.environ,
        "PATH": str(Path(sys.executable).parent) + os.pathsep + os.environ["PATH"],
    }
    result = subprocess.run(
        ["quarto", "render", "index.qmd", "--to", "docx"],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    output = WordPackage.read(tmp_path / "index.docx")
    review = read_review(output)
    assert [comment.text for comment in review.comments] == ["Explain it.", "Updated."]
    assert review.comments[1].parent_id == review.comments[0].id
    assert [(change.kind, change.author) for change in review.revisions] == [
        ("del", "Example Author"),
        ("ins", "Example Author"),
    ]
    assert "An improved claim." in visible_text(
        output.xml("word/document.xml"), "proposed"
    )
    assert "An old claim." in visible_text(output.xml("word/document.xml"), "original")
    assert "Review example" in visible_text(output.xml("word/document.xml"))
    assert "Manuscript Author" in visible_text(output.xml("word/document.xml"))
    for name, content in sources.items():
        assert (tmp_path / name).read_bytes() == content
    assert finish_outputs(tmp_path, ("index.docx",)) == []


@pytest.mark.integration
def test_quarto_html_anchors_threads_and_literal_code(tmp_path):
    if not shutil.which("quarto"):
        pytest.skip("Quarto is not installed")
    (tmp_path / "index.qmd").write_text(
        "---\ntitle: Review example\nformat: html\n---\n\nAn {=={~~old~>improved~~}{#s1} claim==}{>>Explain it.<<}{#c1}.\n\n```markdown\n{++literal example++}\n```\n"
    )
    project = setup(tmp_path, author="Example Author")
    project.reply("c1", '<script>alert("not executable")</script>')
    enable(tmp_path)
    capture_reference(project)
    environment = {
        **os.environ,
        "PATH": str(Path(sys.executable).parent) + os.pathsep + os.environ["PATH"],
    }
    result = subprocess.run(
        ["quarto", "render", "index.qmd", "--to", "html"],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    html = (tmp_path / "index.html").read_text()
    assert 'data-review-id="c1"' in html
    assert 'data-review-kind="I"' in html
    assert 'data-review-kind="D"' in html
    assert "Explain it." in html
    assert "&lt;script&gt;alert" in html
    assert "{++literal example++}" in html
    assert "QRXCQ" not in html
    script = re.search(r'<script src="([^"]*/review\.js)"', html)
    assert script is not None
    assert (tmp_path / script[1]).is_file()


@pytest.mark.integration
def test_quarto_tracks_an_ordinary_edit_against_the_reference(tmp_path):
    if not shutil.which("quarto"):
        pytest.skip("Quarto is not installed")
    original = "---\nformat: docx\n---\n\nA strong effect.\n"
    current = original.replace("strong", "modest")
    (tmp_path / "index.qmd").write_text(original)
    project = setup(tmp_path, author="Example Author")
    enable(tmp_path)
    capture_reference(project)
    (tmp_path / "index.qmd").write_text(current)
    environment = {
        **os.environ,
        "PATH": str(Path(sys.executable).parent) + os.pathsep + os.environ["PATH"],
    }
    result = subprocess.run(
        ["quarto", "render", "index.qmd", "--to", "docx"],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    output = WordPackage.read(tmp_path / "index.docx")
    root = output.xml("word/document.xml")
    assert visible_text(root, "original") == "A strong effect.\n"
    assert visible_text(root, "proposed") == "A modest effect.\n"
    assert len(read_review(output).revisions) == 2
    assert (tmp_path / "index.qmd").read_text() == current
    assert (tmp_path / "review/reference/index.qmd").read_text() == original


@pytest.mark.integration
def test_html_figure_caption_keeps_one_review_range(tmp_path):
    if not shutil.which("quarto"):
        pytest.skip("Quarto is not installed")
    from lxml import html as html_parser

    source = "---\nformat: html\n---\n\n![A {==caption claim==}{>>Explain.<<}{#c1}.](image.svg)\n"
    (tmp_path / "index.qmd").write_text(source)
    (tmp_path / "image.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20"><rect width="20" height="20"/></svg>'
    )
    project = setup(tmp_path, author="Example Author")
    enable(tmp_path)
    capture_reference(project)
    result = subprocess.run(
        ["quarto", "render", "index.qmd", "--to", "html"],
        cwd=tmp_path,
        env={
            **os.environ,
            "PATH": str(Path(sys.executable).parent) + os.pathsep + os.environ["PATH"],
        },
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "HTML conversion" not in result.stderr
    output = (tmp_path / "index.html").read_text()
    page = html_parser.fromstring(output)
    for edge in ("S", "E"):
        assert (
            len(
                page.xpath(
                    f'//figcaption//span[@data-review-id="c1"][@data-review-edge="{edge}"]'
                )
            )
            == 1
        )
        assert (
            len(page.xpath(f'//span[@data-review-id="c1"][@data-review-edge="{edge}"]'))
            == 1
        )
    assert "QRXCQ" not in output
    assert "A caption claim." == "".join(page.xpath("//figcaption//text()"))
    assert all("QRX" not in alt for alt in page.xpath("//img/@alt"))
    assert (tmp_path / "index.qmd").read_text() == source
