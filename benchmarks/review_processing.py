"""Measure review preparation and finishing separately from ordinary rendering.

Run from the repository with ``uv run python benchmarks/review_processing.py``.
The temporary manuscript contains 50,000 prose words and 500 comment threads.
One word changes in each of 100 paragraphs after the reference is captured.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path
from statistics import median
from tempfile import TemporaryDirectory
from time import perf_counter

from quarto_review import pandoc
from quarto_review.markup import parse, project
from quarto_review.metadata import ReviewMetadata
from quarto_review.project import capture_reference, setup
from quarto_review.quarto import enable, prepare
from quarto_review.rendering import PreparedRender
from quarto_review.word.exporter import finish_document
from quarto_review.word.package import WordPackage
from quarto_review.word.reader import read_review, visible_text


def measure(operation):
    started = perf_counter()
    result = operation()
    return perf_counter() - started, result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--paragraphs", type=int, default=1000)
    parser.add_argument("--pairs", type=int, default=4)
    arguments = parser.parse_args()
    if arguments.paragraphs < 2 or arguments.pairs < 1:
        parser.error("Use at least two paragraphs and one render pair")
    paragraphs = []
    for number in range(arguments.paragraphs):
        words = [f"p{number}term{index}" for index in range(50)]
        if number % 2 == 0:
            words[10] = (
                "{=="
                + words[10]
                + "==}{>>Check this term.<<}{#c"
                + str(number // 2)
                + "}"
            )
        paragraphs.append(" ".join(words) + ".")
    original = "\n\n".join(paragraphs) + "\n"
    for number in range(0, arguments.paragraphs, 10):
        paragraphs[number] = paragraphs[number].replace(
            f"p{number}term35", f"p{number}revised35"
        )
    current = "\n\n".join(paragraphs) + "\n"
    with TemporaryDirectory(prefix="quarto-review-benchmark-") as folder:
        directory = Path(folder)
        (directory / "index.qmd").write_text(original)
        manuscript = setup(directory, author="Example Author")
        capture_reference(manuscript)
        (directory / "index.qmd").write_text(current)

        def operation():
            return prepare(
                directory, current, path="index.qmd", output="index.docx", format="docx"
            )

        cold_prepare, record = measure(operation)
        cached_prepare = [measure(operation)[0] for _ in range(5)]
        prepared = PreparedRender(
            record["markdown"],
            ReviewMetadata.from_mapping(record["metadata"]),
            record["comments"],
            Counter(record["expected"]),
        )
        path = directory / "marked.docx"
        render_time, _ = measure(
            lambda: pandoc.run(
                ["--from=markdown-smart", "--to=docx", "--output", str(path)],
                source=prepared.markdown,
            )
        )

        def finish():
            return finish_document(WordPackage.read(path), prepared, directory)

        cold_finish, _ = measure(finish)
        cached_finish = [measure(finish)[0] for _ in range(5)]
        result = {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "words": len(project(parse(original).nodes).split()),
            "comment_threads": len(prepared.comments),
            "automatic_changes": len(record["automatic_suggestions"]),
            "cold_prepare_seconds": cold_prepare,
            "cold_finish_seconds": cold_finish,
            "cached_prepare_median_seconds": median(cached_prepare),
            "cached_finish_median_seconds": median(cached_finish),
            "cold_review_overhead_seconds": cold_prepare + cold_finish,
            "cached_review_overhead_seconds": median(cached_prepare)
            + median(cached_finish),
            "ordinary_pandoc_render_seconds_excluded": render_time,
        }
        if shutil.which("quarto"):
            print(
                "Core processing complete; timing full Quarto renders.",
                file=sys.stderr,
                flush=True,
            )
            vanilla = directory / "vanilla"
            vanilla.mkdir()
            (vanilla / "index.qmd").write_text(project(parse(current).nodes))
            (vanilla / "_quarto.yml").write_text(
                "project:\n  type: default\nformat: docx\n"
            )
            enable(directory)
            # Only generated data in this temporary benchmark project is reset.
            shutil.rmtree(directory / ".quarto/review/cache")
            environment = {
                **os.environ,
                "PATH": str(Path(sys.executable).parent)
                + os.pathsep
                + os.environ["PATH"],
            }

            def render(folder):
                completed = subprocess.run(
                    ["quarto", "render", "index.qmd", "--to", "docx"],
                    cwd=folder,
                    env=environment,
                    capture_output=True,
                    text=True,
                )
                if completed.returncode:
                    raise RuntimeError(
                        f"Quarto exited with status {completed.returncode}: {completed.stdout}{completed.stderr}"
                    )
                if os.environ.get("QUARTO_REVIEW_TIMING"):
                    for line in completed.stderr.splitlines():
                        if line.startswith("Quarto review"):
                            print(line, file=sys.stderr, flush=True)

            baseline, review = [], []
            for pair in range(arguments.pairs):
                baseline.append(measure(lambda: render(vanilla))[0])
                print(
                    f"Pair {pair + 1}, ordinary render: {baseline[-1]:.3f}s",
                    file=sys.stderr,
                    flush=True,
                )
                if pair == 0:
                    plain_output = WordPackage.read(vanilla / "index.docx")
                    if (
                        len(
                            visible_text(
                                plain_output.xml("word/document.xml"), "proposed"
                            ).split()
                        )
                        != result["words"]
                    ):
                        raise RuntimeError(
                            "The ordinary render did not retain the benchmark's full text"
                        )
                review.append(measure(lambda: render(directory))[0])
                print(
                    f"Pair {pair + 1}, review render: {review[-1]:.3f}s",
                    file=sys.stderr,
                    flush=True,
                )
                if pair == 0:
                    review_output = WordPackage.read(directory / "index.docx")
                    if (
                        len(
                            visible_text(
                                review_output.xml("word/document.xml"), "proposed"
                            ).split()
                        )
                        != result["words"]
                        or len(read_review(review_output).comments)
                        != result["comment_threads"]
                    ):
                        raise RuntimeError(
                            "The review render did not retain all benchmark text and comments"
                        )
            result.update(
                {
                    "quarto_version": subprocess.check_output(
                        ["quarto", "--version"], text=True
                    ).strip(),
                    "paired_plain_render_seconds": baseline,
                    "paired_review_render_seconds": review,
                    "full_cold_added_seconds": review[0] - baseline[0],
                    "full_cached_added_seconds": median(review[1:])
                    - median(baseline[1:])
                    if len(review) > 1
                    else None,
                }
            )
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
