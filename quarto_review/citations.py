"""Recover native citation syntax from explicit bibliography links, without guessing."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

import yaml

from quarto_review import pandoc
from quarto_review.errors import ReviewError
from quarto_review.markup import Change, Text, _Parser, walk
from quarto_review.project import Project, write_text
from quarto_review.source import Source, frontmatter, read

_LINK = re.compile(r"\[([^\]\n]+)\]\(#ref[-_]([^()\s]+)\)")
_TOKEN = re.compile(r"\x01([CG])(\d+)\x02")
_CITE = r"\x01C\d+\x02"
_GAP = r"\x01G\d+\x02"


@dataclass(frozen=True)
class NormalizedCitations:
    text: str
    converted: tuple[dict, ...]
    retained: tuple[dict, ...]

    def report(self) -> dict:
        return {"converted": list(self.converted), "retained": list(self.retained)}


def bibliography_keys(path: Path) -> set[str]:
    """Read keys through Pandoc's bibliography reader or CSL JSON/YAML data."""
    path = path.resolve()
    try:
        if path.suffix.lower() in {".bib", ".bibtex", ".biblatex"}:
            items = json.loads(
                pandoc.run([str(path), "--from=biblatex", "--to=csljson"])
            )
        elif path.suffix.lower() in {".json", ".csljson"}:
            items = json.loads(path.read_text())
        elif path.suffix.lower() in {".yaml", ".yml"}:
            items = yaml.safe_load(path.read_text())
            if isinstance(items, dict):
                items = items.get("references")
        else:
            raise ReviewError(
                "Supply a BibTeX/BibLaTeX, CSL JSON or CSL YAML bibliography"
            )
    except (json.JSONDecodeError, yaml.YAMLError) as error:
        raise ReviewError(f"Cannot read bibliography {path.name}: {error}") from error
    if not isinstance(items, list) or any(
        not isinstance(item, dict) or not item.get("id") for item in items
    ):
        raise ReviewError("Bibliography must contain references with explicit IDs")
    ids = [str(item["id"]) for item in items]
    if len(ids) != len(set(ids)):
        raise ReviewError(
            "Bibliography has duplicate IDs; resolve them before normalizing citations"
        )
    return set(ids)


def normalize_source(model: Source, keys: set[str]) -> NormalizedCitations:
    """Rewrite identifiable citation groups, preserving all other source bytes.

    Review syntax, discussions, provenance, code and math are masked rather
    than serialized through a Markdown writer. Unknown or ambiguous groups
    remain unchanged and are reported with source locations.
    """
    source = model.text
    if "\x01" in source or "\x02" in source:
        raise ReviewError("Source contains reserved control characters")
    header_end = frontmatter(source)[1]
    locked = [
        (node.start, node.end, node.id)
        for node in walk(model.document.nodes)
        if isinstance(node, Change)
        and model.metadata.suggestions[node.id].status != "pending"
    ]
    gaps, citations, pieces = [], [], []
    cursor = 0

    def gap(text):
        index = len(gaps)
        gaps.append(text)
        return f"\x01G{index}\x02"

    def prose(text, offset):
        result, pos, last = [], 0, 0
        parser = _Parser(text, model.document.path)

        def links(value, relative):
            def replace(match):
                index = len(citations)
                position = offset + relative + match.start()
                owners = [
                    identifier
                    for start, end, identifier in locked
                    if start <= position < end
                ]
                valid_key = bool(
                    re.fullmatch(
                        r"[A-Za-z0-9_](?:[A-Za-z0-9_:./-]*[A-Za-z0-9_])?", match[2]
                    )
                )
                reason = (
                    (
                        "Decided suggestion "
                        + ", ".join(owners)
                        + " retains this source; separate reconciliation is needed before recovery"
                    )
                    if owners
                    else (
                        "Unsupported native citation key spelling"
                        if not valid_key
                        else ""
                    )
                )
                citations.append(
                    {
                        "raw": match[0],
                        "label": match[1],
                        "key": match[2],
                        "line": source.count("\n", 0, offset + relative + match.start())
                        + 1,
                        "known": match[2] in keys and valid_key and not owners,
                        "reason": reason,
                        "converted": False,
                    }
                )
                return f"\x01C{index}\x02"

            return _LINK.sub(replace, value)

        while pos < len(text):
            parser.position = pos
            end = parser.literal_end()
            if end is not None:
                result.extend((links(text[last:pos], last), gap(text[pos:end])))
                pos, last = end, end
            else:
                pos += 1
        result.append(links(text[last:], last))
        return "".join(result)

    for node in sorted(
        (n for n in walk(model.document.nodes) if isinstance(n, Text)),
        key=lambda n: n.start,
    ):
        start = max(node.start, header_end)
        if start >= node.end:
            continue
        pieces.append(gap(source[cursor:start]))
        pieces.append(prose(source[start : node.end], start))
        cursor = node.end
    pieces.append(gap(source[cursor:]))
    masked = "".join(pieces)

    def item(token):
        return citations[int(_TOKEN.fullmatch(token)[2])]

    def group(match):
        body = match[1]
        tokens = re.findall(_CITE, body)
        if not tokens:
            return match[0]
        entries = [item(token) for token in tokens]
        if any(not entry["known"] for entry in entries):
            for entry in entries:
                entry["reason"] = (
                    entry.get("reason")
                    or "Another citation in this group has an unknown key or protected source"
                )
            return match[0]
        syntax = [gaps[int(m[2])] for m in _TOKEN.finditer(body) if m[1] == "G"]
        if any(
            "~>" in part.replace("{~~~>", "").replace("~>~~}", "") for part in syntax
        ):
            for entry in entries:
                entry["reason"] = (
                    "A replacement crosses citation members; retain it for explicit reconciliation"
                )
            return match[0]
        years = all(re.fullmatch(r"\d{4}[a-z]?", entry["label"]) for entry in entries)
        # A comma separating linked years is source-level grouping, not a locator.
        body = re.sub(r",(?=\s*(?:" + _GAP + r"\s*)*" + _CITE + ")", ";", body)
        for token, entry in zip(tokens, entries, strict=True):
            if not re.search(r"\d{4}[a-z]?$", entry["label"]):
                for value in entries:
                    value["reason"] = (
                        "The linked text is not an identifiable author/year citation"
                    )
                return match[0]
        for token, entry in zip(tokens, entries, strict=True):
            body = body.replace(token, ("-@" if years else "@") + entry["key"])
            entry["converted"] = True
        return "[" + body + "]"

    masked = re.sub(r"\(([^()\n]*)\)", group, masked)

    def possessive_group(match):
        tokens = re.findall(_CITE, match[0])
        entries = [item(token) for token in tokens]
        first = re.fullmatch(r"(.+[’']s) \(\d{4}[a-z]?", entries[0]["label"])
        valid = first and all(
            entry["known"] and not entry.get("reason") for entry in entries
        )
        valid = valid and all(
            re.fullmatch(r"\d{4}[a-z]?", entry["label"]) for entry in entries[1:-1]
        )
        valid = valid and re.fullmatch(r"\d{4}[a-z]?\)", entries[-1]["label"])
        if not valid:
            return match[0]
        for entry in entries:
            entry["converted"] = True
        return (
            first[1] + " [" + "; ".join("-@" + entry["key"] for entry in entries) + "]"
        )

    masked = re.sub(_CITE + r"(?:,\s*" + _CITE + ")+", possessive_group, masked)

    def standalone(match):
        entry = item(match[0])
        if not entry["known"] or entry.get("reason"):
            return match[0]
        possessive = re.fullmatch(r"(.+[’']s) \((\d{4}[a-z]?)\)", entry["label"])
        narrative = re.fullmatch(r".+ \(\d{4}[a-z]?\)", entry["label"])
        parenthetical = re.fullmatch(r"\(.+, \d{4}[a-z]?\)", entry["label"])
        if possessive:
            entry["converted"] = True
            return possessive[1] + " [-@" + entry["key"] + "]"
        if narrative:
            entry["converted"] = True
            return "@" + entry["key"]
        if parenthetical:
            entry["converted"] = True
            return "[@" + entry["key"] + "]"
        return match[0]

    masked = re.sub(_CITE, standalone, masked)

    def restore(match):
        index = int(match[2])
        return gaps[index] if match[1] == "G" else citations[index]["raw"]

    result = _TOKEN.sub(restore, masked)
    converted, retained = [], []
    for entry in citations:
        record = {name: entry[name] for name in ("key", "line", "label")}
        if entry["converted"]:
            converted.append(record)
        else:
            record["reason"] = entry.get("reason") or (
                "No matching bibliography key"
                if not entry["known"]
                else "No unambiguous complete parenthetical or narrative citation"
            )
            retained.append(record)
    updated = read(result, model.document.path)
    if asdict(updated.metadata) != asdict(model.metadata):
        raise ReviewError(
            "Citation conversion changed review identities or decisions; no source was saved"
        )
    return NormalizedCitations(result, tuple(converted), tuple(retained))


