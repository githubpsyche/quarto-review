"""Read and edit a complete review document stored in one QMD file.

The metadata and syntax trees exposed here are in-memory views, not separate
authoring stores. Source offsets remain attached to every editable annotation.
"""

from __future__ import annotations

import json
import re
import shlex
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path

import yaml

from quarto_review.errors import ReviewError
from quarto_review.markup import (
    Boundary,
    Change,
    Comment,
    Document,
    Highlight,
    Text,
    _Parser,
)
from quarto_review.metadata import (
    CommentMetadata,
    NativeObject,
    Reply,
    ReviewMetadata,
    SuggestionMetadata,
)

_FRONT = re.compile(r"\A---\r?\n(.*?)\r?\n(?:---|\.\.\.)[ \t]*(?:\r?\n|$)", re.S)
_DIV = re.compile(r" {0,3}(:{3,})[ \t]*(\{[^\n]*\})?[ \t]*(?:\n|$)")
_ATTR = re.compile(r"\{(?:[^{}\"']|\"(?:\\.|[^\"\\])*\"|'[^']*')*\}")
_DATA = re.compile(r"<!-- review-data:\s*(.*?)\s*-->", re.S)
_ID = re.compile(r"[A-Za-z][A-Za-z0-9_.:-]*\Z")


def frontmatter(source: str) -> tuple[dict, int]:
    match = _FRONT.match(source)
    if not match:
        return {}, 0
    from quarto_review.metadata import _Loader

    try:
        values = yaml.load(match[1], Loader=_Loader) or {}
    except yaml.YAMLError as error:
        raise ReviewError(f"Invalid QMD front matter: {error}") from error
    if not isinstance(values, dict):
        raise ReviewError("QMD front matter must be a mapping")
    return values, match.end()


def is_single(source: str) -> bool:
    # Avoid treating occurrences in code examples or ordinary prose as settings.
    if not source.startswith("---"):
        return False
    settings = frontmatter(source)[0].get("review")
    return isinstance(settings, dict) and settings.get("schema") == 2


def attributes(raw: str) -> tuple[str | None, set[str], dict[str, str]]:
    try:
        tokens = shlex.split(raw[1:-1])
    except ValueError as error:
        raise ReviewError(f"Invalid review attributes: {error}") from error
    identifier, classes, values = None, set(), {}
    for token in tokens:
        if token.startswith("#"):
            if identifier is not None or not _ID.fullmatch(token[1:]):
                raise ReviewError("Review attributes require one valid identifier")
            identifier = token[1:]
        elif token.startswith("."):
            if token[1:] in classes:
                raise ReviewError(f"Duplicate class {token}")
            classes.add(token[1:])
        elif "=" in token:
            key, value = token.split("=", 1)
            if key in values:
                raise ReviewError(f"Duplicate review attribute {key}")
            values[key] = value
        else:
            raise ReviewError(f"Invalid review attribute {token!r}")
    return identifier, classes, values


def attr_text(identifier: str, classes=(), **values) -> str:
    parts = ["#" + identifier, *("." + item for item in classes)]
    for key, value in values.items():
        if value is not None:
            encoded = str(value)
            if not re.fullmatch(r"[A-Za-z0-9_.:/+-]+", encoded):
                encoded = json.dumps(encoded, ensure_ascii=False)
            parts.append(key + "=" + encoded)
    return "{" + " ".join(parts) + "}"


def data_text(data: dict) -> str:
    if not data:
        return ""
    encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace(
        "<", "\\u003c"
    )
    return "<!-- review-data: " + encoded + " -->"


def _message_format(item: CommentMetadata | Reply) -> str | None:
    # Native messages default to literal text, so an explicit Markdown opt-in
    # must survive subsequent reply and decision operations.
    if item.body_format == "plain" or "word_id" in item.provenance:
        return item.body_format
    return None


@dataclass(frozen=True)
class ThreadLocation:
    start: int
    end: int
    consumed_end: int


