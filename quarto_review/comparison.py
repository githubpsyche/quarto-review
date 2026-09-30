"""Compare ordinary prose edits with a fixed, decision-aware reference."""

from __future__ import annotations

import re
from collections import defaultdict, deque
from dataclasses import asdict, dataclass, replace
from difflib import SequenceMatcher
from hashlib import sha256

from quarto_review.errors import ReviewError
from quarto_review.markup import (
    Change,
    Comment,
    Document,
    Highlight,
    Node,
    Text,
    project,
)
from quarto_review.metadata import ReviewMetadata, SuggestionMetadata

__all__ = ["Comparison", "align_automatic_ids", "compare"]


@dataclass(frozen=True)
class Segment:
    """One source leaf's location in the prose projection used for comparison."""

    node: Text
    start: int
    end: int
    protected: bool


@dataclass(frozen=True)
class Token:
    """A word, separator, or indivisible Markdown construct."""

    value: str
    start: int
    end: int


@dataclass(frozen=True)
class Comparison:
    """A temporary review document and metadata; no source files are rewritten."""

    document: Document
    metadata: ReviewMetadata
    automatic_ids: tuple[str, ...]


def align_automatic_ids(rendered: Comparison, authored: Comparison) -> Comparison:
    """Keep ordinary prose changes tied to source IDs across output formats."""
    candidates = defaultdict(deque)
    source_nodes = authored.document.annotations()
    for identifier in authored.automatic_ids:
        node = source_nodes[identifier]
        candidates[project(node.before, "original"), project(node.after)].append(
            identifier
        )
    aliases = {}
    render_nodes = rendered.document.annotations()
    for identifier in rendered.automatic_ids:
        node = render_nodes[identifier]
        key = project(node.before, "original"), project(node.after)
        if candidates[key]:
            aliases[identifier] = candidates[key].popleft()

    def visit(nodes):
        result = []
        for node in nodes:
            if isinstance(node, Change):
                node = replace(
                    node,
                    id=aliases.get(node.id, node.id),
                    before=visit(node.before),
                    after=visit(node.after),
                )
            elif isinstance(node, (Comment, Highlight)):
                node = replace(node, content=visit(node.content))
            result.append(node)
        return tuple(result)

    metadata = ReviewMetadata.from_mapping(asdict(rendered.metadata))
    metadata.suggestions = {
        aliases.get(key, key): item for key, item in metadata.suggestions.items()
    }
    if len(metadata.suggestions) != len(rendered.metadata.suggestions):
        raise ReviewError(
            "Rendered automatic suggestions have conflicting source identities"
        )
    return Comparison(
        replace(rendered.document, nodes=visit(rendered.document.nodes)),
        metadata,
        tuple(aliases.get(key, key) for key in rendered.automatic_ids),
    )


def _projection(
    document: Document, decisions: dict[str, str], reference_ids: set[str]
) -> tuple[str, list[Segment]]:
    pieces: list[str] = []
    segments: list[Segment] = []
    position = 0

    def visit(nodes: tuple[Node, ...], protected: bool = False) -> None:
        nonlocal position
        for node in nodes:
            if isinstance(node, Text):
                pieces.append(node.value)
                segments.append(
                    Segment(node, position, position + len(node.value), protected)
                )
                position += len(node.value)
            elif isinstance(node, (Comment, Highlight)):
                visit(node.content, protected)
            elif isinstance(node, Change):
                state = (
                    decisions.get(node.id, "pending")
                    if node.id in reference_ids
                    else "pending"
                )
                visit(
                    node.after if state == "accepted" else node.before,
                    protected or state == "pending",
                )

    visit(document.nodes)
    return "".join(pieces), segments


