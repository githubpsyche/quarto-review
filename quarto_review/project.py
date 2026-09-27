"""Maintain authoring files, explicit review actions, and frozen references."""

from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory
from typing import TYPE_CHECKING

import yaml

from quarto_review.cache import parse_cached
from quarto_review.errors import ReviewError
from quarto_review.markup import (
    Boundary,
    Change,
    Comment,
    Document,
    Text,
    parse,
    project,
    serialize,
    walk,
)
from quarto_review.metadata import (
    CommentMetadata,
    Reply,
    ReviewMetadata,
    SuggestionMetadata,
    timestamp,
)
from quarto_review.preview import PREVIEW_LINKS, PREVIEW_SIGNAL

__all__ = ["Project", "capture_reference", "setup", "write_text"]

if TYPE_CHECKING:
    from quarto_review.comparison import Comparison
    from quarto_review.source import Source


def write_text(path: Path, content: str) -> None:
    """Replace one UTF-8 file atomically without changing adjacent files."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(content)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


@dataclass
class Project:
    """An explicitly located review project, with no implicit working-directory changes."""

    directory: Path
    metadata: ReviewMetadata
    documents: dict[str, Document]
    source: Source | None = None

    @classmethod
    def read(cls, directory: Path, *, validate_decisions: bool = True) -> Project:
        directory = directory.resolve()
        from quarto_review.source import is_single, read

        input_path = directory / "index.qmd"
        if input_path.is_file() and is_single(input_path.read_text()):
            if (directory / "review.yml").exists():
                raise ReviewError(
                    "Both schema-2 index.qmd and review.yml exist; choose one authoritative source explicitly"
                )
            model = read(input_path.read_text(), "index.qmd")
            result = cls(
                directory,
                ReviewMetadata.from_mapping(asdict(model.metadata)),
                {"index.qmd": model.document},
                model,
            )
            result.reference_path()  # Reject paths escaping the project immediately.
            if validate_decisions:
                result.validate_source_decisions()
            return result
        metadata = ReviewMetadata.read(directory / "review.yml")
        documents = {}
        for name in metadata.sources:
            path = (directory / name).resolve()
            if not path.is_relative_to(directory):
                raise ReviewError(f"Manuscript source escapes the project: {name}")
            documents[name] = parse_cached(
                path.read_text(encoding="utf-8"),
                name,
                directory / ".quarto/review/cache",
            )
        metadata.validate(documents)
        for document in documents.values():
            for identifier, node in document.annotations().items():
                item = metadata.suggestions.get(identifier)
                if (
                    validate_decisions
                    and item is not None
                    and item.status != "pending"
                    and item.provenance.get("decided_text_hash")
                    and isinstance(node, Change)
                ):
                    selected = node.after if item.status == "accepted" else node.before
                    if (
                        sha256(project(selected).encode()).hexdigest()
                        != item.provenance["decided_text_hash"]
                    ):
                        frozen_path = directory / "review/reference/review.yml"
                        frozen = (
                            ReviewMetadata.read(frozen_path).suggestions.get(identifier)
                            if frozen_path.exists()
                            else None
                        )
                        if (
                            frozen is not None
                            and frozen.status == item.status
                            and frozen.provenance.get("decided_text_hash")
                            == item.provenance["decided_text_hash"]
                        ):
                            continue  # This round started after the decision.
                        raise ReviewError(
                            f"{document.path}: decided suggestion {identifier} was rewritten; reopen it with pending or start a new review round before changing its wording"
                        )
        return cls(directory, metadata, documents)

    def save_metadata(self) -> None:
        self.metadata.validate(self.documents)
        if self.source is not None:
            model = self.source.save(
                self.directory / "index.qmd", self.source.updated(self.metadata)
            )
            self.source = model
            self.metadata = ReviewMetadata.from_mapping(asdict(model.metadata))
            self.documents = {"index.qmd": model.document}
        else:
            self.metadata.write(self.directory / "review.yml")

    def reference_path(self) -> Path:
        if self.source is None:
            return self.directory / "review/reference/index.qmd"
        path = (self.directory / self.source.reference).resolve()
        if (
            not path.is_relative_to(self.directory)
            or path == self.directory / "index.qmd"
        ):
            raise ReviewError(
                "The frozen reference must be a separate file inside the project"
            )
        return path

    def reference_document(self, name: str = "index.qmd") -> Document | None:
        if self.source is not None:
            from quarto_review.source import read

            path = self.reference_path()
            return read(path.read_text(), name).document if path.exists() else None
        path = self.directory / "review/reference" / name
        return (
            parse_cached(
                path.read_text(), name, self.directory / ".quarto/review/cache"
            )
            if path.exists()
            else None
        )

    def validate_source_decisions(self) -> None:
        for identifier, item in self.metadata.suggestions.items():
            node = self.documents["index.qmd"].annotations().get(identifier)
            expected = item.provenance.get("decided_text_hash")
            if expected and item.status != "pending" and isinstance(node, Change):
                selected = node.after if item.status == "accepted" else node.before
                if sha256(project(selected).encode()).hexdigest() != expected:
                    from quarto_review.source import read

                    frozen_path = self.reference_path()
                    frozen = (
                        read(frozen_path.read_text()).metadata.suggestions.get(
                            identifier
                        )
                        if frozen_path.exists()
                        else None
                    )
                    if (
                        frozen is not None
                        and frozen.status == item.status
                        and frozen.provenance.get("decided_text_hash") == expected
                    ):
                        continue
                    raise ReviewError(
                        f"Decided suggestion {identifier} was rewritten; reopen it with pending first"
                    )

    def delete_comment(self, identifier: str) -> None:
        if self.source is None:
            raise ReviewError(
                "delete-comment requires the single-source format; convert to a candidate first"
            )
        if identifier not in self.metadata.comments:
            raise ReviewError(f"No initial comment has identifier {identifier}")
        metadata = ReviewMetadata.from_mapping(asdict(self.metadata))
        del metadata.comments[identifier]
        model = self.source.save(
            self.directory / "index.qmd", self.source.updated(metadata)
        )
        self.source, self.metadata = (
            model,
            ReviewMetadata.from_mapping(asdict(model.metadata)),
        )
        self.documents = {"index.qmd": model.document}

    def feedback(self) -> list[dict]:
        """Assemble comment bodies, anchors, and metadata without duplicating storage."""
        result = []
        for path, document in self.documents.items():
            ranges: dict[str, list[tuple[int, int]]] = {}
            starts: dict[str, int] = {}
            pieces = []
            position = 0
            for node in walk(document.nodes):
                if isinstance(node, Boundary):
                    if node.edge == "start":
                        starts[node.id] = position
                    elif node.id in starts:
                        ranges.setdefault(node.id, []).append(
                            (starts.pop(node.id), position)
                        )
                elif isinstance(node, Text):
                    pieces.append(node.value)
                    position += len(node.value)
            all_text = "".join(pieces)
            for identifier, node in document.annotations().items():
                if isinstance(node, Comment):
                    metadata = self.metadata.comments[identifier]
                    anchors = [project(node.content)]
                    if identifier in ranges:
                        anchors = [
                            all_text[start:end] for start, end in ranges[identifier]
                        ]
                    result.append(
                        {
                            "id": identifier,
                            "kind": "comment",
                            "source": path,
                            "line": document.source.count("\n", 0, node.start) + 1,
                            "body": node.body,
                            "anchors": anchors,
                            **asdict(metadata),
                        }
                    )
                elif identifier in self.metadata.suggestions:
                    result.append(
                        {
                            "id": identifier,
                            "kind": "suggestion",
                            "source": path,
                            "line": document.source.count("\n", 0, node.start) + 1,
                            "before": project(node.before, "original"),
                            "after": project(node.after),
                            **asdict(self.metadata.suggestions[identifier]),
                        }
                    )
                elif identifier in self.metadata.objects:
                    item = self.metadata.objects[identifier]
                    result.append(
                        {
                            "id": identifier,
                            "kind": item.kind,
                            "source": path,
                            "before": project(node.before, "original"),
                            "after": project(node.after),
                            "revisions": [
                                {
                                    "id": member,
                                    **asdict(self.metadata.suggestions[member]),
                                }
                                for member in item.revisions
                            ],
                        }
                    )
        for path, comparison in self.ordinary_changes().items():
            annotations = comparison.document.annotations()
            for identifier in comparison.automatic_ids:
                node = annotations[identifier]
                result.append(
                    {
                        "id": identifier,
                        "kind": "suggestion",
                        "automatic": True,
                        "source": path,
                        "line": comparison.document.source.count("\n", 0, node.start)
                        + 1,
                        "before": project(node.before, "original"),
                        "after": project(node.after),
                        **asdict(comparison.metadata.suggestions[identifier]),
                    }
                )
        return result

    def ordinary_changes(self) -> dict[str, Comparison]:
        """Compare authored prose for commands without rendering or changing it."""
        from quarto_review.comparison import compare

        if self.source is not None:
            reference = self.reference_document()
            if reference is None:
                return {}
            return {
                "index.qmd": compare(
                    self.documents["index.qmd"],
                    reference,
                    self.metadata,
                    reference_id=sha256(reference.source.encode()).hexdigest(),
                    date=datetime.fromtimestamp(
                        (self.directory / "index.qmd").stat().st_mtime, UTC
                    ).isoformat(timespec="seconds"),
                )
            }
        reference = self.directory / "review/reference"
        manifest = reference / "manifest.json"
        if not manifest.exists():
            return {}
        identifier = json.loads(manifest.read_text())["id"]
        changes = {}
        for name, document in self.documents.items():
            original = reference / name
            if not original.exists():
                raise ReviewError(
                    f"The reference has no source {name}; start a round including this file"
                )
            date = (
                datetime.fromtimestamp((self.directory / name).stat().st_mtime, UTC)
                .isoformat(timespec="seconds")
                .replace("+00:00", "Z")
            )
            changes[name] = compare(
                document,
                parse_cached(
                    original.read_text(), name, self.directory / ".quarto/review/cache"
                ),
                self.metadata,
                reference_id=identifier,
                date=date,
            )
        return changes

    def retain_suggestion(self, identifier: str) -> None:
        """Make one automatic suggestion explicit before recording a decision."""
        for name, comparison in self.ordinary_changes().items():
            if identifier not in comparison.automatic_ids:
                continue
            node = comparison.document.annotations()[identifier]
            document = self.documents[name]
            if self.source is not None:
                self.metadata.suggestions[identifier] = comparison.metadata.suggestions[
                    identifier
                ]
                markup = serialize((node,))
                markup = markup[: -(len(identifier) + 3)] + self.source.change_suffix(
                    identifier, self.metadata
                )
                text = self.source.apply([(node.start, node.end, markup)])
                model = self.source.save(self.directory / name, text)
                self.source, self.metadata = (
                    model,
                    ReviewMetadata.from_mapping(asdict(model.metadata)),
                )
                self.documents = {name: model.document}
                return
            revised = parse(
                document.source[: node.start]
                + serialize((node,))
                + document.source[node.end :],
                name,
            )
            self.documents[name] = revised
            self.metadata.suggestions[identifier] = comparison.metadata.suggestions[
                identifier
            ]
            self.metadata.validate(self.documents)
            write_text(self.directory / name, revised.source)
            return
        raise ReviewError(f"No suggestion has identifier {identifier}")

    def reply(self, identifier: str, body: str, *, author: str | None = None) -> str:
        """Append one attributed reply to a thread or one of its replies."""
        if not body.strip():
            raise ReviewError("A reply cannot be empty")
        root = next(
            (
                key
                for key, thread in self.metadata.comments.items()
                if key == identifier or identifier in {r.id for r in thread.replies}
            ),
            None,
        )
        if root is None:
            raise ReviewError(f"No comment or reply has identifier {identifier}")
        used = (
            set(self.metadata.comments)
            | set(self.metadata.suggestions)
            | set(self.metadata.objects)
        )
        used.update(
            reply.id
            for thread in self.metadata.comments.values()
            for reply in thread.replies
        )
        number = 1
        while f"r{number}" in used:
            number += 1
        reply_id = f"r{number}"
        if self.source is not None:
            from uuid import uuid4

            reply_id = "r" + uuid4().hex[:12]
        reply = Reply(
            reply_id,
            body,
            author or self.metadata.author,
            timestamp(),
            identifier,
            body_format="markdown" if self.source is not None else "plain",
        )
        thread = self.metadata.comments[root]
        self.metadata.comments[root] = replace(thread, replies=(*thread.replies, reply))
        self.save_metadata()
        return reply_id

    def decide(self, identifier: str, action: str) -> None:
        """Change a review state while retaining its source and fixed reference."""
        if action in {"resolve", "reopen"}:
            if identifier not in self.metadata.comments:
                raise ReviewError(f"No initial comment has identifier {identifier}")
            self.metadata.comments[identifier] = replace(
                self.metadata.comments[identifier],
                status="resolved" if action == "resolve" else "open",
                replies=tuple(
                    replace(
                        reply,
                        resolved=None
                        if self.source is not None
                        else action == "resolve",
                    )
                    for reply in self.metadata.comments[identifier].replies
                ),
            )
        elif action in {"accept", "reject", "pending"}:
            if identifier not in self.metadata.suggestions:
                self.retain_suggestion(identifier)
            provenance = dict(self.metadata.suggestions[identifier].provenance)
            node = next(
                (
                    document.annotations()[identifier]
                    for document in self.documents.values()
                    if identifier in document.annotations()
                ),
                None,
            )
            if action == "pending":
                provenance.pop("decided_text_hash", None)
            elif isinstance(node, Change):
                selected = node.after if action == "accept" else node.before
                provenance["decided_text_hash"] = sha256(
                    project(selected).encode()
                ).hexdigest()
            self.metadata.suggestions[identifier] = replace(
                self.metadata.suggestions[identifier],
                status={
                    "accept": "accepted",
                    "reject": "rejected",
                    "pending": "pending",
                }[action],
                provenance=provenance,
            )
        else:
            raise ReviewError(f"Unknown review action {action}")
        self.save_metadata()


def setup(
    directory: Path,
    *,
    author: str,
    sources: tuple[str, ...] = ("index.qmd",),
    single_source: bool = False,
) -> Project:
    """Register a project's existing annotations and assign missing identifiers."""
    directory = directory.resolve()
    if (directory / "review.yml").exists():
        raise ReviewError(
            "This project already has review.yml; use its existing review state"
        )
    if single_source:
        if sources != ("index.qmd",):
            raise ReviewError("Single-source projects use index.qmd")
        from quarto_review.source import is_single, read, set_review_settings

        input_path = directory / "index.qmd"
        original = input_path.read_text()
        if is_single(original):
            return Project.read(directory)
        initial = parse(original, "index.qmd")
        if initial.annotations():
            raise ReviewError(
                "Initialize plain QMD, or convert attributed legacy annotations with migrate"
            )
        text = set_review_settings(
            original,
            {
                "schema": 2,
                "author": "A",
                "authors": {"A": author},
                "created_at": timestamp(),
            },
        )
        read(text)
        write_text(input_path, text)
        return Project.read(directory)
    metadata = ReviewMetadata(author, timestamp(), sources=sources)
    metadata.validate()
    documents = {}
    used: set[str] = set()
    raw = {}
    for name in sources:
        path = (directory / name).resolve()
        if not path.is_relative_to(directory):
            raise ReviewError(f"Manuscript source escapes the project: {name}")
        document = parse(path.read_text(encoding="utf-8"), name)
        for identifier in document.annotations():
            if identifier in used:
                raise ReviewError(f"Duplicate review identifier {identifier}")
            used.add(identifier)
        raw[name] = document
    for name, document in raw.items():
        edits = []
        for node in walk(document.nodes):
            if not isinstance(node, (Change, Comment)):
                continue
            identifier = node.id
            if identifier is None:
                prefix = "c" if isinstance(node, Comment) else "s"
                number = 1
                while f"{prefix}{number}" in used:
                    number += 1
                identifier = f"{prefix}{number}"
                used.add(identifier)
                edits.append((node.end, "{#" + identifier + "}"))
            collection = (
                metadata.comments if isinstance(node, Comment) else metadata.suggestions
            )
            cls = CommentMetadata if isinstance(node, Comment) else SuggestionMetadata
            collection[identifier] = cls(author, metadata.created_at)
        source = document.source
        for position, insertion in sorted(edits, reverse=True):
            source = source[:position] + insertion + source[position:]
        documents[name] = parse(source, name)
    metadata.validate(documents)
    for name, document in documents.items():
        if document.source != raw[name].source:
            write_text(directory / name, document.source)
    metadata.write(directory / "review.yml")
    return Project(directory, metadata, documents)