@dataclass
class Source:
    document: Document
    metadata: ReviewMetadata
    settings: dict
    authors: dict[str, str | None]
    threads: dict[str, ThreadLocation]
    changes: dict[str, tuple[int, int]]
    anchors: dict[str, list[tuple[int, int]]]
    signature: str = ""

    @property
    def text(self) -> str:
        return self.document.source

    @property
    def reference(self) -> str:
        value = self.settings.get("reference", "reference.qmd")
        if not isinstance(value, str) or not value:
            raise ReviewError("review.reference must be a relative QMD path")
        return value

    def alias(self, name: str | None) -> str:
        for alias, value in self.authors.items():
            if value == name:
                return alias
        ascii_name = (
            unicodedata.normalize("NFKD", name or "Unattributed")
            .encode("ascii", "ignore")
            .decode()
        )
        prefix = (
            "".join(word[0].upper() for word in re.findall(r"[A-Za-z]+", ascii_name))
            or "A"
        )
        alias, number = prefix, 2
        while alias in self.authors:
            alias, number = f"{prefix}{number}", number + 1
        self.authors[alias] = name
        return alias

    def change_suffix(
        self, identifier: str, metadata: ReviewMetadata | None = None
    ) -> str:
        metadata = metadata or self.metadata
        if identifier in metadata.objects:
            obj = metadata.objects[identifier]
            return attr_text(identifier) + data_text(
                {
                    "object": asdict(obj),
                    "revisions": {
                        key: asdict(metadata.suggestions[key]) for key in obj.revisions
                    },
                }
            )
        item = metadata.suggestions[identifier]
        classes = () if item.status == "pending" else (item.status,)
        return attr_text(
            identifier, classes, by=self.alias(item.author), at=item.date
        ) + data_text({"provenance": item.provenance} if item.provenance else {})

    def thread_text(
        self,
        identifier: str,
        item: CommentMetadata | None = None,
        body: str | None = None,
    ) -> str:
        item = item or self.metadata.comments[identifier]
        if body is None:
            body = self.document.annotations()[identifier].body
        # Longer enclosing fences keep Markdown divs inside message bodies literal.
        bodies = [body, *(reply.body for reply in item.replies)]
        longest = max(
            (
                len(m[1])
                for value in bodies
                for m in re.finditer(r"(?m)^ *(:{3,})", value)
            ),
            default=2,
        )
        inner, outer = ":" * max(3, longest + 1), ":" * max(4, longest + 2)
        classes = ["review-thread"] + (
            ["resolved"] if item.status == "resolved" else []
        )
        pieces = [
            outer
            + " "
            + attr_text(
                identifier,
                classes,
                by=self.alias(item.author),
                at=item.date,
                format=_message_format(item),
            )
        ]
        if item.provenance:
            pieces.append(data_text({"provenance": item.provenance}))
        pieces.append(body.rstrip("\n"))
        for reply in item.replies:
            fields = {
                "by": self.alias(reply.author),
                "at": reply.date,
                "format": _message_format(reply),
            }
            if reply.parent_id != identifier:
                fields["to"] = reply.parent_id
            if reply.resolved is not None:
                fields["resolved"] = str(reply.resolved).lower()
            pieces.extend(["", inner + " " + attr_text(reply.id, ("reply",), **fields)])
            if reply.provenance:
                pieces.append(data_text({"provenance": reply.provenance}))
            pieces.extend([reply.body.rstrip("\n"), inner])
        pieces.append(outer)
        return "\n".join(pieces) + "\n"

    def apply(
        self, edits: list[tuple[int, int, str]], *, update_authors: bool = True
    ) -> str:
        ordered = sorted(edits)
        for left, right in zip(ordered, ordered[1:]):
            if left[1] > right[0]:
                raise ReviewError("Review edits overlap; no source was saved")
        result = self.text
        for start, end, value in reversed(ordered):
            result = result[:start] + value + result[end:]
        if update_authors and self.authors != self.settings.get("authors", {}):
            settings = {**self.settings, "authors": self.authors}
            result = set_review_settings(result, settings)
        # Validate every operation before replacing the authoritative source.
        read(result, self.document.path)
        return result

    def save(self, path: Path, text: str) -> Source:
        if path.read_text(encoding="utf-8") != self.text:
            raise ReviewError(
                f"{path}: source changed since it was read; retry against the latest file"
            )
        from quarto_review.project import write_text

        write_text(path, text)
        from quarto_review.preview import invalidate

        invalidate(path.parent)
        return read(text, self.document.path)

    def updated(self, metadata: ReviewMetadata) -> str:
        edits = []
        for identifier, location in self.threads.items():
            if identifier not in metadata.comments:
                edits.append((location.start, location.consumed_end, ""))
                original = self.metadata.comments[identifier]
                for key in (identifier, *(reply.id for reply in original.replies)):
                    edits.extend(
                        (start, end, "") for start, end in self.anchors.get(key, ())
                    )
            elif metadata.comments[identifier] != self.metadata.comments[identifier]:
                edits.append(
                    (
                        location.start,
                        location.end,
                        self.thread_text(identifier, metadata.comments[identifier]),
                    )
                )
        for identifier, location in self.changes.items():
            if (
                identifier in metadata.suggestions
                and metadata.suggestions[identifier]
                != self.metadata.suggestions[identifier]
            ):
                edits.append((*location, self.change_suffix(identifier, metadata)))
            elif identifier in metadata.objects:
                old, new = (
                    self.metadata.objects[identifier],
                    metadata.objects[identifier],
                )
                if old != new or any(
                    self.metadata.suggestions[key] != metadata.suggestions[key]
                    for key in new.revisions
                ):
                    edits.append((*location, self.change_suffix(identifier, metadata)))
        return self.apply(edits)


