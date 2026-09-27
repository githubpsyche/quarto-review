"""Archive exact exported documents with the authoring state they represent."""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory

from quarto_review.errors import ReviewError
from quarto_review.project import write_text
from quarto_review.word.identity import read_identity, write_identity
from quarto_review.word.package import WordPackage


def archive_export(directory: Path, package: WordPackage, render: dict) -> str:
    """Freeze a Word export and embed its content-addressed exchange identity.

    The archive is separate from the fixed review reference. Re-rendering the
    same export can reuse its archive; it does not create a new review round.
    """
    digest = sha256()
    for name, content in sorted(package.parts.items()):
        digest.update(name.encode() + b"\0" + content + b"\0")
    digest.update(json.dumps(render["authoring_hashes"], sort_keys=True).encode())
    identifier = digest.hexdigest()
    identity = read_identity(package)
    identity.update(
        {
            "export": identifier,
            "reference": render["reference_id"],
            "source": render["source"],
        }
    )
    write_identity(package, identity)
    parent = directory / "review/exchanges/exports"
    destination = parent / identifier
    if destination.exists():
        return identifier
    parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".export-", dir=parent) as folder:
        temporary = Path(folder) / identifier
        temporary.mkdir()
        package.write(temporary / "document.docx")
        files = {}
        for name, expected in render["authoring_hashes"].items():
            content = (directory / name).read_bytes()
            if sha256(content).hexdigest() != expected:
                raise ReviewError(
                    f"{name} changed while archiving the export; render again"
                )
            target = temporary / "source" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            files[name] = expected
        record = {
            "version": 1,
            "id": identifier,
            "reference": render["reference_id"],
            "source": render["source"],
            "files": files,
            "identity": identity,
            "word_hash": sha256((temporary / "document.docx").read_bytes()).hexdigest(),
            "render": {
                key: value
                for key, value in render.items()
                if key not in {"finished_hash", "authoring_hashes"}
            },
        }
        write_text(
            temporary / "exchange.json",
            json.dumps(record, ensure_ascii=False, indent=2) + "\n",
        )
        temporary.rename(destination)
    return identifier


def load_export(directory: Path, identifier: str) -> tuple[dict, Path]:
    """Locate a retained export by exact hash, never a path supplied by Word."""
    if len(identifier) != 64 or any(
        character not in "0123456789abcdef" for character in identifier
    ):
        raise ReviewError(
            "An export identity must be a complete hexadecimal SHA-256 hash"
        )
    path = directory / "review/exchanges/exports" / identifier
    record_path = path / "exchange.json"
    if not record_path.is_file():
        raise ReviewError(
            f"The exact export {identifier} is not archived in this project"
        )
    record = json.loads(record_path.read_text())
    if sha256((path / "document.docx").read_bytes()).hexdigest() != record["word_hash"]:
        raise ReviewError(
            f"Archived export {identifier} has changed; retain the original before reconciling a return"
        )
    for name, expected in record["files"].items():
        source = (path / "source" / name).resolve()
        if (
            not source.is_relative_to(path.resolve())
            or sha256(source.read_bytes()).hexdigest() != expected
        ):
            raise ReviewError(
                f"The source snapshot for export {identifier} has changed"
            )
    return record, path
