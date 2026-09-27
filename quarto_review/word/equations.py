"""Keep native equation revisions associated with their source equation."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory

from lxml import etree

from quarto_review import pandoc
from quarto_review.errors import ReviewError
from quarto_review.markers import PATTERN, decode, marker
from quarto_review.metadata import NativeObject, ReviewMetadata
from quarto_review.word.decisions import apply_decision
from quarto_review.word.namespaces import NS, tag
from quarto_review.word.package import WordPackage


def equation_view(element: etree._Element, view: str) -> etree._Element:
    """Project equation content while leaving the archived native XML intact."""
    result = deepcopy(element)
    for node in reversed(list(result.iter())):
        if node.tag not in {
            tag("w", name) for name in ("ins", "del", "moveFrom", "moveTo")
        }:
            continue
        parent = node.getparent()
        position = parent.index(node)
        insertion = node.tag in {tag("w", "ins"), tag("w", "moveTo")}
        include = (view == "proposed") == insertion
        children = list(node) if include else []
        parent.remove(node)
        for child in children:
            for leaf in child.iter(tag("w", "delText")):
                leaf.tag = tag("w", "t")
            parent.insert(position, child)
            position += 1
    for node in list(result.iter(tag("m", "r"))):
        if not any(child.tag in {tag("m", "t"), tag("w", "t")} for child in node):
            node.getparent().remove(node)
    return result


def source_views(
    package: WordPackage, objects: dict[str, NativeObject]
) -> dict[str, tuple[str, str]]:
    """Convert all equation views in one Pandoc call, without losing member IDs."""
    if not objects:
        return {}
    batch = WordPackage(dict(package.parts))
    root = etree.Element(tag("w", "document"), nsmap={"w": NS["w"], "m": NS["m"]})
    body = etree.SubElement(root, tag("w", "body"))
    originals = {name: package.xml(name) for name in package.stories()}
    for identifier, item in objects.items():
        equation = originals[item.story].xpath(item.path, namespaces=NS)[0]
        for view in ("original", "proposed"):
            paragraph = etree.SubElement(body, tag("w", "p"))
            token_id = f"{identifier}:{view}"
            for edge, content in [("S", equation_view(equation, view)), ("E", None)]:
                run = etree.SubElement(paragraph, tag("w", "r"))
                text = etree.SubElement(run, tag("w", "t"))
                text.set(tag("xml", "space"), "preserve")
                token = marker("O", token_id, edge)
                text.text = token + " " if edge == "S" else " " + token
                if content is not None:
                    paragraph.append(content)
    batch.set_xml("word/document.xml", root)
    with TemporaryDirectory(prefix="quarto-review-math-") as folder:
        path = Path(folder) / "equations.docx"
        batch.write(path)
        document = json.loads(pandoc.run([str(path), "--from=docx", "--to=json"]))

        # Pandoc's Markdown writer strips trailing math whitespace, including
        # the space in TeX's control-space command. An empty group keeps that
        # command intact without changing the equation's visible content.
        def protect_math(value):
            if isinstance(value, dict):
                if value.get("t") == "Math" and value["c"][1].endswith("\\ "):
                    value["c"][1] += "{}"
                for child in value.values():
                    protect_math(child)
            elif isinstance(value, list):
                for child in value:
                    protect_math(child)

        protect_math(document)
        markdown = pandoc.run(
            ["--from=json", "--to=markdown", "--wrap=none"],
            source=json.dumps(document),
        )
    values: dict[str, str] = {}
    active: dict[str, int] = {}
    for match in PATTERN.finditer(markdown):
        kind, identifier, edge = decode(match)
        if kind != "O":
            raise ReviewError("Unexpected review boundary while reading equations")
        if edge == "S":
            active[identifier] = match.end()
        elif identifier in active:
            values[identifier] = markdown[
                active.pop(identifier) : match.start()
            ].strip()
    result = {}
    for identifier in objects:
        before, after = (
            values.get(f"{identifier}:original"),
            values.get(f"{identifier}:proposed"),
        )
        if before is None or after is None:
            raise ReviewError(
                f"Equation {identifier} was lost during source conversion"
            )
        result[identifier] = before, after
    return result


def decided_views(
    metadata: ReviewMetadata, directory: Path
) -> dict[str, tuple[str, str]]:
    """Project partial equation decisions, caching the resulting source views."""
    groups = {}
    for identifier, item in metadata.objects.items():
        if any(
            metadata.suggestions[member].status != "pending"
            for member in item.revisions
        ):
            groups.setdefault(item.source, {})[identifier] = item
    output = {}
    for source, objects in groups.items():
        path = (directory / source).resolve()
        if not path.is_relative_to(directory.resolve()):
            raise ReviewError(f"Equation archive escapes the project: {source}")
        decisions = {
            member: metadata.suggestions[member]
            for item in objects.values()
            for member in item.revisions
        }
        digest = sha256(
            path.read_bytes()
            + json.dumps(
                {
                    "objects": {key: asdict(item) for key, item in objects.items()},
                    "decisions": {key: asdict(item) for key, item in decisions.items()},
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        cached = directory / ".quarto/review/equations" / f"{digest}.json"
        if cached.is_file():
            output.update(
                {
                    key: tuple(value)
                    for key, value in json.loads(cached.read_text()).items()
                }
            )
            continue
        package = WordPackage.read(path)
        roots = {
            name: package.xml(name)
            for name in {item.story for item in objects.values()}
        }
        located = []
        for member, item in decisions.items():
            nodes = roots[item.provenance["story"]].xpath(
                item.provenance["path"], namespaces=NS
            )
            if len(nodes) != 1:
                raise ReviewError(f"Equation revision {member} has no archived source")
            located.append((nodes[0], item))
        for node, item in reversed(located):
            if item.status != "pending":
                apply_decision(node, item)
        for name, root in roots.items():
            package.set_xml(name, root)
        values = source_views(package, objects)
        from quarto_review.project import write_text

        write_text(cached, json.dumps(values, ensure_ascii=False) + "\n")
        output.update(values)
    return output
