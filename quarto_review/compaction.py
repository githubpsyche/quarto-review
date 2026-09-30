"""Retire decided prose suggestions without accepting unrelated working edits."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from quarto_review.comparison import compare
from quarto_review.errors import ReviewError
from quarto_review.markup import (
    Boundary,
    Change,
    Comment,
    Highlight,
    Text,
    project,
    walk,
)
from quarto_review.metadata import timestamp
from quarto_review.project import Project, write_text
from quarto_review.source import Source, frontmatter, read, set_review_settings


class _Cleanup:
    def __init__(self, source: Source):
        self.source = source
        self.removed: set[str] = set()
        self.retained: dict[str, str] = {}
        self.boundaries: dict[Boundary, str] = {}
        self.normalize: set[str] = set()
        metadata = source.metadata
        nodes = tuple(walk(source.document.nodes))
        native = (
            set(metadata.objects)
            | {member for obj in metadata.objects.values() for member in obj.revisions}
            | {
                node.id
                for node in nodes
                if isinstance(node, Boundary) and node.id in metadata.suggestions
            }
        )
        for identifier, item in metadata.suggestions.items():
            if item.status != "pending" and identifier in native:
                self.retained[identifier] = (
                    "Required to reproduce native Word formatting or an equation."
                )
        for node in nodes:
            if not isinstance(node, Change) or node.id in native:
                continue
            state = metadata.suggestions[node.id].status
            if state == "pending":
                continue
            discarded = node.before if state == "accepted" else node.after
            children = tuple(walk(discarded))
            blockers = {
                child.id
                for child in children
                if isinstance(child, Change)
                and (
                    child.id in native
                    or metadata.suggestions[child.id].status == "pending"
                )
                or isinstance(child, Boundary)
                and child.id in native
            }
            if blockers:
                self.retained[node.id] = (
                    "Discarded text still contains review records: "
                    + ", ".join(sorted(blockers))
                )
            else:
                self.removed.add(node.id)
                self.normalize.update(
                    child.id for child in children if isinstance(child, Boundary)
                )
        # When a bracketed range loses its text, turn both ends into explicit
        # boundaries. The surviving end may lie outside the decided suggestion.
        counts: dict[str, int] = {}
        for node in nodes:
            if isinstance(node, Boundary) and node.id in self.normalize:
                if node.edge == "start":
                    counts[node.id] = counts.get(node.id, 0) + 1
                number = counts[node.id]
                suffix = "" if number == 1 else f"-{number}"
                self.boundaries[node] = f"[]{{#{node.id}{suffix}-{node.edge}}}"

    def emit(self, nodes, *, undo: set[str] = frozenset()) -> str:
        """Preserve source spelling, thread locations and untouched markup."""
        result = []
        for node in nodes:
            if isinstance(node, Text):
                result.append(node.value)
            elif isinstance(node, Boundary):
                result.append(
                    self.boundaries.get(node, self.source.text[node.start : node.end])
                )
            elif isinstance(node, Comment):
                result.append(self.source.text[node.start : node.end])
            elif isinstance(node, Highlight):
                result.append("{==" + self.emit(node.content, undo=undo) + "==}")
            elif node.id in undo:
                result.append(self.emit(node.before, undo=undo))
            elif node.id in self.removed:
                accepted = (
                    self.source.metadata.suggestions[node.id].status == "accepted"
                )
                chosen, discarded = (
                    (node.after, node.before) if accepted else (node.before, node.after)
                )
                # Preserve all comment and reply anchors, including point
                # comments whose entire quoted passage has just been removed.
                anchors = tuple(
                    child
                    for child in walk(discarded)
                    if isinstance(child, (Boundary, Comment))
                )
                parts = (anchors, chosen) if accepted else (chosen, anchors)
                result.extend(self.emit(part, undo=undo) for part in parts)
            else:
                opening = self.source.text[node.start : node.start + 3]
                before = self.emit(node.before, undo=undo)
                after = self.emit(node.after, undo=undo)
                content = {
                    "{~~": "{~~" + before + "~>" + after + "~~}",
                    "{++": "{++" + after + "++}",
                    "{--": "{--" + before + "--}",
                }[opening]
                start, end = self.source.changes[node.id]
                result.append(content + self.source.text[start:end])
        return "".join(result)


@dataclass(frozen=True)
class Compaction:
    """Verified replacements for the working source and its comparison reference."""

    current: str
    reference: str
    removed: tuple[str, ...]
    retained: dict[str, str]


def plan(source: Source, reference: Source) -> Compaction:
    """Build a cleanup without writing files or altering the supplied models.

    Native decisions and pending suggestions stay attached to their owning
    passage. References containing executed inputs require separate handling;
    rejecting them here avoids silently comparing code output with stale text.
    """
    cleanup = _Cleanup(source)
    if not cleanup.removed:
        return Compaction(source.text, reference.text, (), cleanup.retained)
    if reference.settings.get("compiled"):
        raise ReviewError(
            "Compaction of executed references is not supported yet; no files changed."
        )
    date = timestamp()
    previous = compare(
        source.document,
        reference.document,
        source.metadata,
        reference_id=sha256(reference.text.encode()).hexdigest(),
        date=date,
    )
    current_text = cleanup.emit(source.document.nodes)
    # Undo only automatically detected ordinary edits in the new reference.
    # Explicit pending suggestions retain both alternatives and their identities.
    # Settled decisions become plain text in both files, so they cannot return
    # as new automatic suggestions on the next render.
    reference_text = cleanup.emit(
        previous.document.nodes, undo=set(previous.automatic_ids)
    )
    if "includes" in reference.settings:
        settings = {**source.settings, "includes": reference.settings["includes"]}
        reference_text = set_review_settings(reference_text, settings)
    current, baseline = read(current_text), read(reference_text)
    following = compare(
        current.document,
        baseline.document,
        current.metadata,
        reference_id=sha256(reference_text.encode()).hexdigest(),
        date=date,
    )
    for view in ("original", "proposed"):

        def reading(comparison):
            states = {
                key: item.status
                for key, item in comparison.metadata.suggestions.items()
            }
            text = project(comparison.document.nodes, view, states)
            return text[frontmatter(text)[1] :]

        if reading(previous) != reading(following):
            raise ReviewError(
                f"Compaction changed the {view} reading; no files changed."
            )
    if current.metadata.comments != source.metadata.comments:
        raise ReviewError("Compaction changed a discussion; no files changed.")
    for identifier, item in source.metadata.suggestions.items():
        if (
            item.status == "pending"
            and current.metadata.suggestions.get(identifier) != item
        ):
            raise ReviewError(
                f"Compaction would lose pending suggestion {identifier}; no files changed."
            )
    removed = tuple(
        sorted(source.metadata.suggestions.keys() - current.metadata.suggestions.keys())
    )
    return Compaction(current_text, reference_text, removed, cleanup.retained)


def _save_pair(
    paths: tuple[Path, Path], originals: tuple[str, str], replacements: tuple[str, str]
) -> None:
    """Recheck both inputs; restore the reference if saving the source fails."""

    def unchanged(path, expected):
        if path.read_text(encoding="utf-8") != expected:
            raise ReviewError(
                f"{path}: source changed during compaction; retry against the latest files."
            )

    for path, original in zip(paths, originals, strict=True):
        unchanged(path, original)
    current, reference = paths
    write_text(reference, replacements[1])
    try:
        unchanged(current, originals[0])
        write_text(current, replacements[0])
    except BaseException:
        # Never replace another editor's intervening work during rollback.
        unchanged(reference, replacements[1])
        write_text(reference, originals[1])
        raise


def compact(directory: Path, *, dry_run: bool = False) -> dict:
    """Collapse settled prose changes in a schema-2 project in one bulk action.

    No rendering, Git operation, archival-copy creation or runtime installation
    is performed. Original Word archives are never rewritten.
    """
    manuscript = Project.read(directory)
    if manuscript.source is None:
        raise ReviewError(
            "compact requires schema 2; migrate to a separate candidate first."
        )
    path = manuscript.reference_path()
    if not path.is_file():
        raise ReviewError(
            "Compaction requires the existing comparison reference; no files changed."
        )
    reference = read(path.read_text(encoding="utf-8"))
    result = plan(manuscript.source, reference)
    if result.removed and not dry_run:
        _save_pair(
            (manuscript.directory / "index.qmd", path),
            (manuscript.source.text, reference.text),
            (result.current, result.reference),
        )
        from quarto_review.preview import invalidate

        invalidate(manuscript.directory)
    return {
        "removed": list(result.removed),
        "retained": result.retained,
        "dry_run": dry_run,
        "changed": bool(result.removed) and not dry_run,
    }
