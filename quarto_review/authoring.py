"""Add review annotations and register hand-written CriticMarkup safely."""

from __future__ import annotations

import re
from pathlib import Path

from quarto_review.errors import ReviewError
from quarto_review.markup import Change, Comment, Text, parse, walk
from quarto_review.metadata import (
    CommentMetadata,
    ReviewMetadata,
    SuggestionMetadata,
    timestamp,
)
from quarto_review.project import Project, write_text


def unused_id(metadata: ReviewMetadata, prefix: str) -> str:
    identifiers = (
        set(metadata.comments) | set(metadata.suggestions) | set(metadata.objects)
    )
    identifiers.update(
        reply.id for thread in metadata.comments.values() for reply in thread.replies
    )
    number = 1
    while f"{prefix}{number}" in identifiers:
        number += 1
    return f"{prefix}{number}"


def escape_comment(body: str) -> str:
    return re.sub(r"([\\`*_{}\[\]<>])", r"\\\1", body)


def annotate(
    project: Project,
    source: str,
    text: str,
    *,
    body: str | None = None,
    replacement: str | None = None,
    before: str | None = None,
    start: int | None = None,
    author: str | None = None,
) -> str:
    """Annotate one exact source passage without guessing among repeated matches.

    Supplying before groups an already-made edit. Otherwise replacement proposes
    new wording. An optional character offset disambiguates repeated passages.
    """
    if source not in project.documents:
        raise ReviewError(f"No registered source named {source}")
    if (body is None) == (replacement is None and before is None):
        raise ReviewError("Provide either a comment body or suggested wording")
    if not text:
        raise ReviewError("Select a nonempty source passage to anchor the annotation")
    document = project.documents[source]
    positions = [
        match.start() for match in re.finditer(re.escape(text), document.source)
    ]
    if start is not None:
        positions = [position for position in positions if position == start]
    if len(positions) != 1:
        raise ReviewError(
            f"The selected passage has {len(positions)} matches in {source}; provide its exact start offset"
        )
    offset = positions[0]
    if not any(
        isinstance(node, Text)
        and node.start <= offset
        and node.end >= offset + len(text)
        for node in walk(document.nodes)
    ):
        raise ReviewError(
            "The selected passage crosses an existing annotation; reconcile its boundaries before grouping"
        )
    if project.source is not None:
        from dataclasses import asdict
        from uuid import uuid4

        from quarto_review.source import attr_text

        identifier = ("c" if body is not None else "s") + uuid4().hex[:12]
        model = project.source
        selected = author or project.metadata.author
        if body is not None:
            if not body.strip():
                raise ReviewError("An initial comment cannot be empty")
            item = CommentMetadata(selected, timestamp(), body_format="markdown")
            markup = "[" + text + "]" + attr_text(identifier)
            block = model.thread_text(identifier, item, body)
        else:
            old, new = (text, replacement) if before is None else (before, text)
            if old == new:
                raise ReviewError("Suggested wording must differ from its original")
            project.metadata.suggestions[identifier] = SuggestionMetadata(
                selected, timestamp()
            )
            markup = (
                "{~~"
                + old
                + "~>"
                + new
                + "~~}"
                + model.change_suffix(identifier, project.metadata)
            )
            block = ""
        edits = [(offset, offset + len(text), markup)]
        if block:
            edits.append((len(model.text), len(model.text), "\n\n" + block))
        model = model.save(project.directory / source, model.apply(edits))
        project.source = model
        project.documents = {source: model.document}
        project.metadata = ReviewMetadata.from_mapping(asdict(model.metadata))
        return identifier
    identifier = unused_id(project.metadata, "c" if body is not None else "s")
    date = timestamp()
    selected_author = author or project.metadata.author
    if body is not None:
        if not body.strip():
            raise ReviewError("An initial comment cannot be empty")
        markup = (
            "{==" + text + "==}{>>" + escape_comment(body) + "<<}{#" + identifier + "}"
        )
        project.metadata.comments[identifier] = CommentMetadata(selected_author, date)
    else:
        old, new = (text, replacement) if before is None else (before, text)
        if old == new:
            raise ReviewError("Suggested wording must differ from its original")
        markup = "{~~" + old + "~>" + new + "~~}{#" + identifier + "}"
        project.metadata.suggestions[identifier] = SuggestionMetadata(
            selected_author, date
        )
    revised = document.source[:offset] + markup + document.source[offset + len(text) :]
    project.documents[source] = parse(revised, source)
    project.metadata.validate(project.documents)
    write_text(project.directory / source, revised)
    project.save_metadata()
    return identifier


def synchronize(directory: Path, *, author: str | None = None) -> dict:
    """Register new typed annotations; missing existing records remain errors."""
    directory = directory.resolve()
    from quarto_review.source import is_single

    path = directory / "index.qmd"
    if path.is_file() and is_single(path.read_text()):
        project = Project.read(directory)
        return {
            "added": [],
            "validated": len(project.metadata.comments)
            + len(project.metadata.suggestions),
        }
    metadata = ReviewMetadata.read(directory / "review.yml")
    documents = {}
    added = []
    for source in metadata.sources:
        path = (directory / source).resolve()
        if not path.is_relative_to(directory):
            raise ReviewError(f"Source escapes the project: {source}")
        document = parse(path.read_text(), source)
        edits = []
        for node in walk(document.nodes):
            if not isinstance(node, (Change, Comment)):
                continue
            collection = (
                metadata.comments if isinstance(node, Comment) else metadata.suggestions
            )
            if node.id in collection or node.id in metadata.objects:
                continue
            identifier = node.id or unused_id(
                metadata, "c" if isinstance(node, Comment) else "s"
            )
            if node.id is None:
                edits.append((node.end, "{#" + identifier + "}"))
            cls = CommentMetadata if isinstance(node, Comment) else SuggestionMetadata
            collection[identifier] = cls(author or metadata.author, timestamp())
            added.append(identifier)
        revised = document.source
        for offset, insertion in sorted(edits, reverse=True):
            revised = revised[:offset] + insertion + revised[offset:]
        documents[source] = parse(revised, source)
    metadata.validate(documents)
    for source, document in documents.items():
        write_text(directory / source, document.source)
    metadata.write(directory / "review.yml")
    return {"added": added}
