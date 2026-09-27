"""Check that project-selected HTML formats retain review information."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml
from lxml import html

from quarto_review.project import capture_reference, setup
from quarto_review.quarto import enable


@pytest.mark.integration
def test_html_style_is_selected_by_project_yaml(tmp_path):
    extension = os.environ.get("QUARTO_REVIEW_APA_EXTENSION")
    if not extension or not shutil.which("quarto"):
        pytest.skip("Set QUARTO_REVIEW_APA_EXTENSION and install Quarto")
    destination = tmp_path / "_extensions/wjschne/apaquarto"
    destination.parent.mkdir(parents=True)
    shutil.copytree(Path(extension), destination)
    source = "# Findings\n\nA {=={~~strong~>modest~~}{#s1} effect==}{>>Explain this claim.<<}{#c1}.\n"
    (tmp_path / "index.qmd").write_text(source)
    config_path = tmp_path / "_quarto.yml"
    config_path.write_text(yaml.safe_dump({
        "project": {"type": "default"},
        "title": "Review fixture",
        "author": [{"name": "Manuscript Author", "affiliations": [{"name": "Example University"}]}],
        "format": {"apaquarto-html": {"suppress-author-note": True}},
    }))
    project = setup(tmp_path, author="Reviewer")
    project.reply("c1", "Clarification planned.")
    enable(tmp_path)
    capture_reference(project)
    metadata_before = (tmp_path / "review.yml").read_bytes()
    reference_before = {
        str(p.relative_to(tmp_path)): p.read_bytes()
        for p in (tmp_path / "review/reference").rglob("*") if p.is_file()
    }
    bootstrap_styles = []
    for format_name, options in (
        ("apaquarto-html", {"suppress-author-note": True}),
        ("html", {"theme": "darkly", "toc": True}),
    ):
        config = yaml.safe_load(config_path.read_text())
        config["format"] = {format_name: options}
        config_path.write_text(yaml.safe_dump(config, sort_keys=False))
        enable(tmp_path)
        assert yaml.safe_load(config_path.read_text())["format"] == config["format"]
        result = subprocess.run(
            ["quarto", "render", "index.qmd"], cwd=tmp_path,
            capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        page = html.fromstring((tmp_path / "index.html").read_bytes())
        styles = page.xpath('//link[@rel="stylesheet"]/@href')
        assert any(path.endswith("apa.css") for path in styles) == (format_name == "apaquarto-html")
        bootstrap_styles.append(next(path for path in styles if "/bootstrap-" in path and path.endswith("min.css")))
        assert len(page.xpath('//*[@class="qr-thread"]')) == 1
        assert len(page.xpath('//*[@class="qr-reply"]')) == 1
        assert "Explain this claim." in page.text_content()
        assert "Clarification planned." in page.text_content()
        assert page.xpath('//*[@data-review-kind="I"]')
        assert page.xpath('//*[@data-review-kind="D"]')
        assert any(path.endswith("review.css") for path in styles)
        assert page.xpath('//script[contains(@src,"review.js")]')
        assert (tmp_path / "index.qmd").read_text() == source
        assert (tmp_path / "review.yml").read_bytes() == metadata_before
        for name, content in reference_before.items():
            assert (tmp_path / name).read_bytes() == content
    assert bootstrap_styles[0] != bootstrap_styles[1]