def _reference_files(project: Project, include: tuple[str, ...]) -> set[Path]:
    """Collect explicit inputs plus local assets referenced by source or YAML."""
    root = project.directory
    files = {root / name for name in project.metadata.sources}
    if project.source is None:
        files.add(root / "review.yml")
    pending = [root / name for name in include]
    pending.extend(
        root / name
        for name in ("_quarto.yml", "_quarto.yaml", "_metadata.yml", "_extensions")
        if (root / name).exists()
    )
    for document in project.documents.values():
        for match in re.finditer(
            r"!?\[[^\]]*\]\(([^\s)]+)(?:[^)]*)\)", document.source
        ):
            asset = (root / document.path).parent / match[1]
            if asset.is_file():
                pending.append(asset)
        if document.source.startswith("---\n"):
            front = document.source.split("\n---", 1)[0][4:]
            pending.extend(
                _yaml_files(yaml.safe_load(front), (root / document.path).parent)
            )
    while pending:
        path = pending.pop()
        if path.parent == root / "_extensions/quarto-review" and (
            path.name in {PREVIEW_SIGNAL, "review-reference.qmd"}
            or path.name in PREVIEW_LINKS
            and path.is_symlink()
        ):
            continue
        path = path.resolve()
        if not path.is_relative_to(root):
            raise ReviewError(
                f"Reference input is outside the project: {path}; copy it into the project first"
            )
        if path.is_relative_to(root / "review"):
            raise ReviewError(
                "Review archives and references cannot be included recursively"
            )
        if not path.exists():
            raise ReviewError(f"Reference input is missing: {path.relative_to(root)}")
        if path in files:
            continue
        if path.is_dir():
            pending.extend(path.iterdir())
        elif path.is_file():
            files.add(path)
            if path.suffix in {".yml", ".yaml"}:
                pending.extend(
                    _yaml_files(yaml.safe_load(path.read_text()), path.parent)
                )
    return files