def normalize_project(
    directory: Path, bibliography: Path, *, apply: bool = False
) -> dict:
    """Normalize source and reference with rollback, retaining working edits."""
    project = Project.read(directory)
    if project.source is None:
        raise ReviewError(
            "Normalize citations after migrating to the single-source format"
        )
    reference_path = project.reference_path()
    reference = read(reference_path.read_text(), project.source.reference)
    if reference.settings.get("compiled"):
        raise ReviewError(
            "Captured executed references need a separately verified citation migration"
        )
    keys = bibliography_keys(bibliography)
    configuration = project.directory / "_quarto.yml"
    project_metadata = (
        yaml.safe_load(configuration.read_text()) if configuration.exists() else {}
    )
    declared = frontmatter(project.source.text)[0].get(
        "bibliography", (project_metadata or {}).get("bibliography", [])
    )
    if isinstance(declared, str):
        declared = [declared]
    configured = isinstance(declared, list) and bibliography.resolve() in {
        (project.directory / str(name)).resolve() for name in declared
    }
    if apply and not configured:
        raise ReviewError(
            "Declare the supplied bibliography in index.qmd or _quarto.yml before applying citation recovery; no source was saved"
        )
    current = normalize_source(project.source, keys)
    frozen = normalize_source(reference, keys)
    blocked = [
        item
        for result in (current, frozen)
        for item in result.retained
        if item["reason"].startswith("Decided suggestion ")
    ]
    if apply and blocked:
        raise ReviewError(
            "Settled citation suggestions need separate reconciliation before recovery; no files were changed"
        )
    report = {
        "applied": apply,
        "blocked": blocked,
        "source": current.report(),
        "reference": frozen.report(),
        "bibliography": str(bibliography.resolve()),
        "bibliography_configured": configured,
        "formatting": "Native citation formatting follows the project's bibliography, CSL and locale; check candidate renders.",
    }
    if (
        not apply
        or current.text == project.source.text
        and frozen.text == reference.text
    ):
        return report
    source_path = project.directory / "index.qmd"
    if (
        source_path.read_text() != project.source.text
        or reference_path.read_text() != reference.text
    ):
        raise ReviewError(
            "Review source changed during citation conversion; retry against current files"
        )
    write_text(reference_path, frozen.text)
    try:
        project.source.save(source_path, current.text)
    except Exception:
        write_text(reference_path, reference.text)
        raise
    return report
