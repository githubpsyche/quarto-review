"""Build and validate the synthetic public demo without altering its sources."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import unquote, urlsplit
from zipfile import ZIP_DEFLATED, ZipFile

from lxml import html

from quarto_review import __version__
from quarto_review.markup import Comment, walk
from quarto_review.project import Project
from quarto_review.quarto import enable
from quarto_review.word.identity import read_identity
from quarto_review.word.package import WordPackage
from quarto_review.word.reader import read_review
from quarto_review.word.validation import validate_package

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples/walkthrough"
SOURCE_FILES = (
    "index.qmd",
    "reference.qmd",
    "_quarto.yml",
    "README.md",
    "references.bib",
)


def verify(directory: Path, project: Project) -> None:
    """Check published links, review bodies, attribution and native Word records."""
    page = html.fromstring((directory / "index.html").read_bytes())
    assert page.xpath('//*[@id="qr-view"]'), "Review controls missing"
    assert f"Built with quarto-review {__version__}" in page.text_content()
    assert (
        json.loads((directory / "downloads/build-info.json").read_text())[
            "package_version"
        ]
        == __version__
    )
    assert page.xpath('//*[@id="qr-thread-c5"]//strong'), "Discussion Markdown missing"
    assert page.xpath('//*[@id="qr-thread-c6"]//*[contains(@class,"qr-body-plain")]'), (
        "Literal discussion missing"
    )
    for path in directory.rglob("*.html"):
        tree = html.fromstring(path.read_bytes())
        for value in tree.xpath("//@href|//@src"):
            url = urlsplit(value)
            if url.scheme or url.netloc or not url.path or url.path.startswith("/"):
                continue
            target = path.parent / unquote(url.path)
            assert target.exists(), f"Missing demo resource: {path.name}: {value}"
    word = WordPackage.read(directory / "index.docx")
    validate_package(word)
    review = read_review(word)
    roots = {
        node.id: node.body
        for node in walk(project.documents["index.qmd"].nodes)
        if isinstance(node, Comment)
    }
    expected = [
        (body, project.metadata.comments[key].author) for key, body in roots.items()
    ]
    expected.extend(
        (reply.body, reply.author)
        for thread in project.metadata.comments.values()
        for reply in thread.replies
    )
    assert sorted((c.text, c.author) for c in review.comments) == sorted(expected), (
        "Word comment text or authors changed"
    )
    assert sum(c.parent_id is not None for c in review.comments) == 4, (
        "Word replies missing"
    )
    citation = next(
        c
        for c in review.comments
        if c.text.startswith("Please check that the second reference")
    )
    assert [anchor.text for anchor in citation.anchors] == ["Smith 2021"], (
        "Citation member target changed"
    )
    addition = page.get_element_by_id("qr-suggestion-s6").text_content()
    assert "2022" in addition and "@smith" not in addition, (
        "Citation addition is not formatted"
    )
    member_ids = {
        item["word_id"]
        for item in read_identity(word)["revisions"]
        if item["id"] == "s6"
    }
    assert len(member_ids) == 1, "Word split the citation addition"
    assert [(r.kind, r.text) for r in review.revisions if r.id in member_ids] == [
        ("ins", ", 2022")
    ], "Word citation addition changed"
    assert any(c.resolved for c in review.comments), "Resolved thread missing"
    assert {r.kind for r in review.revisions} >= {"ins", "del"}, (
        "Tracked changes missing"
    )
    assert set(project.metadata.suggestions) == {"s1", "s2", "s3", "s4", "s5", "s6"}
    assert project.ordinary_changes()["index.qmd"].automatic_ids, (
        "Ordinary edit missing"
    )


def build_info() -> dict:
    """Identify the exact local inputs, including changes outside the last commit."""
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT))
    names = (
        subprocess.check_output(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=ROOT,
        )
        .decode()
        .split("\0")
    )
    digest = sha256()
    for name in sorted(set(filter(None, names))):
        path = ROOT / name
        if path.is_file():
            digest.update(name.encode() + b"\0" + sha256(path.read_bytes()).digest())
    return {
        "package_version": __version__,
        "review_schema": 2,
        "git_commit": commit,
        "working_tree_modified": dirty,
        "source_sha256": digest.hexdigest(),
        "quarto_version": subprocess.check_output(
            ["quarto", "--version"], text=True
        ).strip(),
    }


def build(destination: Path) -> None:
    destination = destination.resolve()
    if destination.exists():
        raise SystemExit(f"Use a fresh output directory: {destination}")
    originals = {name: (EXAMPLE / name).read_bytes() for name in SOURCE_FILES}
    identity = build_info()
    with TemporaryDirectory(prefix="quarto-review-demo-") as temporary:
        project_dir = Path(temporary) / "walkthrough"
        project_dir.mkdir()
        for name, contents in originals.items():
            (project_dir / name).write_bytes(contents)
        downloads = project_dir / "downloads"
        downloads.mkdir()
        (downloads / "build-info.json").write_text(
            json.dumps(identity, indent=2) + "\n"
        )
        build_label = (
            "modified working tree"
            if identity["working_tree_modified"]
            else identity["git_commit"][:12]
        )
        note = f"Built with quarto-review {__version__} ({build_label}). [Build details](downloads/build-info.json).\n\n"
        for name in ("index.qmd", "reference.qmd"):
            path = project_dir / name
            path.write_text(
                path.read_text().replace(
                    "This guide is itself a review document.",
                    note + "This guide is itself a review document.",
                )
            )
        with ZipFile(downloads / "walkthrough.zip", "w", ZIP_DEFLATED) as archive:
            for name, contents in originals.items():
                archive.writestr("walkthrough/" + name, contents)
        project = Project.read(project_dir)
        enable(project_dir)
        environment = dict(os.environ)
        for name in ("QUARTO_REVIEW_PROJECT", "QUARTO_REVIEW_COMMAND", "QUARTO_PANDOC"):
            environment.pop(name, None)
        subprocess.run(
            ["quarto", "render", "index.qmd", "--to", "all"],
            cwd=project_dir,
            env=environment,
            check=True,
        )
        output = project_dir / "_site"
        verify(output, project)
        (output / ".nojekyll").touch()
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(output, destination)
    assert all(
        (EXAMPLE / name).read_bytes() == contents
        for name, contents in originals.items()
    ), "Walkthrough source changed"
    print(f"Validated HTML, Word review records and downloads: {destination}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist/demo")
    build(parser.parse_args().output)
