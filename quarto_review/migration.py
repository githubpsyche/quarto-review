"""Create and verify candidate conversions without changing the original project."""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory

from quarto_review.errors import ReviewError
from quarto_review.markup import (
    Boundary,
    Change,
    Comment,
    Highlight,
    Text,
    parse,
    project,
)
from quarto_review.metadata import ReviewMetadata
from quarto_review.project import Project, write_text
from quarto_review.source import from_legacy, frontmatter, read


def inventory(document, metadata):
    """Semantic source inventory, including exact range positions in both views."""
    result = {"comments": {}, "suggestions": {}, "objects": asdict(metadata)["objects"]}
    for identifier, node in document.annotations().items():
        if isinstance(node, Comment):
            result["comments"][identifier] = {
                "body": node.body.rstrip("\n"),
                **asdict(metadata.comments[identifier]),
            }
        elif isinstance(node, Change):
            result["suggestions"][identifier] = {
                "before": project(node.before, "original"),
                "after": project(node.after, "proposed"),
            }
    result["decisions"] = asdict(metadata)["suggestions"]
    result["review-author"] = metadata.author
    result["created_at"] = metadata.created_at
    result["imports"] = metadata.imports
    result["manuscript_metadata"] = {
        key: value
        for key, value in frontmatter(document.source)[0].items()
        if key != "review"
    }
    # Retain word boundaries, code whitespace and anchor text. Only the outer
    # blank lines introduced by attaching metadata/thread blocks are ignored.
    for view in ("original", "proposed"):
        pieces, anchors, active = [], {}, {}
        count = 0

        def emit(value):
            nonlocal count
            if not pieces:
                value = re.sub(
                    r"\A---\n.*?\n(?:---|\.\.\.)[ \t]*(?:\n|$)", "", value, flags=re.S
                )
            pieces.append(value)
            count += len(value)

        def visit(nodes):
            for node in nodes:
                if isinstance(node, Text):
                    emit(node.value)
                elif isinstance(node, Boundary):
                    if node.edge == "start":
                        active[node.id] = count
                    elif node.id in active:
                        anchors.setdefault(node.id, []).append(
                            (active.pop(node.id), count)
                        )
                elif isinstance(node, Comment):
                    start = count
                    visit(node.content)
                    if node.content:
                        anchors.setdefault(node.id, []).append((start, count))
                elif isinstance(node, Highlight):
                    visit(node.content)
                elif isinstance(node, Change):
                    item = metadata.suggestions.get(node.id)
                    status = item.status if item else "pending"
                    after = (
                        status == "accepted"
                        or status == "pending"
                        and view == "proposed"
                    )
                    visit(node.after if after else node.before)

        visit(document.nodes)
        raw = "".join(pieces)
        leading = len(raw) - len(raw.lstrip("\r\n"))
        result[view] = {
            "text": raw.strip("\r\n"),
            "anchors": {
                key: [
                    (start - leading, end - leading, raw[start:end])
                    for start, end in ranges
                ]
                for key, ranges in anchors.items()
            },
        }
    return result


def convert_verified(document, metadata):
    text = from_legacy(document, metadata)
    model = read(text, document.path)
    if inventory(document, metadata) != inventory(model.document, model.metadata):
        raise ReviewError(
            f"{document.path}: conversion changed manuscript or review semantics; no candidate was published"
        )
    return text


def migrate(directory: Path, destination: Path) -> dict:
    directory, destination = directory.resolve(), destination.resolve()
    if destination.exists() or destination.is_relative_to(directory):
        raise ReviewError("Choose a new candidate directory outside the source project")
    original = Project.read(directory)
    if original.source is not None:
        raise ReviewError("This project already uses the single-source format")
    if original.metadata.sources != ("index.qmd",):
        raise ReviewError("Single-source conversion requires one index.qmd")
    inputs = [directory / "index.qmd", directory / "review.yml"]
    reference = directory / "review/reference"
    if (
        not (reference / "index.qmd").is_file()
        or not (reference / "review.yml").is_file()
    ):
        raise ReviewError(
            "The legacy project must have its frozen source and review metadata"
        )
    inputs += [reference / "index.qmd", reference / "review.yml"]
    hashes = {
        str(p.relative_to(directory)): sha256(p.read_bytes()).hexdigest()
        for p in inputs
    }
    if (
        sha256(original.documents["index.qmd"].source.encode()).hexdigest()
        != hashes["index.qmd"]
    ):
        raise ReviewError(
            "Source changed during conversion; retry from the latest files"
        )
    # Re-read after fingerprints are captured so the final guard covers metadata too.
    original = Project.read(directory)
    current = convert_verified(original.documents["index.qmd"], original.metadata)
    old_meta = ReviewMetadata.read(reference / "review.yml")
    frozen = convert_verified(
        parse((reference / "index.qmd").read_text(), "index.qmd"), old_meta
    )
    manifest_path = reference / "manifest.json"
    if manifest_path.exists():
        from quarto_review.source import set_review_settings

        manifest = json.loads(manifest_path.read_text())
        compiled = {}
        for key, name in manifest.get("compiled", {}).items():
            path = (reference / name).resolve()
            if not path.is_relative_to(reference) or not path.is_file():
                raise ReviewError("Missing or external executed reference input")
            inputs.append(path)
            hashes[str(path.relative_to(directory))] = sha256(
                path.read_bytes()
            ).hexdigest()
            compiled[key.split(":", 1)[1]] = convert_verified(
                parse(path.read_text(), "index.qmd"), old_meta
            )
        if compiled:
            settings = read(frozen).settings
            settings["compiled"] = compiled
            settings["includes"] = manifest.get("includes", [])
            frozen = set_review_settings(frozen, settings)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(
        prefix=".review-conversion-", dir=destination.parent
    ) as folder:
        candidate = Path(folder) / "candidate"
        candidate.mkdir()
        write_text(candidate / "index.qmd", current)
        write_text(candidate / "reference.qmd", frozen)
        # Only immutable native source dependencies are copied, not another active project.
        required = set()
        for metadata in (original.metadata, old_meta):
            required.update(metadata.imports.values())
            required.update(item.source for item in metadata.objects.values())
            for item in [
                *metadata.comments.values(),
                *metadata.suggestions.values(),
                *(
                    reply
                    for thread in metadata.comments.values()
                    for reply in thread.replies
                ),
            ]:
                if item.provenance.get("source"):
                    required.add(item.provenance["source"])
        for name in sorted(required):
            if Path(name).is_absolute() or ".." in Path(name).parts:
                raise ReviewError(
                    f"Native source assets must use project-relative paths: {name}"
                )
            path = (directory / name).resolve()
            if not path.is_relative_to(directory) or not path.is_file():
                raise ReviewError(
                    f"Missing or external native source dependency: {name}"
                )
            target = candidate / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
        if any(
            sha256(p.read_bytes()).hexdigest() != hashes[str(p.relative_to(directory))]
            for p in inputs
        ):
            raise ReviewError(
                "Source changed during conversion; regenerate from the latest files"
            )
        report = {
            "source": str(directory),
            "input_sha256": hashes,
            "verified": [
                "manuscript projections",
                "suggestion wording",
                "comment anchors",
                "comment text",
                "replies",
                "attribution",
                "decisions",
                "native identities",
            ],
            "candidate": str(destination),
            "switched": False,
            "note": "Candidate review sources only; manuscript configuration and other render dependencies remain in the original project.",
        }
        write_text(
            candidate / "migration-report.json", json.dumps(report, indent=2) + "\n"
        )
        candidate.rename(destination)
    return report
