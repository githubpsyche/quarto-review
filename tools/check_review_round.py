"""Demonstrate explicit schema-2 reconciliation on synthetic review documents.

The returned file is generated from scripted reviewer choices, not by Word.
This validates the documented workflow but is not native application evidence.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

from quarto_review.migration import inventory
from quarto_review.project import Project
from quarto_review.quarto import enable
from quarto_review.source import set_review_settings
from quarto_review.word.importer import import_document
from quarto_review.word.package import WordPackage
from quarto_review.word.reader import read_review, visible_text
from quarto_review.word.validation import validate_package

SOURCE = """---
title: Synthetic review round
author: Example Author
review:
  schema: 2
  author: A
  authors:
    A: Example Author
    R: Example Reviewer
---

The study found [a {~~large~>modest~~}{#s1 by=A at=2026-09-01T09:00:00Z} effect]{#c1}.
The follow-up was brief.

:::: {.review-thread #c1 by=R at=2026-09-01T08:00:00Z}
Please qualify the magnitude.
::::
"""
REPLY = "The revised magnitude addresses my concern."
DATE = "2026-09-02T10:00:00Z"


def render(directory: Path) -> Path:
    enable(directory)
    subprocess.run(
        ["quarto", "render", "index.qmd", "--to", "docx", "--quiet"],
        cwd=directory,
        check=True,
    )
    path = directory / "index.docx"
    validate_package(WordPackage.read(path))
    return path


def run(destination: Path) -> None:
    destination = destination.resolve()
    if destination.exists():
        raise SystemExit(f"Choose a fresh output directory: {destination}")
    active = destination / "working"
    active.mkdir(parents=True)
    for name in ("index.qmd", "reference.qmd"):
        (active / name).write_text(SOURCE)
    sent = render(active)
    shutil.copyfile(sent, destination / "sent.docx")
    (destination / "sent.qmd").write_text(SOURCE)

    # Generate a deterministic stand-in for two reviewer actions in Word.
    reviewer = destination / "scripted-reviewer"
    reviewer.mkdir()
    returned_source = SOURCE.replace("#s1 by=A", "#s1 .accepted by=A").replace(
        ".review-thread #c1 by=R", ".review-thread #c1 .resolved by=R"
    )
    returned_source = returned_source.replace(
        "\n::::\n", f"\n\n::: {{.reply #r1 by=R at={DATE}}}\n{REPLY}\n:::\n::::\n"
    )
    (reviewer / "index.qmd").write_text(returned_source)
    (reviewer / "reference.qmd").write_text(SOURCE)
    shutil.copyfile(render(reviewer), destination / "returned.docx")

    # Work continued while the reviewer had the sent draft.
    local = SOURCE.replace("The follow-up was brief.", "The follow-up lasted two days.")
    (active / "index.qmd").write_text(local)
    before = {
        name: (active / name).read_bytes() for name in ("index.qmd", "reference.qmd")
    }
    candidate = destination / "feedback-candidate"
    import_document(
        destination / "returned.docx",
        candidate,
        author="Example Author",
        single_source=True,
    )
    assert all((active / name).read_bytes() == data for name, data in before.items())
    incoming = Project.read(candidate)
    matching = [
        key
        for key, node in incoming.documents["index.qmd"].annotations().items()
        if getattr(node, "body", "").strip() == "Please qualify the magnitude."
    ]
    assert len(matching) == 1
    thread = incoming.metadata.comments[matching[0]]
    assert thread.status == "resolved"
    assert len(thread.replies) == 1 and thread.replies[0].body == REPLY
    assert thread.replies[0].author == "Example Reviewer"
    assert thread.replies[0].date == DATE
    assert not incoming.metadata.suggestions, "Reviewer accepted the only suggestion"

    # These are explicit, case-specific decisions, not an automatic merge.
    current = Project.read(active)
    current.decide("s1", "accept")
    current = Project.read(active)
    current.metadata.comments["c1"] = replace(
        thread, replies=(replace(thread.replies[0], id="r1", parent_id="c1"),)
    )
    for archive in incoming.metadata.imports.values():
        target = active / archive
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(candidate / archive, target)
    updated = current.source.updated(current.metadata)
    updated = set_review_settings(
        updated,
        {
            **current.source.settings,
            "authors": current.source.authors,
            "imports": {
                **current.source.settings.get("imports", {}),
                **incoming.metadata.imports,
            },
        },
    )
    current.source.save(active / "index.qmd", updated)
    final = Project.read(active)
    values = inventory(final.documents["index.qmd"], final.metadata)
    assert "a modest effect" in values["proposed"]["text"]
    assert "The follow-up lasted two days." in values["proposed"]["text"]
    assert (
        final.metadata.comments["c1"].replies[0].provenance
        == thread.replies[0].provenance
    )
    assert (active / "reference.qmd").read_bytes() == before["reference.qmd"]
    package = WordPackage.read(render(active))
    review = read_review(package)
    reply = next(item for item in review.comments if item.parent_id is not None)
    assert (reply.text, reply.author, reply.date) == (REPLY, "Example Reviewer", DATE)
    parent = next(item for item in review.comments if item.id == reply.parent_id)
    assert parent.resolved
    assert parent.anchors and "modest" in parent.anchors[0].text
    assert "The follow-up lasted two days." in visible_text(
        package.xml("word/document.xml"), "proposed"
    )
    shutil.copyfile(active / "index.docx", destination / "reconciled.docx")
    report = {
        "result": "passed",
        "native_word_application_test": False,
        "checks": [
            "candidate import leaves current source unchanged",
            "explicit acceptance and thread resolution",
            "reply authorship, date, provenance and parent retained",
            "concurrent local prose edit retained",
            "frozen reference unchanged",
            "second Word export validated",
        ],
    }
    (destination / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"PASS: explicit review round; artifacts in {destination}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args().output)
