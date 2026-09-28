"""Render the synthetic HTML-only fixture for review-panel interaction checks."""

import argparse
import subprocess
from pathlib import Path

from quarto_review.quarto import enable


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default="tests/fixtures/review-panel.qmd")
    parser.add_argument("--output", default="work/review-panel")
    args = parser.parse_args()
    directory = (root / args.output).resolve()
    if not directory.is_relative_to(root / "work"):
        parser.error("Fixture output must be inside this repository's work directory")
    directory.mkdir(parents=True, exist_ok=True)
    source = (root / args.source).read_text()
    for name in ("index.qmd", "reference.qmd"):
        (directory / name).write_text(source)
    (directory / "_quarto.yml").write_text(
        "project:\n  type: manuscript\n  output-dir: _output\n"
        "manuscript:\n  article: index.qmd\n  code-links: false\n"
        "format:\n  html:\n    theme: darkly\n    toc: false\n"
    )
    enable(directory)
    subprocess.run(
        ["quarto", "render", "index.qmd", "--to", "html", "--quiet"],
        cwd=directory, check=True,
    )
    assert (directory / "index.qmd").read_text() == source
    assert (directory / "reference.qmd").read_text() == source
    print(directory / "_output/index.html")


if __name__ == "__main__":
    main()
