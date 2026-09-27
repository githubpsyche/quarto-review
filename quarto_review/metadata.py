"""Store review attribution and decisions beside the manuscript source."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Literal

import yaml

from quarto_review.errors import ReviewError
from quarto_review.markup import Change, Comment, Document

__all__ = [
    "CommentMetadata",
    "NativeObject",
    "Reply",
    "ReviewMetadata",
    "SuggestionMetadata",
    "timestamp",
]


def timestamp() -> str:
    """Return the current UTC time for a newly recorded review action."""
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


class _Loader(yaml.SafeLoader):
    """Keep ISO timestamps as strings and reject duplicate mapping keys."""

    yaml_implicit_resolvers = {
        key: [
            (kind, expression)
            for kind, expression in values
            if kind != "tag:yaml.org,2002:timestamp"
        ]
        for key, values in yaml.SafeLoader.yaml_implicit_resolvers.items()
    }

    def construct_mapping(self, node, deep=False):
        mapping = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if key in mapping:
                raise ReviewError(
                    f"Duplicate YAML key {key!r} at line {key_node.start_mark.line + 1}"
                )
            mapping[key] = self.construct_object(value_node, deep=deep)
        return mapping


@dataclass(frozen=True)
class Reply:
    """One reply with an explicit interpretation of its stored body."""

    id: str
    body: str
    author: str | None
    date: str | None
    parent_id: str
    provenance: dict[str, str] = field(default_factory=dict)
    resolved: bool | None = None
    body_format: Literal["plain", "markdown"] = "plain"


@dataclass(frozen=True)
class CommentMetadata:
    """Thread metadata whose initial body and anchor are in QMD."""

    author: str | None
    date: str | None
    status: Literal["open", "resolved"] = "open"
    replies: tuple[Reply, ...] = ()
    provenance: dict[str, str] = field(default_factory=dict)
    body_format: Literal["plain", "markdown"] = "plain"


@dataclass(frozen=True)
class SuggestionMetadata:
    """Attribution and disposition of a suggestion represented in QMD."""

    author: str | None
    date: str | None
    status: Literal["pending", "accepted", "rejected"] = "pending"
    provenance: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class NativeObject:
    """An equation with native review records retained in the archived Word file."""

    kind: Literal["equation"]
    source: str
    story: str
    path: str
    revisions: tuple[str, ...]
    source_hash: str | None = None


@dataclass
class ReviewMetadata:
    """Versioned review metadata independent of rendered document layout."""

    author: str
    created_at: str
    comments: dict[str, CommentMetadata] = field(default_factory=dict)
    suggestions: dict[str, SuggestionMetadata] = field(default_factory=dict)
    sources: tuple[str, ...] = ("index.qmd",)
    imports: dict[str, str] = field(default_factory=dict)
    objects: dict[str, NativeObject] = field(default_factory=dict)
    version: int = 1

    def validate(self, documents: Mapping[str, Document] | None = None) -> None:
        """Check identities and relationships before an export or source edit."""
        if self.version != 1:
            raise ReviewError(f"Unsupported review metadata version {self.version}")
        if not isinstance(self.author, str) or not self.author.strip():
            raise ReviewError("Set an explicit author in review.yml")
        identifiers = set(self.comments)
        if identifiers & self.suggestions.keys():
            raise ReviewError(
                "A review identifier is used for both a comment and a suggestion"
            )
        identifiers.update(self.suggestions)
        if identifiers & self.objects.keys():
            raise ReviewError(
                "An object identifier is also used by another review record"
            )
        identifiers.update(self.objects)
        for identifier, item in self.objects.items():
            if item.kind != "equation":
                raise ReviewError(f"Object {identifier}: unsupported kind {item.kind}")
            for revision in item.revisions:
                if revision not in self.suggestions:
                    raise ReviewError(
                        f"Object {identifier}: missing revision {revision}"
                    )
        for identifier, comment in self.comments.items():
            if comment.status not in {"open", "resolved"}:
                raise ReviewError(
                    f"Comment {identifier}: unknown status {comment.status}"
                )
            for message in (comment, *comment.replies):
                if message.body_format not in {"plain", "markdown"}:
                    raise ReviewError(
                        f"Comment {identifier}: unsupported body format {message.body_format}"
                    )
            available = {identifier}
            for reply in comment.replies:
                if reply.id in identifiers:
                    raise ReviewError(f"Duplicate review identifier {reply.id}")
                if reply.parent_id not in available:
                    raise ReviewError(
                        f"Reply {reply.id} refers to unavailable parent {reply.parent_id}"
                    )
                identifiers.add(reply.id)
                available.add(reply.id)
        for identifier, suggestion in self.suggestions.items():
            if suggestion.status not in {"pending", "accepted", "rejected"}:
                raise ReviewError(
                    f"Suggestion {identifier}: unknown status {suggestion.status}"
                )
        if documents is not None:
            found: dict[str, Change | Comment] = {}
            for path, document in documents.items():
                for identifier, node in document.annotations().items():
                    if identifier in found:
                        raise ReviewError(
                            f"{path}: duplicate review identifier {identifier}"
                        )
                    found[identifier] = node
            for identifier in self.comments:
                if not isinstance(found.get(identifier), Comment):
                    raise ReviewError(
                        f"Comment {identifier} has no initial body and anchor in QMD"
                    )
            for identifier in self.suggestions:
                if any(identifier in item.revisions for item in self.objects.values()):
                    continue
                if not isinstance(found.get(identifier), Change):
                    raise ReviewError(
                        f"Suggestion {identifier} has no CriticMarkup in QMD"
                    )
            for identifier, node in found.items():
                if identifier in self.objects and isinstance(node, Change):
                    continue
                known = self.comments if isinstance(node, Comment) else self.suggestions
                if identifier not in known:
                    raise ReviewError(
                        f"Annotation {identifier} has no metadata in review.yml"
                    )
            for identifier in self.objects:
                if not isinstance(found.get(identifier), Change):
                    raise ReviewError(
                        f"Equation {identifier} has no before/after source in QMD"
                    )

    @classmethod
    def from_mapping(cls, values: Mapping) -> ReviewMetadata:
        """Reconstruct validated metadata from YAML or a generated render record."""
        try:
            data = dict(values)
            comments = {}
            for identifier, values in data.pop("comments", {}).items():
                values = dict(values)
                replies = tuple(Reply(**item) for item in values.pop("replies", []))
                comments[identifier] = CommentMetadata(**values, replies=replies)
            suggestions = {
                identifier: SuggestionMetadata(**values)
                for identifier, values in data.pop("suggestions", {}).items()
            }
            data["sources"] = tuple(data.get("sources", ["index.qmd"]))
            objects = {}
            for identifier, values in data.pop("objects", {}).items():
                values = dict(values)
                values["revisions"] = tuple(values["revisions"])
                objects[identifier] = NativeObject(**values)
            result = cls(
                **data, comments=comments, suggestions=suggestions, objects=objects
            )
            result.validate()
            return result
        except (TypeError, AttributeError, ValueError, KeyError) as error:
            raise ReviewError(f"Invalid review metadata: {error}") from error

    @classmethod
    def read(cls, path: Path) -> ReviewMetadata:
        """Read metadata, retaining timestamps and rejecting ambiguous YAML."""
        try:
            data = yaml.load(path.read_text(encoding="utf-8"), Loader=_Loader)
            if not isinstance(data, dict):
                raise ReviewError(f"{path}: expected a YAML mapping")
            return cls.from_mapping(data)
        except (OSError, yaml.YAMLError) as error:
            raise ReviewError(f"Cannot read review metadata {path}: {error}") from error

    def write(self, path: Path) -> None:
        """Validate and atomically save readable YAML with one record per item."""
        self.validate()
        data = asdict(self)
        data = {"version": data.pop("version"), **data}
        encoded = yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=88)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary: Path | None = None
        try:
            with NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=path.parent, delete=False
            ) as file:
                temporary = Path(file.name)
                file.write(encoded)
            os.replace(temporary, path)
            if path.name == "review.yml":
                from quarto_review.preview import invalidate

                invalidate(path.parent.resolve())
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
