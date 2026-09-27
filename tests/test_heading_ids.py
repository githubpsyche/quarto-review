"""Review markup must not become part of HTML heading destinations."""
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
@pytest.mark.parametrize("format_name", ["html", "apaquarto-html"])
def test_reviewed_headings_keep_clean_unique_link_targets(tmp_path, format_name):
    if not shutil.which("quarto"):
        pytest.skip("Quarto is not installed")
    if format_name == "apaquarto-html":
        extension = os.environ.get("QUARTO_REVIEW_APA_EXTENSION")
        if not extension:
            pytest.skip("Set QUARTO_REVIEW_APA_EXTENSION")
        destination = tmp_path / "_extensions/wjschne/apaquarto"
        destination.parent.mkdir(parents=True)
        shutil.copytree(Path(extension), destination)
    source = """# {==Target==}{>>Check this title.<<}{#c1}

Text under the commented heading.

# Another section {#target}

# {==Named heading==}{>>Keep this explicit identifier.<<}{#c2} {#keep-me}

[Explicit link](#keep-me).

# {==Deliberate Recognition==}{>>Keep the domain clear.<<}{#c3}

# A {~~large~>small~~}{#s1} effect
"""
    (tmp_path / "index.qmd").write_text(source)
    (tmp_path / "_quarto.yml").write_text(yaml.safe_dump({
        "project": {"type": "default"},
        "title": "Heading fixture",
        "author": [{"name": "Manuscript Author", "affiliations": [{"name": "Example University"}]}],
        "format": {format_name: {"toc": True, "suppress-author-note": True}},
    }))
    project = setup(tmp_path, author="Reviewer")
    enable(tmp_path)
    capture_reference(project)
    result = subprocess.run(
        ["quarto", "render", "index.qmd"], cwd=tmp_path,
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    page = html.fromstring((tmp_path / "index.html").read_bytes())
    identifiers = page.xpath('//*[@id]/@id')
    assert len(identifiers) == len(set(identifiers))
    assert not any("qrx" in identifier.lower() for identifier in identifiers)
    assert {"target", "target-1", "keep-me", "deliberate-recognition"} <= set(identifiers)
    toc = page.xpath('//*[@id="TOC"]//a/@href')
    assert "#keep-me" in toc
    assert "#deliberate-recognition" in toc
    assert all(link[1:] in identifiers for link in toc if link.startswith("#"))
    assert len(page.xpath('//*[@class="qr-thread"]')) == 3
    assert len(page.xpath('//*[@class="qr-suggestion"]')) == 1
    assert (tmp_path / "index.qmd").read_text() == source
