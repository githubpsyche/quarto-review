"""Connect review preparation and native Word finishing to Quarto render hooks."""

from __future__ import annotations

import json
import os
import re
import shutil
from collections import Counter
from dataclasses import asdict
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

import yaml

from quarto_review.cache import parse_cached
from quarto_review.comparison import align_automatic_ids, compare
from quarto_review.errors import ReviewError
from quarto_review.markup import Change, Comment, serialize
from quarto_review.metadata import ReviewMetadata
from quarto_review.project import Project, write_text
from quarto_review.rendering import PreparedRender, prepare_render
from quarto_review.word.exporter import finish_document
from quarto_review.word.package import WordPackage

__all__ = ["enable", "finish_outputs", "prepare"]


def enable(directory: Path) -> None:
    """Install the bundled filter without replacing an existing output format."""
    project = Project.read(directory)
    destination = project.directory / "_extensions/quarto-review"
    if destination.exists():
        current = destination / "_extension.yml"
        if (
            not current.exists()
            or yaml.safe_load(current.read_text()).get("title") != "Quarto review"
        ):
            raise ReviewError(
                f"The extension destination already contains other files: {destination}"
            )
    shutil.copytree(
        Path(__file__).parent / "extension", destination, dirs_exist_ok=True
    )
    path = project.directory / "_quarto.yml"
    config = yaml.safe_load(path.read_text()) if path.exists() else {}
    if config is None:
        config = {}
    if not isinstance(config, dict):
        raise ReviewError("_quarto.yml must contain a YAML mapping")
    filters = config.get("filters", [])
    if isinstance(filters, str):
        filters = [filters]
    entry = {"at": "pre-ast", "path": "quarto-review"}
    if entry not in filters:
        config["filters"] = [
            entry,
            *[item for item in filters if item != "quarto-review"],
        ]
    citation_filter = {
        "at": "post-quarto",
        "path": "_extensions/quarto-review/citations.lua",
    }
    if citation_filter not in config.get("filters", []):
        config["filters"].append(citation_filter)
    review_settings = config.setdefault("quarto-review", {})
    if not isinstance(review_settings, dict):
        raise ReviewError("The quarto-review project setting must be a YAML mapping")
    # Project preview must reload its context when review state changes. These
    # paths register dependencies without publishing review.yml as a resource.
    if project.source is not None:
        review_settings.update(
            {"source-file": "index.qmd", "reference-file": project.source.reference}
        )
        review_settings.pop("metadata-file", None)
    else:
        review_settings.update(
            {
                "metadata-file": "review.yml",
                "reference-file": "review/reference/manifest.json",
            }
        )
    settings = config.setdefault("project", {"type": "default"})
    if isinstance(settings, str):
        settings = {"type": settings}
        config["project"] = settings
    settings.setdefault("render", list(project.metadata.sources))
    hooks = settings.get("post-render", [])
    if isinstance(hooks, str):
        hooks = [hooks]
    hook = "_extensions/quarto-review/finish.py"
    if hook not in hooks:
        settings["post-render"] = [
            *[item for item in hooks if item != "quarto-review finish"],
            hook,
        ]
    write_text(path, yaml.safe_dump(config, sort_keys=False, allow_unicode=True))
    from quarto_review.pandoc_driver import configure

    configure(project.directory)
    from quarto_review.preview import configure as configure_preview

    configure_preview(
        project.directory,
        reference=project.source.reference if project.source is not None else None,
    )


