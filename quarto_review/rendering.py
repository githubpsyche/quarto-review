"""Prepare source annotations for conversion without changing authoring files."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Literal

from quarto_review.errors import ReviewError
from quarto_review.markers import PATTERN, marker
from quarto_review.markup import (
    Boundary,
    Change,
    Comment,
    Document,
    Highlight,
    Node,
    Text,
    project,
    walk,
)
from quarto_review.metadata import ReviewMetadata

__all__ = ["PreparedRender", "prepare_render"]


@dataclass(frozen=True)
class PreparedRender:
    """Conversion source and the boundary inventory required to verify it."""

    markdown: str
    metadata: ReviewMetadata
    comments: dict[str, str]
    expected: Counter[str]
    suggestions: dict[str, tuple[str, str]] = field(default_factory=dict)


def prepare_render(
    document: Document,
    metadata: ReviewMetadata,
    *,
    view: Literal["review", "original", "proposed"] = "review",
    native_objects: bool = True,
    directory: Path | None = None,
) -> PreparedRender:
    """Keep review boundaries visible to a converter and bodies outside prose.

    The intermediate markers contain no Markdown punctuation. The Word
    finisher consumes them and checks that each appears exactly once. Clean
    projections require no finisher and contain no review markers.
    """
    if view not in {"review", "original", "proposed"}:
        raise ReviewError(f"Unknown render view {view}")
    if PATTERN.search(document.source):
        raise ReviewError(
            f"{document.path}: source contains a reserved conversion marker"
        )
    metadata.validate({document.path: document})
    decisions = {
        identifier: item.status for identifier, item in metadata.suggestions.items()
    }
    comments = {
        node.id: node.body for node in walk(document.nodes) if isinstance(node, Comment)
    }
    if None in comments:
        raise ReviewError(
            f"{document.path}: assign identifiers to initial comments before rendering"
        )
    for node in walk(document.nodes):
        if isinstance(node, Change) and node.id is None:
            raise ReviewError(
                f"{document.path}: assign identifiers to suggestions before rendering"
            )
    equation_views = {}
    partial_equations = []
    for node in walk(document.nodes):
        if not isinstance(node, Change) or node.id not in metadata.objects:
            continue
        before, after = project(node.before, "original"), project(node.after)
        item = metadata.objects[node.id]
        if item.source_hash != sha256((before + "\0" + after).encode()).hexdigest():
            raise ReviewError(
                f"Equation {node.id} has changed while native revisions remain attached; reconcile its review records before exporting"
            )
        states = {metadata.suggestions[member].status for member in item.revisions}
        if view == "review" and native_objects or states == {"pending"}:
            continue
        if states in ({"accepted"}, {"rejected"}):
            selected = after if states == {"accepted"} else before
            equation_views[node.id] = selected, selected
        else:
            partial_equations.append(node.id)
    if partial_equations:
        if directory is None:
            raise ReviewError(
                f"Equation {partial_equations[0]}: partial decisions require the project directory to project native revisions"
            )
        from quarto_review.word.equations import decided_views

        equation_views.update(decided_views(metadata, directory))

    def clean(nodes):
        pieces = []
        for node in nodes:
            if isinstance(node, Change) and node.id in equation_views:
                pieces.append(equation_views[node.id][0 if view == "original" else 1])
            elif isinstance(node, Change):
                state = decisions.get(node.id, "pending")
                use_after = (
                    state == "accepted" or state == "pending" and view == "proposed"
                )
                pieces.append(clean(node.after if use_after else node.before))
            elif isinstance(node, (Highlight, Comment)):
                pieces.append(clean(node.content))
            elif isinstance(node, Text):
                pieces.append(node.value)
        return "".join(pieces)

    if view != "review":
        return PreparedRender(clean(document.nodes), metadata, comments, Counter())

    ranged = {node.id for node in walk(document.nodes) if isinstance(node, Boundary)}
    reply_ids = {
        reply.id for item in metadata.comments.values() for reply in item.replies
    }
    expected: Counter[str] = Counter()

    def boundary(kind: str, identifier: str, edge: str) -> str:
        token = marker(kind, identifier, edge)
        expected[token] += 1
        return token

    def marked(kind: str, identifier: str, content: str) -> str:
        start, end = boundary(kind, identifier, "S"), boundary(kind, identifier, "E")
        if "\n\n" in content or content.startswith(
            ("# ", "## ", "```", "~~~", "| ", "- ")
        ):
            return "\n\n" + start + "\n\n" + content + "\n\n" + end + "\n\n"
        return start + content + end

    def render(nodes: tuple[Node, ...]) -> str:
        pieces = []
        for node in nodes:
            if isinstance(node, Text):
                pieces.append(node.value)
            elif isinstance(node, Boundary):
                if node.id in metadata.comments or node.id in reply_ids:
                    kind = "C"
                elif node.id in metadata.suggestions:
                    kind = "F"
                else:
                    raise ReviewError(f"Range {node.id} has no review metadata")
                pieces.append(
                    boundary(kind, node.id, "S" if node.edge == "start" else "E")
                )
            elif isinstance(node, Highlight):
                pieces.append(render(node.content))
            elif isinstance(node, Comment):
                content = render(node.content)
                pieces.append(
                    content if node.id in ranged else marked("C", node.id, content)
                )
            elif node.id in metadata.objects:
                original, proposed = equation_views.get(
                    node.id,
                    (project(node.before, "original"), project(node.after, "proposed")),
                )
                if native_objects or original == proposed:
                    pieces.append(marked("O", node.id, proposed))
                else:
                    pieces.append(
                        marked("D", node.id, original) + marked("I", node.id, proposed)
                    )
            elif node.id in ranged:
                if node.before or node.after:
                    raise ReviewError(
                        f"Property suggestion {node.id} unexpectedly contains prose"
                    )
            else:
                state = metadata.suggestions[node.id].status
                if state != "pending":
                    discarded = node.before if state == "accepted" else node.after
                    discarded_pieces = []
                    for child in walk(discarded):
                        if isinstance(child, Change) and not native_objects:
                            # The parent decision can remove a nested suggestion's
                            # entire range. Retain a point for its HTML history card.
                            discarded_pieces.append(marked("O", child.id, ""))
                        elif isinstance(child, Boundary):
                            if (
                                child.id not in metadata.comments
                                and child.id not in reply_ids
                            ):
                                raise ReviewError(
                                    f"Suggestion {node.id} would discard an attached formatting revision; reconcile the nested decisions first"
                                )
                            discarded_pieces.append(
                                boundary(
                                    "C", child.id, "S" if child.edge == "start" else "E"
                                )
                            )
                        elif isinstance(child, Comment) and child.id not in ranged:
                            discarded_pieces.append(marked("C", child.id, ""))
                    retained = render(
                        node.after if state == "accepted" else node.before
                    )
                    discarded_anchors = "".join(discarded_pieces)
                    rendered = (
                        discarded_anchors + retained
                        if state == "accepted"
                        else retained + discarded_anchors
                    )
                    pieces.append(
                        rendered if native_objects else marked("O", node.id, rendered)
                    )
                else:
                    if node.before:
                        pieces.append(marked("D", node.id, render(node.before)))
                    if node.after:
                        pieces.append(marked("I", node.id, render(node.after)))
                    if not node.before and not node.after:
                        native_kind = metadata.suggestions[node.id].provenance.get(
                            "kind"
                        )
                        if native_kind in {
                            "ins",
                            "del",
                            "moveFrom",
                            "moveTo",
                            "conflictIns",
                            "conflictDel",
                        }:
                            kind = (
                                "D"
                                if native_kind in {"del", "moveFrom", "conflictDel"}
                                else "I"
                            )
                            pieces.append(marked(kind, node.id, ""))
                        else:
                            raise ReviewError(
                                f"Suggestion {node.id} has no text or preserved native record"
                            )
        return "".join(pieces)

    markdown = render(document.nodes)
    # Keep both source alternatives for inspection after a decision. They are
    # review-card content, never reintroduced into the manuscript projection.
    # Decisions on nested edits still apply within each alternative.
    suggestions = {
        node.id: (
            project(node.before, "original", decisions),
            project(node.after, "proposed", decisions),
        )
        for node in walk(document.nodes)
        if isinstance(node, Change) and node.id in metadata.suggestions
    }
    return PreparedRender(markdown, metadata, comments, expected, suggestions)
