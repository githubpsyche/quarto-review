"""Cache parsed source as data, keyed by source content and parser version."""

from __future__ import annotations

import json
import os
from hashlib import sha256
from pathlib import Path
from tempfile import NamedTemporaryFile

from quarto_review import markup
from quarto_review.markup import Boundary, Change, Comment, Document, Highlight, Text

_PARSER = sha256(Path(markup.__file__).read_bytes()).hexdigest()


def _encode(node):
    common = {"type": type(node).__name__, "start": node.start, "end": node.end}
    if isinstance(node, Text):
        return {**common, "value": node.value}
    if isinstance(node, Change):
        return {
            **common,
            "id": node.id,
            "before": [_encode(child) for child in node.before],
            "after": [_encode(child) for child in node.after],
        }
    if isinstance(node, Boundary):
        return {**common, "id": node.id, "edge": node.edge}
    result = {**common, "content": [_encode(child) for child in node.content]}
    if isinstance(node, Comment):
        result.update(id=node.id, body=node.body)
    return result


def _decode(value):
    location = value["start"], value["end"]
    match value["type"]:
        case "Text":
            return Text(value["value"], *location)
        case "Change":
            return Change(
                tuple(map(_decode, value["before"])),
                tuple(map(_decode, value["after"])),
                value["id"],
                *location,
            )
        case "Boundary":
            return Boundary(value["id"], value["edge"], *location)
        case "Comment":
            return Comment(
                tuple(map(_decode, value["content"])),
                value["body"],
                value["id"],
                *location,
            )
        case "Highlight":
            return Highlight(tuple(map(_decode, value["content"])), *location)
        case _:
            raise ValueError("Unknown cached source node")


def parse_cached(source: str, path: str, directory: Path) -> Document:
    """Read or regenerate a JSON cache; never execute a serialized Python object."""
    digest = sha256((_PARSER + "\0" + path + "\0" + source).encode()).hexdigest()
    cache = directory / f"{digest}.json"
    if cache.exists():
        try:
            data = json.loads(cache.read_text(encoding="utf-8"))
            if data["key"] == digest:
                return Document(source, tuple(map(_decode, data["nodes"])), path)
        except (ValueError, KeyError, TypeError):
            pass
    document = markup.parse(source, path)
    data = {"key": digest, "nodes": [_encode(node) for node in document.nodes]}
    directory.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=directory, delete=False
        ) as stream:
            temporary = Path(stream.name)
            json.dump(data, stream, ensure_ascii=False, separators=(",", ":"))
        os.replace(temporary, cache)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return document
