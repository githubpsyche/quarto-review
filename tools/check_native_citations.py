"""Check one explicitly reconciled synthetic native Word round for this release."""

import argparse
import json
import shutil
import subprocess
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

from quarto_review import __version__
from quarto_review.compaction import compact
from quarto_review.migration import inventory
from quarto_review.project import Project
from quarto_review.quarto import enable
from quarto_review.source import set_review_settings
from quarto_review.word.importer import import_document
from quarto_review.word.package import WordPackage
from quarto_review.word.reader import read_review, visible_text
from quarto_review.word.validation import validate_package

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "work/native-citations"
BIB = "native-word-citations.bib"
BODIES = {
    "c1": "Please qualify the magnitude.",
    "c2": "Please check the second reference.",
    "c3": "Keep this reviewed reference entry.",
}
REPLIES = {
    "c1": "The revised magnitude addresses my concern.",
    "c2": "The second reference is correct.",
}


def render(directory: Path) -> WordPackage:
    enable(directory)
    subprocess.run(
        ["quarto", "render", "index.qmd", "--to", "all", "--quiet"],
        cwd=directory,
        check=True,
    )
    package = WordPackage.read(directory / "index.docx")
    validate_package(package)
    return package


def fingerprint() -> str:
    digest = sha256()
    for path in sorted((ROOT / "quarto_review").rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts:
            digest.update(
                str(path.relative_to(ROOT)).encode()
                + b"\0"
                + sha256(path.read_bytes()).digest()
            )
    return digest.hexdigest()


def details(package: WordPackage) -> dict:
    review = read_review(package)
    return {
        "original": visible_text(package.xml("word/document.xml"), "original"),
        "proposed": visible_text(package.xml("word/document.xml"), "proposed"),
        "comments": [
            (
                c.id,
                c.text,
                c.author,
                c.date,
                c.parent_id,
                c.resolved,
                [a.text for a in c.anchors],
            )
            for c in review.comments
        ],
        "revisions": [
            (r.id, r.kind, r.text, r.author, r.date) for r in review.revisions
        ],
    }


def prepare() -> None:
    """Save the synthetic version sent and retain a newer local working edit."""
    assert not WORK.exists(), "Use a fresh directory"
    active = WORK / "working"
    active.mkdir(parents=True)
    source = (ROOT / "tests/fixtures/native-word-citations.qmd").read_text()
    for name in ("index.qmd", "reference.qmd"):
        (active / name).write_text(source)
    shutil.copyfile(ROOT / "tests/fixtures" / BIB, active / BIB)
    sent = render(active)
    shutil.copyfile(active / "index.docx", WORK / "sent.docx")
    (WORK / "sent.qmd").write_text(source)
    (active / "index.qmd").write_text(
        source.replace("The follow-up was brief.", "The follow-up lasted two days.")
    )
    report = {
        "version": __version__,
        "library_sha256": fingerprint(),
        "sent_sha256": sha256((WORK / "sent.docx").read_bytes()).hexdigest(),
        "sent": details(sent),
        "stage": "prepared",
    }
    (WORK / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print("Prepared:", WORK / "sent.docx")


def reconcile() -> None:
    """Check this fixture's Word decisions before explicit reconciliation and cleanup."""
    active = WORK / "working"
    before = {
        name: (active / name).read_bytes()
        for name in ("index.qmd", "reference.qmd", BIB)
    }
    returned_path = WORK / "returned-native.docx"
    returned = WordPackage.read(returned_path)
    validate_package(returned)
    received = read_review(returned)
    assert not received.revisions, [(r.kind, r.text) for r in received.revisions]
    assert "a modest effect" in visible_text(returned.xml("word/document.xml"))
    roots = {c.text.strip(): c for c in received.comments if c.parent_id is None}
    assert set(roots) == set(BODIES.values()), list(roots)
    assert roots[BODIES["c2"]].anchors[0].text == "Smith 2021", roots[
        BODIES["c2"]
    ].anchors
    for identifier in ("c1", "c2"):
        parent = roots[BODIES[identifier]]
        assert parent.resolved
        replies = [c for c in received.comments if c.parent_id == parent.id]
        assert len(replies) == 1 and replies[0].text.strip() == REPLIES[identifier], (
            replies
        )
        assert replies[0].author and replies[0].date
    assert not roots[BODIES["c3"]].resolved
    # The reviewer's rejection removes the added year from the citation group,
    # while the separate reviewed reference list intentionally retains its entry.
    paragraph = next(
        p
        for p in returned.xml("word/document.xml").iter(
            "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"
        )
        if "Evidence " in visible_text(p)
    )
    assert "2021" in visible_text(paragraph) and "2022" not in visible_text(paragraph)
    candidate = WORK / "feedback-candidate"
    import_document(
        returned_path,
        candidate,
        author="Example Author",
        single_source=True,
        bibliography=active / BIB,
    )
    assert all((active / name).read_bytes() == data for name, data in before.items())
    incoming = Project.read(candidate)
    current = Project.read(active)
    current.decide("s1", "accept")
    Project.read(active).decide("s2", "reject")
    current = Project.read(active)
    for identifier, body in BODIES.items():
        matches = [
            key
            for key, node in incoming.documents["index.qmd"].annotations().items()
            if getattr(node, "body", "").strip() == body
        ]
        assert len(matches) == 1, (identifier, matches)
        thread = incoming.metadata.comments[matches[0]]
        replies = tuple(
            replace(reply, id="r" + identifier[1:], parent_id=identifier)
            for reply in thread.replies
        )
        current.metadata.comments[identifier] = replace(thread, replies=replies)
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
    pre_cleanup = render(active)
    unchanged_archives = {
        str(path): path.read_bytes() for path in active.glob("assets/review/*.docx")
    }
    preview = compact(active, dry_run=True)
    assert preview["removed"] == ["s0", "s1", "s2"], preview
    result = compact(active)
    assert result["removed"] == ["s0", "s1", "s2"] and not result["retained"], result
    post_cleanup = render(active)
    before_details, after_details = details(pre_cleanup), details(post_cleanup)
    # Ordinary edits receive a render-time timestamp. Their wording, IDs and
    # attribution must stay identical; fixed discussion dates remain exact.
    before_revisions = before_details.pop("revisions")
    after_revisions = after_details.pop("revisions")
    assert before_details == after_details, (before_details, after_details)
    assert [r[:4] for r in before_revisions] == [r[:4] for r in after_revisions]
    assert all(r[4] for r in before_revisions + after_revisions)
    assert all(
        Path(name).read_bytes() == data for name, data in unchanged_archives.items()
    )
    final = Project.read(active)
    assert not final.metadata.suggestions
    assert len(final.ordinary_changes()["index.qmd"].automatic_ids) >= 1
    assert "The follow-up lasted two days." in final.source.text
    assert "The follow-up was brief." in (active / "reference.qmd").read_text()
    assert "@smith2021" in final.source.text and "@smith2022" not in final.source.text
    assert "A reviewed reference entry" in final.source.text
    assert (active / BIB).read_bytes() == before[BIB]
    shutil.copyfile(active / "index.docx", WORK / "reconciled.docx")
    report = json.loads((WORK / "report.json").read_text())
    assert report["library_sha256"] == fingerprint()
    report.update(
        {
            "stage": "reconciled",
            "returned_sha256": sha256(returned_path.read_bytes()).hexdigest(),
            "reconciled": details(post_cleanup),
            "compaction": result,
            "citation_import": json.loads(
                (candidate / ".quarto/review/citation-import.json").read_text()
            ),
        }
    )
    (WORK / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(
        "PASS: native return, citation targets, explicit reconciliation, cleanup, and retained local edit"
    )
    print("Reopen and save:", WORK / "reconciled.docx")


def verify() -> None:
    """Verify the second Word save and import it without changing the working files."""
    path = WORK / "reopened-native.docx"
    package = WordPackage.read(path)
    validate_package(package)
    report = json.loads((WORK / "report.json").read_text())
    assert report["library_sha256"] == fingerprint()
    expected = report["reconciled"]
    actual = details(package)
    assert actual["original"] == expected["original"]
    assert actual["proposed"] == expected["proposed"]
    # Word may renumber native comment IDs. Require a unique complete record
    # match and preserve the parent graph under that one-to-one mapping.
    expected_comments = expected["comments"]
    assert len(actual["comments"]) == len(expected_comments)
    identities = {}
    for comment in actual["comments"]:
        matches = [
            c
            for c in expected_comments
            if list(comment[1:4]) == c[1:4] and [comment[5], comment[6]] == c[5:]
        ]
        assert len(matches) == 1, (comment, matches)
        identities[comment[0]] = matches[0][0]
    assert len(set(identities.values())) == len(expected_comments)
    assert all(c[4] is None or c[4] in identities for c in actual["comments"])
    normalized = [
        [identities[c[0]], *c[1:4], identities.get(c[4]), *c[5:]]
        for c in actual["comments"]
    ]
    assert normalized == expected_comments

    def minute(records):
        return [
            (kind, text, author, date[:16] if date else date)
            for identifier, kind, text, author, date in records
        ]

    assert minute(actual["revisions"]) == minute(expected["revisions"]), (
        actual["revisions"],
        expected["revisions"],
    )
    assert "The follow-up lasted two days." in actual["proposed"]
    candidate = WORK / "reopened-candidate"
    before = {
        name: (WORK / "working" / name).read_bytes()
        for name in ("index.qmd", "reference.qmd", BIB)
    }
    import_document(
        path,
        candidate,
        author="Example Author",
        single_source=True,
        bibliography=WORK / "working" / BIB,
    )
    assert all(
        (WORK / "working" / name).read_bytes() == data for name, data in before.items()
    )
    imported = Project.read(candidate)
    values = inventory(imported.documents["index.qmd"], imported.metadata)
    assert "The follow-up lasted two days." in values["proposed"]["text"]
    assert len(imported.metadata.comments) == 3
    assert sum(len(c.replies) for c in imported.metadata.comments.values()) == 2
    report.update(
        {
            "stage": "passed",
            "final_sha256": sha256(path.read_bytes()).hexdigest(),
            "word_revision_dates_compared_to_minute": True,
            "word_comment_id_mapping": identities,
        }
    )
    (WORK / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(
        "PASS: reopened native Word save and independent import preserve readings, citation targets, replies, resolution and pending local changes"
    )
    print("Final SHA-256:", report["final_sha256"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("prepare", "reconcile", "verify"))
    parser.add_argument("--output", type=Path, default=WORK)
    arguments = parser.parse_args()
    WORK = arguments.output.resolve()
    globals()[arguments.phase]()