_TOKENS = re.compile(
    r"\A---\n.*?\n(?:---|\.\.\.)[ \t]*(?:\n|$)"
    r"|(?m:^ {0,3}(?P<fence>`{3,}|~{3,})[^\n]*\n.*?^ {0,3}(?P=fence)[ \t]*(?:\n|$))"
    r"|\$\$.*?\$\$|(?<!\\)\$(?:\\.|[^$\n])+?\$"
    r"|`+[^`\n]*`+"
    r"|(?P<anchor>\[\]\{[ \t]*#[A-Za-z][\w.:-]*(?:[ \t]+\.[\w:-]+)*[ \t]*\})"
    r"|!?\[(?:\\.|[^\]\n])*\](?:\([^\n)]*\)|\[[^\]\n]*\])?"
    r"|(?<![\w])[-]?@[A-Za-z0-9_][A-Za-z0-9_:./-]*[A-Za-z0-9_]|(?<![\w])@[A-Za-z0-9_]"
    r"|\*\*[^*\n]+\*\*|\*[^*\n]+\*|__[^_\n]+__|_[^_\n]+_"
    r"|\{[^{}\n]*\}|\\."
    r"|\n[ \t]*\n+|[^\S\n]+|\n|\w+(?:['’]\w+)*|[^\w\s]",
    re.DOTALL,
)


def _blocks(source: str) -> list[list[Token]]:
    blocks: list[list[Token]] = []
    current: list[Token] = []
    for match in _TOKENS.finditer(source):
        # Empty navigation spans become bookmarks, not Word text revisions.
        # Ignore them for alignment while retaining the current source and
        # offsets. Code and escaped syntax are consumed by other token branches.
        if match.group("anchor"):
            continue
        value = match[0]
        if match.start() == 0 and value.startswith("---\n"):
            value = "\0metadata"
        elif value == "\n":
            # A Markdown soft break renders like a space within a paragraph.
            # Keep its source offsets, but do not report sentence-per-line
            # authoring as hundreds of ordinary tracked changes.
            value = " "
        current.append(Token(value, match.start(), match.end()))
        if match[0].startswith("\n") and "\n\n" in match[0].replace(" ", "").replace(
            "\t", ""
        ):
            blocks.append(current)
            current = []
    if current:
        blocks.append(current)
    return blocks


def _edits(before: str, after: str) -> list[tuple[int, int, int, int]]:
    """Align paragraphs first; compare words only inside matched replacements."""

    def bounds(source: str) -> tuple[int, int]:
        metadata = re.match(
            r"\A---\n.*?\n(?:---|\.\.\.)[ \t]*(?:\n|$)", source, re.DOTALL
        )
        start, end = metadata.end() if metadata else 0, len(source)
        while start < end and source[start] in "\r\n":
            start += 1
        while end > start and source[end - 1] in "\r\n":
            end -= 1
        return start, end

    old_offset, old_end = bounds(before)
    new_offset, new_end = bounds(after)
    before, after = before[old_offset:old_end], after[new_offset:new_end]
    old, new = _blocks(before), _blocks(after)

    def keys(blocks: list[list[Token]]) -> list[tuple[str, ...]]:
        return [tuple(token.value for token in block) for block in blocks]

    def span(tokens: list[Token], start: int, stop: int) -> tuple[int, int]:
        offset = tokens[start].start if start < len(tokens) else tokens[-1].end
        return offset, tokens[stop - 1].end if stop > start else offset

    changes = []
    matcher = SequenceMatcher(None, keys(old), keys(new), autojunk=False)
    for kind, a, b, c, d in matcher.get_opcodes():
        if kind == "equal":
            continue
        if kind == "replace" and b - a == d - c:
            for left, right in zip(old[a:b], new[c:d], strict=True):
                words = SequenceMatcher(
                    None,
                    [token.value for token in left],
                    [token.value for token in right],
                    autojunk=False,
                )
                for (
                    operation,
                    old_start,
                    old_stop,
                    new_start,
                    new_stop,
                ) in words.get_opcodes():
                    if operation != "equal":
                        changes.append(
                            (
                                *span(left, old_start, old_stop),
                                *span(right, new_start, new_stop),
                            )
                        )
        else:
            start_old = old[a][0].start if a < len(old) else len(before)
            end_old = old[b - 1][-1].end if b > a else start_old
            start_new = new[c][0].start if c < len(new) else len(after)
            end_new = new[d - 1][-1].end if d > c else start_new
            changes.append((start_old, end_old, start_new, end_new))
    return [
        (a + old_offset, b + old_offset, c + new_offset, d + new_offset)
        for a, b, c, d in changes
    ]


