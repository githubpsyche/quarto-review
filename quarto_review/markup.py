"""Parse CriticMarkup while keeping Markdown and review identities intact.

The parser operates before Markdown rendering. It retains source positions and
both sides of each suggestion; it does not flatten Markdown into plain text.
Backtick code spans, fenced code blocks, and escaped delimiters remain literal.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Literal

from quarto_review.errors import ReviewError

__all__ = [
    "Boundary",
    "Change",
    "Comment",
    "Document",
    "Highlight",
    "Text",
    "parse",
    "project",
    "walk",
]

type View = Literal["original", "proposed"]
type Decision = Literal["pending", "accepted", "rejected"]


@dataclass(frozen=True)
class Text:
    """Unmodified source text, including ordinary Markdown syntax."""

    value: str
    start: int
    end: int


@dataclass(frozen=True)
class Change:
    """A proposed change whose source boundaries define its presentation."""

    before: tuple[Node, ...]
    after: tuple[Node, ...]
    id: str | None
    start: int
    end: int


@dataclass(frozen=True)
class Comment:
    """An initial comment body and its explicitly anchored source content."""

    content: tuple[Node, ...]
    body: str
    id: str | None
    start: int
    end: int


@dataclass(frozen=True)
class Highlight:
    """Highlighted source with no attached comment."""

    content: tuple[Node, ...]
    start: int
    end: int


@dataclass(frozen=True)
class Boundary:
    """One side of an imported range that crosses other annotation ranges."""

    id: str
    edge: Literal["start", "end"]
    start: int
    end: int


type Node = Text | Change | Comment | Highlight | Boundary

_BOUNDARY = re.compile(
    r'\[\]\{\.review-(start|end) data-review="([A-Za-z][A-Za-z0-9_.:-]*)"\}'
)


@dataclass(frozen=True)
class Document:
    """Parsed source with locations available for precise edits and diagnostics."""

    source: str
    nodes: tuple[Node, ...]
    path: str = "<source>"

    def annotations(self) -> dict[str, Change | Comment]:
        """Return named annotations; unnamed marks remain available in nodes."""
        return {
            node.id: node
            for node in walk(self.nodes)
            if isinstance(node, (Change, Comment)) and node.id is not None
        }


def walk(nodes: tuple[Node, ...]) -> Iterator[Node]:
    """Visit nested marks in source order, including both sides of changes."""
    for node in nodes:
        yield node
        if isinstance(node, Change):
            yield from walk(node.before)
            yield from walk(node.after)
        elif isinstance(node, (Comment, Highlight)):
            yield from walk(node.content)


def serialize(nodes: tuple[Node, ...]) -> str:
    """Write a review tree as QMD, including temporary comparison annotations."""
    pieces = []
    for node in nodes:
        if isinstance(node, Text):
            pieces.append(node.value)
        elif isinstance(node, Boundary):
            pieces.append(f'[]{{.review-{node.edge} data-review="{node.id}"}}')
        elif isinstance(node, Highlight):
            pieces.append("{==" + serialize(node.content) + "==}")
        elif isinstance(node, Comment):
            body = re.sub(r"([\\`*_{}\[\]<>])", r"\\\1", node.body)
            anchor = "{==" + serialize(node.content) + "==}" if node.content else ""
            pieces.append(
                anchor
                + "{>>"
                + body
                + "<<}"
                + ("{#" + node.id + "}" if node.id else "")
            )
        else:
            pieces.append(
                "{~~"
                + serialize(node.before)
                + "~>"
                + serialize(node.after)
                + "~~}"
                + ("{#" + node.id + "}" if node.id else "")
            )
    return "".join(pieces)


def project(
    nodes: tuple[Node, ...],
    view: View = "proposed",
    decisions: Mapping[str, Decision] | None = None,
) -> str:
    """Return manuscript Markdown for one view, omitting initial comment bodies.

    Decisions override the selected view. This permits comparison against a
    reference after applying explicit decisions in memory without rewriting it.
    """
    if view not in {"original", "proposed"}:
        raise ValueError(f"Unknown view: {view}")
    states = decisions or {}
    pieces: list[str] = []
    for node in nodes:
        if isinstance(node, Text):
            pieces.append(node.value)
        elif isinstance(node, Change):
            decision = states.get(node.id, "pending")
            if decision not in {"pending", "accepted", "rejected"}:
                raise ReviewError(f"Suggestion {node.id}: unknown decision {decision}")
            use_after = decision == "accepted" or (
                decision == "pending" and view == "proposed"
            )
            pieces.append(
                project(node.after if use_after else node.before, view, states)
            )
        elif isinstance(node, (Comment, Highlight)):
            pieces.append(project(node.content, view, states))
    return "".join(pieces)


class _Parser:
    def __init__(self, source: str, path: str) -> None:
        self.source = source
        self.path = path
        self.position = 0
        self.identifiers: set[str] = set()

    def error(self, message: str, position: int | None = None) -> ReviewError:
        position = self.position if position is None else position
        line = self.source.count("\n", 0, position) + 1
        column = position - self.source.rfind("\n", 0, position)
        return ReviewError(f"{self.path}:{line}:{column}: {message}")

    def identifier(self) -> str | None:
        match = re.match(
            r"\{#([A-Za-z][A-Za-z0-9_.:-]*)\}", self.source[self.position :]
        )
        if match is None:
            return None
        identifier = match[1]
        if identifier in self.identifiers:
            raise self.error(f"Duplicate review identifier {identifier}")
        self.identifiers.add(identifier)
        self.position += match.end()
        return identifier

    def literal_end(self) -> int | None:
        """Find code, math, or an escaped character starting at this position."""
        source, start = self.source, self.position
        if source[start] not in "\\`~$":
            return None
        if source[start] == "\\":
            return min(start + 2, len(source))
        line_start = source.rfind("\n", 0, start) + 1
        at_indent = (
            len(source[line_start:start]) <= 3 and not source[line_start:start].strip()
        )
        if at_indent:
            opening = re.match(r"(`{3,}|~{3,})[^\n]*(?:\n|$)", source[start:])
            if opening:
                marker = opening[1]
                closing = re.search(
                    rf"(?m)^ {{0,3}}{re.escape(marker[0])}{{{len(marker)},}}[ \t]*(?:\n|$)",
                    source[start + opening.end() :],
                )
                return start + opening.end() + closing.end() if closing else len(source)
        if source[start] == "`":
            marker = re.match(r"`+", source[start:])[0]
            closing = re.search(
                rf"(?<!`){re.escape(marker)}(?!`)", source[start + len(marker) :]
            )
            if closing:
                return start + len(marker) + closing.end()
        if source[start] == "$":
            marker = "$$" if source.startswith("$$", start) else "$"
            position = source.find(marker, start + len(marker))
            while position >= 0:
                before = position - 1
                while before >= 0 and source[before] == "\\":
                    before -= 1
                if (position - before - 1) % 2 == 0:
                    return position + len(marker)
                position = source.find(marker, position + len(marker))
        return None

    def special(self):
        """Optional source-dialect node, with locations retained."""
        return None

    def body(self) -> str:
        start = self.position
        while self.position < len(self.source):
            if self.source.startswith("\\", self.position):
                self.position += 2
            elif self.source.startswith("<<}", self.position):
                body = re.sub(
                    r"\\([\\`*_{}\[\]<>])", r"\1", self.source[start : self.position]
                )
                self.position += 3
                return body
            else:
                self.position += 1
        raise self.error("Unclosed comment; expected <<}", start)

    def sequence(
        self, stops: tuple[str, ...] = (), *, limit: int | None = None
    ) -> tuple[tuple[Node, ...], str | None]:
        nodes: list[Node] = []
        start_text = self.position

        def flush() -> None:
            if start_text < self.position:
                nodes.append(
                    Text(
                        self.source[start_text : self.position],
                        start_text,
                        self.position,
                    )
                )

        while self.position < (len(self.source) if limit is None else limit):
            stop = next(
                (
                    value
                    for value in stops
                    if self.source.startswith(value, self.position)
                ),
                None,
            )
            if stop is not None:
                flush()
                self.position += len(stop)
                return tuple(nodes), stop
            end = self.literal_end()
            if end is not None:
                self.position = end
                continue
            prior = self.position
            special = self.special()
            if special is not None:
                following = self.position
                self.position = prior
                flush()
                self.position = following
                nodes.extend(special)
                start_text = self.position
                continue
            boundary = _BOUNDARY.match(self.source, self.position)
            if boundary is not None:
                flush()
                nodes.append(
                    Boundary(boundary[2], boundary[1], self.position, boundary.end())
                )
                self.position = boundary.end()
                start_text = self.position
                continue
            token = self.source[self.position : self.position + 3]
            if token in {"{++", "{--", "{~~", "{==", "{>>"}:
                flush()
                start = self.position
                self.position += 3
                if token == "{>>":
                    body = self.body()
                    identifier = self.identifier()
                    nodes.append(Comment((), body, identifier, start, self.position))
                elif token == "{==":
                    content, closing = self.sequence(("==}",))
                    if closing is None:
                        raise self.error("Unclosed highlight; expected ==}", start)
                    if self.source.startswith("{>>", self.position):
                        self.position += 3
                        body = self.body()
                        identifier = self.identifier()
                        nodes.append(
                            Comment(content, body, identifier, start, self.position)
                        )
                    else:
                        nodes.append(Highlight(content, start, self.position))
                else:
                    closing_mark = {"{++": "++}", "{--": "--}", "{~~": "~>"}[token]
                    first, closing = self.sequence((closing_mark,))
                    if closing is None:
                        raise self.error(
                            f"Unclosed change; expected {closing_mark}", start
                        )
                    second: tuple[Node, ...] = ()
                    if token == "{~~":
                        second, closing = self.sequence(("~~}",))
                        if closing is None:
                            raise self.error(
                                "Unclosed substitution; expected ~~}", start
                            )
                    before = () if token == "{++" else first
                    after = first if token == "{++" else second
                    identifier = self.identifier()
                    nodes.append(
                        Change(before, after, identifier, start, self.position)
                    )
                start_text = self.position
            elif token in {"++}", "--}", "~~}", "==}", "<<}"}:
                raise self.error(
                    f"Closing marker {token} has no matching opening marker"
                )
            else:
                self.position += 1
        flush()
        return tuple(nodes), None


def parse(source: str, path: str = "<source>") -> Document:
    """Parse source without accepting suggestions or changing whitespace."""
    parser = _Parser(source, path)
    nodes, _ = parser.sequence()
    return Document(source, nodes, path)