def set_review_settings(source: str, settings: dict) -> str:
    values, end = frontmatter(source)
    encoded = yaml.safe_dump({"review": settings}, sort_keys=False, allow_unicode=True)
    if not end:
        return "---\n" + encoded + "---\n\n" + source
    match = _FRONT.match(source)
    header = match[1]
    # Replace just the top-level review key. Leave all manuscript metadata verbatim.
    key = re.search(r"(?m)^review:[^\n]*(?:\n|$)", header)
    if key:
        following = re.search(r"(?m)^[^\s#][^\n]*:", header[key.end() :])
        stop = key.end() + following.start() if following else len(header)
        header = header[: key.start()] + encoded + header[stop:]
    else:
        header = header.rstrip("\n") + "\n" + encoded
    return "---\n" + header.rstrip("\n") + "\n---\n" + source[end:]


class _Reader(_Parser):
    def __init__(self, source: str, path: str, settings: dict):
        super().__init__(source, path)
        self.settings = settings
        self.front_end = _FRONT.match(source).end() if _FRONT.match(source) else 0
        self.authors = dict(settings.get("authors", {}))
        if not self.authors or any(
            not _ID.fullmatch(key) or (value is not None and not isinstance(value, str))
            for key, value in self.authors.items()
        ):
            raise self.error("review.authors must map valid aliases to names")
        author = self.author({"by": settings.get("author")}, 0)
        if not author:
            raise self.error("review.author must identify a named current author")
        self.metadata = ReviewMetadata(
            author, settings.get("created_at", ""), sources=(path,)
        )
        self.metadata.imports = dict(settings.get("imports", {}))
        self.blocks: dict[int, tuple[str, int]] = {}
        self.threads: dict[str, ThreadLocation] = {}
        self.changes: dict[str, tuple[int, int]] = {}
        self.anchors: dict[str, list[tuple[int, int]]] = {}
        self.ranges: dict[str, list[tuple[str, str, int]]] = {}
        self.potential_changes = set(
            re.findall(r"\{#([A-Za-z][A-Za-z0-9_.:-]*)(?=\s)[^{}\n]*\bby=", source)
        )
        self.potential_changes.update(
            re.findall(r"\{#([A-Za-z][A-Za-z0-9_.:-]*)\}<!-- review-data:", source)
        )
        self.scan_threads()

    def author(self, values, position):
        key = values.get("by")
        if key not in self.authors:
            raise self.error(f"Unknown or missing author alias {key!r}", position)
        return self.authors[key]

    def literal_end(self):
        if self.position == 0 and self.front_end:
            return self.front_end
        if self.source.startswith("<!--", self.position):
            end = self.source.find("-->", self.position + 4)
            if end < 0:
                raise self.error("Unclosed HTML comment")
            return end + 3
        return super().literal_end()

    def attached_data(self, position):
        match = _DATA.match(self.source, position)
        if not match:
            return {}, position
        try:
            value = json.loads(match[1])
            if not isinstance(value, dict):
                raise ValueError("expected an object")
        except ValueError as error:
            raise self.error(f"Invalid review-data: {error}", position) from error
        return value, match.end()

    def block_end(self, position: int):
        opening = _DIV.match(self.source, position)
        cursor, depth = opening.end(), 1
        literal = _Parser(self.source, self.path)
        while cursor < len(self.source):
            literal.position = cursor
            stop = literal.literal_end()
            if stop:
                cursor = stop
                continue
            if cursor == 0 or self.source[cursor - 1] == "\n":
                match = _DIV.match(self.source, cursor)
                if match:
                    depth += 1 if match[2] else -1
                    if depth == 0:
                        return cursor, match.end()
                    cursor = match.end()
                    continue
            cursor += 1
        raise self.error("Unclosed review div", position)

    def message(self, opening, root: str | None = None):
        identifier, classes, values = attributes(opening[2])
        allowed = {"by", "at", "format"} | ({"to", "resolved"} if root else set())
        if not identifier or values.keys() - allowed:
            raise self.error(
                "Missing message ID or unsupported message attribute", opening.start()
            )
        if classes - ({"reply"} if root else {"review-thread", "resolved"}):
            raise self.error("Unsupported review message class", opening.start())
        self.author(values, opening.start())
        end_body, end = self.block_end(opening.start())
        body_start = opening.end()
        data, following = self.attached_data(body_start)
        if data.keys() - {"provenance"} or not isinstance(
            data.get("provenance", {}), dict
        ):
            raise self.error("Unsupported message review-data", body_start)
        if following != body_start and self.source[following : following + 1] == "\n":
            following += 1
        body_start = following
        # Older schema-2 imports predate explicit formats; native Word bodies
        # remain literal unless their author explicitly opts into Markdown.
        values.setdefault(
            "format", "plain" if "word_id" in data.get("provenance", {}) else "markdown"
        )
        if values["format"] not in {"plain", "markdown"}:
            raise self.error(
                "Message format must be plain or markdown", opening.start()
            )
        return identifier, classes, values, data, body_start, end_body, end

    def scan_threads(self):
        cursor = self.front_end
        literal = _Parser(self.source, self.path)
        while cursor < len(self.source):
            literal.position = cursor
            skip = literal.literal_end()
            if skip:
                cursor = skip
                continue
            if self.source.startswith("<!--", cursor):
                stop = self.source.find("-->", cursor + 4)
                cursor = len(self.source) if stop < 0 else stop + 3
                continue
            match = (
                _DIV.match(self.source, cursor)
                if cursor == 0 or self.source[cursor - 1] == "\n"
                else None
            )
            if not match or not match[2] or ".review-thread" not in match[2]:
                cursor += 1
                continue
            identifier, classes, values, data, body_start, body_end, end = self.message(
                match
            )
            if identifier in self.metadata.comments:
                raise self.error(f"Duplicate thread {identifier}", cursor)
            replies, pieces, position, last = [], [], body_start, body_start
            while position < body_end:
                literal.position = position
                skip = literal.literal_end()
                if skip:
                    position = skip
                    continue
                child = (
                    _DIV.match(self.source, position)
                    if position == 0 or self.source[position - 1] == "\n"
                    else None
                )
                if child and child[2] and ".reply" in child[2]:
                    if replies and self.source[last:position].strip():
                        raise self.error(
                            "Place initial message text before its replies", last
                        )
                    if not replies:
                        pieces.append(self.source[last:position])
                    rid, _, attrs, extra, begin, finish, after = self.message(
                        child, identifier
                    )
                    if attrs.get("resolved") not in {None, "true", "false"}:
                        raise self.error(
                            "Reply resolved must be true or false", position
                        )
                    replies.append(
                        Reply(
                            rid,
                            self.source[begin:finish].rstrip("\n"),
                            self.author(attrs, position),
                            attrs.get("at"),
                            attrs.get("to", identifier),
                            extra.get("provenance", {}),
                            None
                            if "resolved" not in attrs
                            else attrs["resolved"] == "true",
                            attrs["format"],
                        )
                    )
                    position = last = after
                elif child and child[2]:
                    position = self.block_end(position)[1]
                else:
                    position += 1
            if replies:
                if self.source[last:body_end].strip():
                    raise self.error(
                        "Place initial message text before its replies", last
                    )
            else:
                pieces.append(self.source[last:body_end])
            body = "".join(pieces).rstrip("\n")
            if not body.strip() or any(not reply.body.strip() for reply in replies):
                raise self.error("Review messages cannot be empty", cursor)
            self.metadata.comments[identifier] = CommentMetadata(
                self.author(values, cursor),
                values.get("at"),
                "resolved" if "resolved" in classes else "open",
                tuple(replies),
                data.get("provenance", {}),
                values["format"],
            )
            self.blocks[cursor] = (identifier, end)
            consumed = end
            while consumed < len(self.source) and self.source[consumed] in "\r\n":
                consumed += 1
            self.threads[identifier] = ThreadLocation(cursor, end, consumed)
            self.blocks[cursor] = (identifier, consumed)
            # Store the body separately until a Comment node is constructed.
            self.blocks[cursor] += (body,)
            cursor = consumed
        self.comment_ids = set(self.metadata.comments) | {
            reply.id
            for item in self.metadata.comments.values()
            for reply in item.replies
        }

    def identifier(self):
        match = _ATTR.match(self.source, self.position)
        if not match:
            raise self.error("Every suggestion needs an ID and attribution")
        start = self.position
        identifier, classes, values = attributes(match[0])
        if not identifier or identifier in self.identifiers:
            raise self.error(f"Missing or duplicate suggestion ID {identifier}")
        if (
            classes - {"accepted", "rejected"}
            or {"accepted", "rejected"} <= classes
            or values.keys() - {"by", "at"}
        ):
            raise self.error("Invalid suggestion attributes")
        self.identifiers.add(identifier)
        self.position = match.end()
        data, self.position = self.attached_data(self.position)
        if data.keys() - {"object", "revisions", "provenance"} or not isinstance(
            data.get("provenance", {}), dict
        ):
            raise self.error("Unsupported suggestion review-data", start)
        if "object" in data:
            obj = dict(data["object"])
            obj["revisions"] = tuple(obj["revisions"])
            self.metadata.objects[identifier] = NativeObject(**obj)
            for key, item in data.get("revisions", {}).items():
                if key in self.metadata.suggestions:
                    raise self.error(f"Duplicate native revision {key}", start)
                self.metadata.suggestions[key] = SuggestionMetadata(**item)
        else:
            self.metadata.suggestions[identifier] = SuggestionMetadata(
                self.author(values, start),
                values.get("at"),
                next(iter(classes), "pending"),
                data.get("provenance", {}),
            )
        self.changes[identifier] = (start, self.position)
        return identifier

    def special(self):
        start = self.position
        if start in self.blocks:
            identifier, end, body = self.blocks[start]
            self.position = end
            return (Comment((), body, identifier, start, end),)
        if self.source[start : start + 1] != "[":
            return None
        # Read a bracketed span without confusing nested links, images or code.
        depth, cursor = 1, start + 1
        literal = _Parser(self.source, self.path)
        while cursor < len(self.source) and depth:
            literal.position = cursor
            skip = literal.literal_end()
            if skip:
                cursor = skip
                continue
            char = self.source[cursor]
            depth += (char == "[") - (char == "]")
            cursor += 1
        if depth:
            return None
        # A citation/link immediately followed by CriticMarkup is not a span.
        # Let the ordinary parser consume the review operation separately.
        if self.source.startswith(("{++", "{--", "{~~", "{==", "{>>"), cursor):
            return None
        attr = _ATTR.match(self.source, cursor)
        if not attr:
            return None
        identifier, classes, values = attributes(attr[0])
        # Ordinary Markdown spans with classes or non-review IDs are untouched.
        if classes or values or not identifier:
            return None
        if cursor == start + 2:
            roots = (
                self.comment_ids
                | self.potential_changes
                | set(self.metadata.suggestions)
            )
            edge = identifier.rsplit("-", 1)[-1]
            root = identifier[: -(len(edge) + 1)]
            number = "1"
            if root not in roots and "-" in root:
                parent, possible_number = root.rsplit("-", 1)
                if possible_number.isdigit() and parent in roots:
                    root, number = parent, possible_number
            if edge in {"start", "end"} and root in roots:
                self.ranges.setdefault(root, []).append((number, edge, start))
                self.anchors.setdefault(root, []).append((start, attr.end()))
                self.position = attr.end()
                return (Boundary(root, edge, start, attr.end()),)
            if identifier.endswith(("-start", "-end")):
                raise self.error(f"Review boundary {identifier} has no definition")
            return None
        if identifier not in self.comment_ids:
            return None
        self.anchors.setdefault(identifier, []).extend(
            [(start, start + 1), (cursor - 1, attr.end())]
        )
        self.ranges.setdefault(identifier, []).extend(
            [("span", "start", start), ("span", "end", attr.end())]
        )
        self.position = start + 1
        content, _ = self.sequence(limit=cursor - 1)
        if self.position != cursor - 1:
            raise self.error("Invalid comment span", start)
        self.position = attr.end()
        return (
            Boundary(identifier, "start", start, start + 1),
            *content,
            Boundary(identifier, "end", cursor - 1, attr.end()),
        )


