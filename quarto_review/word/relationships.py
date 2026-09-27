"""Copy the relationships and style dependencies used by imported comments."""

from __future__ import annotations

import posixpath
from copy import deepcopy
from hashlib import sha256
from pathlib import PurePosixPath
from urllib.parse import unquote

from lxml import etree

from quarto_review.errors import ReviewError
from quarto_review.word.namespaces import NS, tag
from quarto_review.word.package import WordPackage, parse_xml


def relationship_part(name: str) -> str:
    path = PurePosixPath(name)
    return str(path.parent / "_rels" / (path.name + ".rels"))


def internal_target(owner: str, target: str) -> str:
    target = unquote(target).split("#", 1)[0]
    result = posixpath.normpath(
        target.lstrip("/")
        if target.startswith("/")
        else posixpath.join(posixpath.dirname(owner), target)
    )
    if result.startswith("../") or result.startswith("/"):
        raise ReviewError(
            f"Relationship escapes the document package: {owner}: {target}"
        )
    return result


class DependencyCopier:
    """Remap imported relationships without overwriting generated package parts."""

    def __init__(self, source: WordPackage, destination: WordPackage) -> None:
        self.source = source
        self.destination = destination
        self.parts: dict[str, str] = {}
        self.styles: dict[str, str] = {}
        self.numbering: dict[str, str] = {}
        self.abstract_numbering: dict[str, str] = {}

    def copy_part(self, name: str) -> str:
        if name in self.parts:
            return self.parts[name]
        if name not in self.source.parts:
            raise ReviewError(f"An imported comment refers to missing part {name}")
        content = self.source.parts[name]
        relations = self.source.parts.get(relationship_part(name), b"")
        path = PurePosixPath(name)
        digest = sha256(content + relations).hexdigest()[:16]
        output = str(path.with_name(f"qr-{digest}-{path.name}"))
        self.parts[name] = output
        self.destination.parts[output] = content
        self.copy_type(name, output)
        if relations:
            mapping = self.copy_relationships(name, output)
            if path.suffix.lower() == ".xml":
                root = self.destination.xml(output)
                self.remap(root, mapping)
                self.destination.set_xml(output, root)
        return output

    def copy_type(self, source: str, destination: str) -> None:
        types = self.source.xml("[Content_Types].xml")
        entry = next(
            (node for node in types if node.get("PartName") == "/" + source), None
        )
        if entry is None:
            extension = PurePosixPath(source).suffix.removeprefix(".")
            entry = next(
                (node for node in types if node.get("Extension") == extension), None
            )
        if entry is None:
            raise ReviewError(f"Imported part {source} has no content type")
        output = self.destination.xml("[Content_Types].xml")
        if not any(node.get("PartName") == "/" + destination for node in output):
            etree.SubElement(
                output,
                tag("ct", "Override"),
                PartName="/" + destination,
                ContentType=entry.get("ContentType"),
            )
        self.destination.set_xml("[Content_Types].xml", output)

    def copy_relationships(self, owner: str, destination: str) -> dict[str, str]:
        name = relationship_part(owner)
        if name not in self.source.parts:
            return {}
        output_name = relationship_part(destination)
        output = (
            self.destination.xml(output_name)
            if output_name in self.destination.parts
            else etree.Element(tag("pr", "Relationships"), nsmap={None: NS["pr"]})
        )
        used = {node.get("Id") for node in output}
        mapping = {}
        for original in self.source.xml(name):
            node = deepcopy(original)
            if node.get("TargetMode") != "External":
                target = self.copy_part(internal_target(owner, node.get("Target", "")))
                node.set(
                    "Target", posixpath.relpath(target, posixpath.dirname(destination))
                )
            values = {key: value for key, value in node.attrib.items() if key != "Id"}
            existing = next(
                (
                    item
                    for item in output
                    if {key: value for key, value in item.attrib.items() if key != "Id"}
                    == values
                ),
                None,
            )
            if existing is None:
                number = 1
                while f"rIdImported{number}" in used:
                    number += 1
                identifier = f"rIdImported{number}"
                used.add(identifier)
                node.set("Id", identifier)
                output.append(node)
            else:
                identifier = existing.get("Id")
            mapping[original.get("Id")] = identifier
        self.destination.set_xml(output_name, output)
        return mapping

    @staticmethod
    def remap(root: etree._Element, mapping: dict[str, str]) -> None:
        for node in root.iter():
            for attribute, value in list(node.attrib.items()):
                if etree.QName(attribute).namespace == NS["r"]:
                    if value not in mapping:
                        raise ReviewError(
                            f"Imported XML uses undeclared relationship {value}"
                        )
                    node.set(attribute, mapping[value])

    def style(self, identifier: str) -> str:
        if identifier in self.styles:
            return self.styles[identifier]
        name = "word/styles.xml"
        if name not in self.source.parts:
            raise ReviewError(f"Imported comment style {identifier} has no styles part")
        original = next(
            (
                node
                for node in self.source.xml(name)
                if node.get(tag("w", "styleId")) == identifier
            ),
            None,
        )
        if original is None:
            raise ReviewError(f"Imported comment style {identifier} is not defined")
        output = self.destination.xml(name)
        digest = sha256(etree.tostring(original)).hexdigest()[:12]
        selected = f"qr{digest}_{identifier}"
        self.styles[identifier] = selected
        if not any(node.get(tag("w", "styleId")) == selected for node in output):
            node = deepcopy(original)
            node.set(tag("w", "styleId"), selected)
            node.attrib.pop(tag("w", "default"), None)
            for reference in node:
                if reference.tag in {
                    tag("w", key) for key in ("basedOn", "next", "link")
                }:
                    reference.set(
                        tag("w", "val"), self.style(reference.get(tag("w", "val")))
                    )
            for reference in node.iter(tag("w", "numId")):
                if reference.get(tag("w", "val")) != "0":
                    reference.set(
                        tag("w", "val"), self.number(reference.get(tag("w", "val")))
                    )
            # Recursive style copying may have added dependencies to the part.
            output = self.destination.xml(name)
            output.append(node)
            self.destination.set_xml(name, output)
        return selected

    def number(self, identifier: str) -> str:
        """Copy a comment list definition and its paragraph-style dependencies."""
        if identifier in self.numbering:
            return self.numbering[identifier]
        name = "word/numbering.xml"
        original = self.source.xml(name)
        source_number = next(
            (
                node
                for node in original
                if node.tag == tag("w", "num")
                and node.get(tag("w", "numId")) == identifier
            ),
            None,
        )
        if source_number is None:
            raise ReviewError(f"Imported comment list {identifier} is not defined")
        if name not in self.destination.parts:
            self.destination.set_xml(
                name, etree.Element(tag("w", "numbering"), nsmap={"w": NS["w"]})
            )
            self.copy_type(name, name)
            relation_name = relationship_part("word/document.xml")
            relations = self.destination.xml(relation_name)
            used = {node.get("Id") for node in relations}
            number = 1
            while f"rIdQrNumbering{number}" in used:
                number += 1
            etree.SubElement(
                relations,
                tag("pr", "Relationship"),
                Id=f"rIdQrNumbering{number}",
                Type=NS["r"] + "/numbering",
                Target="numbering.xml",
            )
            self.destination.set_xml(relation_name, relations)
        output = self.destination.xml(name)
        selected = str(
            max(
                (
                    int(node.get(tag("w", "numId")))
                    for node in output
                    if node.tag == tag("w", "num")
                ),
                default=0,
            )
            + 1
        )
        self.numbering[identifier] = selected
        node = deepcopy(source_number)
        node.set(tag("w", "numId"), selected)
        abstract_reference = node.find("./w:abstractNumId", NS)
        if abstract_reference is None:
            raise ReviewError(
                f"Imported comment list {identifier} has no abstract definition"
            )
        abstract_id = abstract_reference.get(tag("w", "val"))
        if abstract_id not in self.abstract_numbering:
            abstract = next(
                (
                    item
                    for item in original
                    if item.tag == tag("w", "abstractNum")
                    and item.get(tag("w", "abstractNumId")) == abstract_id
                ),
                None,
            )
            if abstract is None:
                raise ReviewError(
                    f"Imported abstract list {abstract_id} is not defined"
                )
            abstract = deepcopy(abstract)
            if abstract.find(".//w:lvlPicBulletId", NS) is not None:
                raise ReviewError(
                    "An imported comment uses a picture bullet; reconcile its list style before export"
                )
            new_id = str(
                max(
                    (
                        int(item.get(tag("w", "abstractNumId")))
                        for item in output
                        if item.tag == tag("w", "abstractNum")
                    ),
                    default=-1,
                )
                + 1
            )
            self.abstract_numbering[abstract_id] = new_id
            abstract.set(tag("w", "abstractNumId"), new_id)
            # Reserve identities before following styles that may refer back to
            # this numbering definition.
            abstract_reference.set(tag("w", "val"), new_id)
            insertion = next(
                (
                    index
                    for index, item in enumerate(output)
                    if item.tag == tag("w", "num")
                ),
                len(output),
            )
            output.insert(insertion, abstract)
            output.append(node)
            self.destination.set_xml(name, output)
            for reference in abstract.iter():
                if reference.tag in {
                    tag("w", kind) for kind in ("pStyle", "styleLink", "numStyleLink")
                }:
                    reference.set(
                        tag("w", "val"), self.style(reference.get(tag("w", "val")))
                    )
            output = self.destination.xml(name)
            reserved = next(
                item
                for item in output
                if item.tag == tag("w", "abstractNum")
                and item.get(tag("w", "abstractNumId")) == new_id
            )
            output.replace(reserved, abstract)
        else:
            abstract_reference.set(
                tag("w", "val"), self.abstract_numbering[abstract_id]
            )
            output.append(node)
        self.destination.set_xml(name, output)
        return selected

    def comment(self, xml: str) -> str:
        root = parse_xml(xml.encode())
        mapping = self.copy_relationships("word/comments.xml", "word/comments.xml")
        self.remap(root, mapping)
        for node in root.iter():
            if node.tag in {
                tag("w", "pStyle"),
                tag("w", "rStyle"),
                tag("w", "tblStyle"),
            }:
                node.set(tag("w", "val"), self.style(node.get(tag("w", "val"))))
            elif node.tag == tag("w", "numId") and node.get(tag("w", "val")) != "0":
                node.set(tag("w", "val"), self.number(node.get(tag("w", "val"))))
        return etree.tostring(root, encoding="unicode")
