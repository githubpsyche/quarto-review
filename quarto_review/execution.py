"""Capture the executed Markdown used by Quarto for a fixed review reference."""

from __future__ import annotations

import json
import os
import subprocess
from hashlib import sha256

from quarto_review.errors import ReviewError
from quarto_review.project import Project, _reference_files, write_text


def reference_inputs(
    project: Project, include: tuple[str, ...] = ()
) -> tuple[str, ...]:
    """Retain explicitly identified analysis inputs across renders and rounds."""
    manifest = project.directory / "review/reference/manifest.json"
    previous = (
        json.loads(manifest.read_text()).get("includes", [])
        if manifest.exists()
        else []
    )
    if project.source is not None and project.reference_path().exists():
        from quarto_review.source import frontmatter

        previous = (
            frontmatter(project.reference_path().read_text())[0]
            .get("review", {})
            .get("includes", [])
        )
    executing = json.loads(os.environ.get("QUARTO_REVIEW_INCLUDE", "[]"))
    return tuple(dict.fromkeys([*previous, *executing, *include]))


def input_hashes(project: Project, include: tuple[str, ...] = ()) -> dict[str, str]:
    """Fingerprint authoring files and the identified render dependencies."""
    return {
        str(path.relative_to(project.directory)): sha256(path.read_bytes()).hexdigest()
        for path in sorted(
            _reference_files(project, reference_inputs(project, include))
        )
    }


def record_execution(project: Project, source: str, format: str, markdown: str) -> None:
    """Cache executed input with the authoring state that produced it."""
    identifier = sha256((source + "\0" + format).encode()).hexdigest()
    write_text(
        project.directory / ".quarto/review/compiled" / f"{identifier}.json",
        json.dumps(
            {
                "source": source,
                "format": format,
                "markdown": markdown,
                "inputs": input_hashes(project),
            },
            ensure_ascii=False,
        )
        + "\n",
    )


def execute(
    project: Project, formats: tuple[str, ...], include: tuple[str, ...] = ()
) -> None:
    """Run ordinary Quarto execution explicitly, without advancing a reference."""
    before = input_hashes(project, include)
    for source in project.metadata.sources:
        for format in formats or (None,):
            command = ["quarto", "render", source]
            if format is not None:
                command.extend(["--to", format])
            result = subprocess.run(
                command,
                cwd=project.directory,
                env={
                    **os.environ,
                    "QUARTO_REVIEW_CAPTURE": "1",
                    "QUARTO_REVIEW_INCLUDE": json.dumps(
                        reference_inputs(project, include)
                    ),
                },
                capture_output=True,
                text=True,
            )
            if result.returncode:
                raise ReviewError(
                    f"Executed reference capture failed for {source}:\n{result.stdout}{result.stderr}"
                )
    if input_hashes(project, include) != before:
        raise ReviewError(
            "An authoring input changed during execution; the reference was not advanced"
        )


def compiled_inputs(project: Project, include: tuple[str, ...] = ()) -> dict[str, str]:
    """Return cached format-specific inputs only when their source state matches."""
    expected = input_hashes(project, include)
    values = {}
    for path in sorted((project.directory / ".quarto/review/compiled").glob("*.json")):
        record = json.loads(path.read_text())
        if record["inputs"] == expected:
            values[f"{record['source']}:{record['format']}"] = record["markdown"]
    return values
