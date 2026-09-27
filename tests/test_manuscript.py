"""Native manuscript layout must survive enabling the review extension."""
import shutil
import subprocess
from collections import Counter

import pytest
import yaml
from lxml import html

from quarto_review.project import capture_reference, setup
from quarto_review.quarto import enable


@pytest.mark.integration
def test_native_manuscript_front_matter_retains_review_ranges(tmp_path):
    if not shutil.which("quarto"):
        pytest.skip("Install Quarto")
    source = (
        "# A {=={~~strong~>qualified~~}{#s1} title==}{>>Check title.<<}{#c1}\n\n"
        "An {==annotated abstract==}{>>Check abstract.<<}{#c2}.\n\n"
        "# Findings\n\nA {==body passage==}{>>Check body.<<}{#c3}.\n"
    )
    (tmp_path / "index.qmd").write_text(source)
    (tmp_path / "frontmatter.lua").write_text('''
function Pandoc(doc)
  doc.meta.title = pandoc.MetaInlines(doc.blocks[1].content)
  doc.meta.abstract = pandoc.MetaBlocks({doc.blocks[2]})
  doc.blocks:remove(1)
  doc.blocks:remove(1)
  return doc
end
''')
    config_path = tmp_path / "_quarto.yml"
    config_path.write_text(yaml.safe_dump({
        "project": {"type": "manuscript", "output-dir": "_output"},
        "manuscript": {"article": "index.qmd", "code-links": False},
        "author": [{"name": "Manuscript Author", "affiliation": "Example University"}],
        "format": {"html": {"theme": "darkly", "pagetitle": "Manuscript review"}},
        "filters": [{"at": "pre-ast", "path": "frontmatter.lua"}],
    }))
    project = setup(tmp_path, author="Reviewer")
    project.reply("c2", "Abstract reply.")
    enable(tmp_path)
    capture_reference(project)
    review_before = (tmp_path / "review.yml").read_bytes()
    config = yaml.safe_load(config_path.read_text())
    assert config["project"]["type"] == "manuscript"
    assert config["format"]["html"]["theme"] == "darkly"
    result = subprocess.run(
        ["quarto", "render", "--to", "html"], cwd=tmp_path,
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    page = html.fromstring((tmp_path / "_output/index.html").read_bytes())
    header = page.get_element_by_id("title-block-header")
    main = page.xpath("//main")[0]
    assert header not in main.iter()
    assert header.xpath('.//div[contains(@class,"quarto-title-banner")]')
    assert header.xpath('.//p[@class="author"]')[0].text_content().strip() == "Manuscript Author"
    assert header.xpath('.//p[@class="affiliation"]')[0].text_content().strip() == "Example University"
    for identifier, container in (("c1", header), ("c2", header), ("c3", main)):
        boundaries = container.xpath(f'.//*[@data-review-id="{identifier}"][@class="qr-boundary"]')
        assert Counter(node.get("data-review-edge") for node in boundaries) == {"S": 1, "E": 1}
    assert header.xpath('.//*[@data-review-kind="I"]')
    assert header.xpath('.//*[@data-review-kind="D"]')
    assert len(page.xpath('//*[@class="qr-thread"]')) == 3
    assert len(page.xpath('//*[@class="qr-reply"]')) == 1
    assert page.xpath('//*[@id="TOC"]//a[@href="#findings"]')
    assert (tmp_path / "index.qmd").read_text() == source
    assert (tmp_path / "review.yml").read_bytes() == review_before