def compare(
    document: Document,
    reference: Document,
    metadata: ReviewMetadata,
    *,
    reference_id: str,
    date: str,
) -> Comparison:
    """Add temporary CriticMarkup nodes for ordinary edits against a reference.

    Explicit pending suggestions are compared through their original wording,
    so their replacement text is not counted twice. Decisions are applied to
    both comparison views in memory. A replacement crossing an annotation
    boundary requires explicit grouping rather than an inferred anchor move.
    """
    decisions = {
        identifier: item.status for identifier, item in metadata.suggestions.items()
    }
    current_annotations, old_annotations = (
        document.annotations(),
        reference.annotations(),
    )
    for identifier in current_annotations.keys() & old_annotations.keys():
        current, original = current_annotations[identifier], old_annotations[identifier]
        if not isinstance(current, Change) or not isinstance(original, Change):
            continue
        if decisions.get(identifier, "pending") != "pending":
            continue
        if project(current.before, "original") != project(original.before, "original"):
            raise ReviewError(
                f"{document.path}: suggestion {identifier}'s original wording differs from the fixed reference"
            )
        item = metadata.suggestions.get(identifier)
        if (
            item is not None
            and item.author != metadata.author
            and project(current.after) != project(original.after)
        ):
            raise ReviewError(
                f"{document.path}: accept or reject {identifier} before rewriting another reviewer's suggested wording"
            )
    reference_ids = set(reference.annotations())
    before, _ = _projection(reference, decisions, reference_ids)
    after, segments = _projection(document, decisions, reference_ids)
    changes = _edits(before, after)
    output_metadata = ReviewMetadata.from_mapping(asdict(metadata))
    replacements: dict[Text, list[tuple[int, int, Change]]] = {}
    identifiers = []
    for old_start, old_end, new_start, new_end in changes:
        removed, inserted = before[old_start:old_end], after[new_start:new_end]
        if removed == inserted:
            continue
        candidates = [
            segment
            for segment in segments
            if not segment.protected
            and segment.start <= new_start
            and segment.end >= new_end
        ]
        if not candidates:
            line = (
                document.source.count("\n", 0, min(new_start, len(document.source))) + 1
            )
            raise ReviewError(
                f"{document.path}:{line}: an ordinary edit crosses a review annotation; use an explicit CriticMarkup replacement to specify its grouping and anchor"
            )
        segment = next(
            (item for item in candidates if item.start <= new_start < item.end),
            candidates[-1],
        )
        local_start, local_end = new_start - segment.start, new_end - segment.start
        fingerprint = "\0".join(
            (
                reference_id,
                document.path,
                str(old_start),
                str(old_end),
                str(new_start),
                removed,
                inserted,
            )
        )
        identifier = "a" + sha256(fingerprint.encode()).hexdigest()[:20]
        if (
            identifier in current_annotations
            or identifier in output_metadata.suggestions
        ):
            raise ReviewError(
                f"Automatic suggestion identifier collides with source annotation {identifier}"
            )
        output_metadata.suggestions[identifier] = SuggestionMetadata(
            metadata.author, date
        )
        first = (Text(removed, 0, len(removed)),) if removed else ()
        second = (
            (
                Text(
                    inserted,
                    segment.node.start + local_start,
                    segment.node.start + local_end,
                ),
            )
            if inserted
            else ()
        )
        change = Change(
            first,
            second,
            identifier,
            segment.node.start + local_start,
            segment.node.start + local_end,
        )
        replacements.setdefault(segment.node, []).append(
            (local_start, local_end, change)
        )
        identifiers.append(identifier)

    def rewrite(nodes: tuple[Node, ...]) -> tuple[Node, ...]:
        result = []
        for node in nodes:
            if isinstance(node, Text) and node in replacements:
                cursor = 0
                for start, end, change in sorted(
                    replacements[node], key=lambda item: item[0]
                ):
                    if cursor < start:
                        result.append(
                            Text(
                                node.value[cursor:start],
                                node.start + cursor,
                                node.start + start,
                            )
                        )
                    result.append(change)
                    cursor = end
                if cursor < len(node.value):
                    result.append(
                        Text(node.value[cursor:], node.start + cursor, node.end)
                    )
            elif isinstance(node, Change):
                result.append(
                    replace(
                        node, before=rewrite(node.before), after=rewrite(node.after)
                    )
                )
            elif isinstance(node, (Comment, Highlight)):
                result.append(replace(node, content=rewrite(node.content)))
            else:
                result.append(node)
        return tuple(result)

    return Comparison(
        Document(document.source, rewrite(document.nodes), document.path),
        output_metadata,
        tuple(identifiers),
    )