def prepare(
    directory: Path, source: str, *, path: str, output: str, format: str
) -> dict:
    """Prepare Quarto's executed intermediate Markdown and save a render record.

    Quarto has already executed code cells when this function runs. Preparing
    this intermediate input retains their outputs. Authoring and reference
    files are only read; generated records live under .quarto/review.
    """
    project = Project.read(directory)
    input_path = Path(path)
    if not input_path.is_absolute():
        input_path = project.directory / input_path
    try:
        source_name = str(input_path.resolve().relative_to(project.directory))
    except ValueError as error:
        raise ReviewError(
            f"Render input is outside the review project: {path}"
        ) from error
    if source_name not in project.documents:
        raise ReviewError(f"Render input {source_name} is not registered in review.yml")
    output_path = Path(output)
    if output_path.is_absolute():
        try:
            output = str(output_path.relative_to(project.directory))
        except ValueError as error:
            raise ReviewError(
                f"Render output is outside the review project: {output}"
            ) from error
    cache = project.directory / ".quarto/review/cache"
    if project.source is not None:
        from quarto_review.source import read

        document = read(source, source_name, settings=project.source.settings).document
    else:
        document = parse_cached(source, source_name, cache)
    annotations = document.annotations()
    missing = project.documents[source_name].annotations().keys() - annotations.keys()
    if missing:
        raise ReviewError(
            f"{source_name}: Quarto's executed body omitted review annotations {', '.join(sorted(missing))}; "
            "annotations in YAML metadata or excluded content cannot be exported. Move them into the body or remove the exclusion before rendering"
        )
    objects = {
        key: value
        for key, value in project.metadata.objects.items()
        if key in annotations
    }
    members = {member for value in objects.values() for member in value.revisions}
    data = asdict(project.metadata)
    data["comments"] = {
        key: value
        for key, value in data["comments"].items()
        if isinstance(annotations.get(key), Comment)
    }
    data["suggestions"] = {
        key: value
        for key, value in data["suggestions"].items()
        if isinstance(annotations.get(key), Change) or key in members
    }
    data["objects"] = {
        key: value for key, value in data["objects"].items() if key in objects
    }
    metadata = ReviewMetadata.from_mapping(data)
    from quarto_review.execution import record_execution

    record_execution(project, source_name, format, source)
    capturing = os.environ.get("QUARTO_REVIEW_CAPTURE") == "1"
    reference_path = (
        project.reference_path()
        if project.source is not None
        else project.directory / "review/reference" / source_name
    )
    if not reference_path.is_file() and not capturing:
        raise ReviewError(
            f"No fixed reference exists for {source_name}; capture a reference before rendering"
        )
    if project.source is not None:
        from quarto_review.source import read

        reference_model = (
            read(reference_path.read_text(), source_name)
            if reference_path.exists()
            else project.source
        )
        reference = reference_model.document
        manifest = {}
        reference_id = sha256(reference.source.encode()).hexdigest()
    else:
        reference = parse_cached(
            reference_path.read_text(encoding="utf-8")
            if reference_path.is_file()
            else project.documents[source_name].source,
            source_name,
            cache,
        )
        manifest_path = project.directory / "review/reference/manifest.json"
        manifest = (
            json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
        )
        reference_id = (
            manifest.get("id") or sha256(reference.source.encode()).hexdigest()
        )
    date = (
        datetime.fromtimestamp(input_path.stat().st_mtime, UTC)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )
    authored = (
        None
        if capturing
        else compare(
            project.documents[source_name],
            reference,
            metadata,
            reference_id=reference_id,
            date=date,
        )
    )
    automatic_ids = ()
    compiled_name = manifest.get("compiled", {}).get(f"{source_name}:{format}")
    compact_compiled = (
        reference_model.settings.get("compiled", {}).get(format)
        if project.source is not None
        else None
    )
    if authored is not None and (
        authored.automatic_ids or compiled_name or compact_compiled
    ):
        if compact_compiled:
            reference = read(
                compact_compiled, source_name, settings=reference_model.settings
            ).document
        elif compiled_name:
            reference = parse_cached(
                (project.directory / "review/reference" / compiled_name).read_text(),
                source_name,
                cache,
            )
        elif re.search(
            r"(?m)^\s*`{3,}\{(?:python|r|julia|ojs)\b|`\{(?:python|r|julia)\}",
            project.documents[source_name].source,
        ):
            raise ReviewError(
                f"{source_name}: capture an executed reference before comparing edits to a manuscript with executable code"
            )
        comparison = compare(
            document, reference, metadata, reference_id=reference_id, date=date
        )
        comparison = align_automatic_ids(comparison, authored)
        document, metadata, automatic_ids = (
            comparison.document,
            comparison.metadata,
            comparison.automatic_ids,
        )
    view = "review" if format in {"docx", "html"} else "proposed"
    prepared = prepare_render(
        document,
        metadata,
        view=view,
        native_objects=format == "docx",
        directory=project.directory,
    )
    record = {
        "version": 1,
        "single_source": project.source is not None,
        "source": source_name,
        "output": output,
        "format": format,
        "markdown": prepared.markdown,
        "metadata": asdict(metadata),
        "comments": prepared.comments,
        "expected": dict(prepared.expected),
        "automatic_suggestions": list(automatic_ids),
        "reference_id": reference_id,
        "executed_source": source,
        "authored_review_source": serialize(authored.document.nodes)
        if authored is not None
        else project.documents[source_name].source,
        "authored_metadata": asdict(authored.metadata)
        if authored is not None
        else asdict(metadata),
        "authoring_hashes": {
            name: sha256((project.directory / name).read_bytes()).hexdigest()
            for name in [
                *project.metadata.sources,
                *([] if project.source is not None else ["review.yml"]),
            ]
        },
    }
    if format in {"docx", "html"}:
        identifier = sha256((source_name + "\0" + output).encode()).hexdigest()
        record["citation_plan"] = f".quarto/review/plans/{identifier}.citations"
        # Direct preparation/export has no Lua pass. Quarto replaces this empty
        # plan with its parsed citation ranges; every prepare clears stale data.
        write_text(project.directory / record["citation_plan"], "[]\n")
        write_text(
            project.directory / ".quarto/review/plans" / f"{identifier}.json",
            json.dumps(record, ensure_ascii=False, indent=2) + "\n",
        )
    if format == "html":
        from quarto_review.html import review_panel

        record["panel"] = review_panel(prepared)
    return record