def read(
    source: str, path: str = "index.qmd", *, settings: dict | None = None
) -> Source:
    settings = settings or frontmatter(source)[0].get("review", {})
    if not isinstance(settings, dict) or settings.get("schema") != 2:
        raise ReviewError(f"{path}: expected review.schema: 2")
    try:
        reader = _Reader(source, path, settings)
        nodes, _ = reader.sequence()
    except (TypeError, ValueError, KeyError) as error:
        raise ReviewError(
            f"{path}: invalid single-source review data: {error}"
        ) from error
    document = Document(source, nodes, path)
    reader.metadata.validate({path: document})
    for identifier, item in reader.metadata.comments.items():
        if not reader.ranges.get(identifier):
            raise reader.error(
                f"Comment {identifier} has no anchor", reader.threads[identifier].start
            )
    for identifier, events in reader.ranges.items():
        if (
            identifier not in reader.comment_ids
            and identifier not in reader.metadata.suggestions
        ):
            raise reader.error(
                f"Range {identifier} has no review definition", events[0][2]
            )
        active = set()
        for number, edge, position in sorted(events, key=lambda event: event[2]):
            if edge == "start":
                if active:
                    raise reader.error(
                        f"Overlapping ranges for the same comment {identifier}",
                        position,
                    )
                active.add(number)
            elif number not in active:
                raise reader.error(f"Unpaired range for {identifier}", position)
            else:
                active.remove(number)
        if active:
            raise reader.error(f"Unclosed range for {identifier}", events[-1][2])
    return Source(
        document,
        reader.metadata,
        settings,
        reader.authors,
        reader.threads,
        reader.changes,
        reader.anchors,
    )