def _yaml_files(value, directory: Path) -> list[Path]:
    files = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key not in {"quarto-review", "review"}:
                files.extend(_yaml_files(child, directory))
    elif isinstance(value, list):
        for child in value:
            files.extend(_yaml_files(child, directory))
    elif isinstance(value, str) and "\n" not in value:
        candidate = directory / value
        try:
            if candidate.is_file():
                files.append(candidate)
        except OSError:
            pass
    return files


def capture_reference(
    project: Project,
    *,
    new_round: bool = False,
    include: tuple[str, ...] = (),
    execute: bool = False,
    formats: tuple[str, ...] = (),
) -> dict:
    """Freeze source, metadata, configuration, and identified dependencies.

    An existing reference requires an explicit new-round operation. Previous
    rounds are retained. Additional execution inputs can be supplied in include.
    """
    if project.source is not None:
        path = project.reference_path()
        if path.exists() and not new_round:
            raise ReviewError(
                "A frozen reference already exists; use --new-round explicitly"
            )
        from quarto_review.execution import compiled_inputs
        from quarto_review.execution import execute as execute_project
        from quarto_review.source import set_review_settings

        if execute:
            execute_project(project, formats, include)
        compiled = compiled_inputs(project, include)
        if execute and not compiled:
            raise ReviewError(
                "No executed inputs were captured; the reference was not changed"
            )
        settings = dict(project.source.settings)
        if compiled:
            settings["compiled"] = {
                key.split(":", 1)[1]: value for key, value in compiled.items()
            }
            if include:
                settings["includes"] = list(include)
        text = (
            set_review_settings(project.source.text, settings)
            if compiled
            else project.source.text
        )
        if path.exists():
            previous = path.read_bytes()
            archive = (
                project.directory
                / "review/rounds"
                / (sha256(previous).hexdigest() + ".qmd")
            )
            write_text(archive, previous.decode())
        write_text(path, text)
        return {
            "version": 2,
            "id": sha256(text.encode()).hexdigest(),
            "reference": str(path),
        }
    review = project.directory / "review"
    reference = review / "reference"
    if reference.exists() and not new_round:
        raise ReviewError(
            "A fixed reference already exists; starting another round must be explicit"
        )
    from quarto_review.execution import compiled_inputs, reference_inputs
    from quarto_review.execution import execute as execute_project

    if execute:
        execute_project(project, formats, include)
    include = reference_inputs(project, include)
    compiled = compiled_inputs(project, include)
    if execute and not compiled:
        raise ReviewError(
            "Quarto produced no executed review inputs; enable review before capturing the reference"
        )
    files = _reference_files(project, include)
    for markdown in compiled.values():
        for match in re.finditer(r"!?\[[^\]]*\]\(([^\s)]+)(?:[^)]*)\)", markdown):
            asset = (project.directory / match[1]).resolve()
            if asset.is_file() and asset.is_relative_to(project.directory):
                files.add(asset)
    hashes = {
        str(path.relative_to(project.directory)): sha256(path.read_bytes()).hexdigest()
        for path in sorted(files)
    }
    compiled_hashes = {
        key: sha256(value.encode()).hexdigest() for key, value in compiled.items()
    }
    identifier = sha256(
        json.dumps([hashes, compiled_hashes], sort_keys=True).encode()
    ).hexdigest()
    manifest = {
        "version": 1,
        "id": identifier,
        "created_at": timestamp(),
        "files": hashes,
        "compiled": {},
        "includes": list(include),
    }
    review.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".reference-", dir=review) as folder:
        temporary = Path(folder) / "reference"
        temporary.mkdir()
        for path in files:
            destination = temporary / path.relative_to(project.directory)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, destination)
        for key, markdown in compiled.items():
            filename = f"compiled/{sha256(key.encode()).hexdigest()}.md"
            write_text(temporary / filename, markdown)
            manifest["compiled"][key] = filename
            manifest["files"][filename] = sha256(markdown.encode()).hexdigest()
        write_text(temporary / "manifest.json", json.dumps(manifest, indent=2) + "\n")
        if reference.exists():
            old_manifest = reference / "manifest.json"
            old_id = (
                json.loads(old_manifest.read_text())["id"]
                if old_manifest.exists()
                else sha256(
                    b"".join(
                        path.read_bytes()
                        for path in sorted(reference.rglob("*"))
                        if path.is_file()
                    )
                ).hexdigest()
            )
            archive = review / "rounds" / old_id
            archive.parent.mkdir(exist_ok=True)
            if archive.exists():
                raise ReviewError(
                    f"Reference archive {old_id} already exists; inspect it before advancing"
                )
            reference.rename(archive)
        temporary.rename(reference)
    from quarto_review.preview import invalidate

    invalidate(project.directory)
    return manifest