def finish_outputs(
    directory: Path, outputs: tuple[str, ...] | None = None
) -> list[str]:
    """Finish review information in this render's Word and HTML outputs."""
    directory = directory.resolve()
    if outputs is None:
        paths = os.environ.get("QUARTO_PROJECT_OUTPUT_FILES")
        if paths is None:
            raise ReviewError(
                "No Quarto output list is available; provide --output explicitly"
            )
        outputs = tuple(value for value in paths.splitlines() if value)
    files = [(directory / name).resolve() for name in outputs]
    plans = directory / ".quarto/review/plans"
    records = (
        [(path, json.loads(path.read_text())) for path in plans.glob("*.json")]
        if plans.exists()
        else []
    )
    finished = []
    for path in files:
        if path.suffix.lower() not in {".docx", ".html"}:
            continue
        if not path.is_relative_to(directory):
            raise ReviewError(f"Review output is outside the project: {path}")
        candidates = [
            (record_path, record)
            for record_path, record in records
            if Path(record["output"]).name == path.name
        ]
        if len(candidates) != 1:
            raise ReviewError(
                f"Expected one review render record for {path.name}, found {len(candidates)}"
            )
        record_path, record = candidates[0]
        digest = sha256(path.read_bytes()).hexdigest()
        if record.get("finished_hash") == digest:
            continue
        for name, expected in record["authoring_hashes"].items():
            if sha256((directory / name).read_bytes()).hexdigest() != expected:
                raise ReviewError(
                    f"{name} changed during rendering; render again before exporting review records"
                )
        try:
            citation_plans = (
                json.loads((directory / record["citation_plan"]).read_text())
                if record.get("citation_plan")
                else []
            )
        except (OSError, json.JSONDecodeError) as error:
            raise ReviewError(
                f"Cannot read the generated citation plan for {path.name}; render again"
            ) from error
        if path.suffix.lower() == ".html":
            from quarto_review.citation_ranges import restore_html
            from quarto_review.html_finish import finish_html

            completed_html = finish_html(
                restore_html(path.read_text(), citation_plans), record["expected"]
            )
            write_text(path, completed_html)
            record["finished_hash"] = sha256(path.read_bytes()).hexdigest()
            write_text(
                record_path, json.dumps(record, ensure_ascii=False, indent=2) + "\n"
            )
            finished.append(str(path))
            continue
        prepared = PreparedRender(
            record["markdown"],
            ReviewMetadata.from_mapping(record["metadata"]),
            record["comments"],
            Counter(record["expected"]),
        )
        from quarto_review.citation_ranges import restore_word

        package = restore_word(WordPackage.read(path), citation_plans)
        completed = finish_document(package, prepared, directory)
        if os.environ.get("QUARTO_REVIEW_CAPTURE") != "1" and not record.get(
            "single_source"
        ):
            from quarto_review.exchanges import archive_export

            record["export_id"] = archive_export(directory, completed, record)
        completed.write(path)
        record["finished_hash"] = sha256(path.read_bytes()).hexdigest()
        write_text(record_path, json.dumps(record, ensure_ascii=False, indent=2) + "\n")
        finished.append(str(path))
    return finished