def from_legacy(
    document: Document, metadata: ReviewMetadata, *, reference: str = "reference.qmd"
) -> str:
    """Convert an attributed legacy tree without writing or consulting live files."""
    settings = {"schema": 2, "author": "", "authors": {}, "reference": reference}
    if metadata.created_at:
        settings["created_at"] = metadata.created_at
    if metadata.imports:
        settings["imports"] = metadata.imports
    writer = Source(document, metadata, settings, {}, {}, {}, {})
    settings["author"] = writer.alias(metadata.author)
    counts: dict[str, int] = {}
    active: dict[str, int] = {}
    bodies = {}

    def encode(nodes):
        parts = []
        for node in nodes:
            if isinstance(node, Text):
                parts.append(node.value)
            elif isinstance(node, Change):
                parts.append(
                    "{~~"
                    + encode(node.before)
                    + "~>"
                    + encode(node.after)
                    + "~~}"
                    + writer.change_suffix(node.id)
                )
            elif isinstance(node, Comment):
                bodies[node.id] = node.body
                if node.content:
                    parts.append("[" + encode(node.content) + "]" + attr_text(node.id))
            elif isinstance(node, Highlight):
                parts.append("{==" + encode(node.content) + "==}")
            elif isinstance(node, Boundary):
                if node.edge == "start":
                    counts[node.id] = counts.get(node.id, 0) + 1
                    active[node.id] = counts[node.id]
                number = active.get(node.id)
                if number is None:
                    raise ReviewError(f"Unpaired legacy boundary {node.id}")
                suffix = "" if number == 1 else f"-{number}"
                parts.append("[]" + attr_text(node.id + suffix + "-" + node.edge))
                if node.edge == "end":
                    del active[node.id]
        return "".join(parts)

    text = encode(document.nodes)
    if active:
        raise ReviewError("Unclosed legacy comment ranges")
    for identifier, item in metadata.comments.items():
        text = (
            text.rstrip("\n")
            + "\n\n"
            + writer.thread_text(identifier, item, bodies[identifier])
        )
    settings["authors"] = writer.authors
    text = set_review_settings(text, settings)
    read(text, document.path)
    return text
