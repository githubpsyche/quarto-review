"""Read document packages and replace selected parts atomically."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile

from lxml import etree

from quarto_review.errors import ReviewError

__all__ = ["WordPackage", "parse_xml", "serialize_xml"]


def parse_xml(data: bytes) -> etree._Element:
    """Parse an XML part without external entities or network access."""
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    return etree.fromstring(data, parser)


def serialize_xml(root: etree._Element) -> bytes:
    """Serialize a Word XML part with an explicit declaration."""
    return etree.tostring(root, encoding="UTF-8", xml_declaration=True, standalone=True)


@dataclass
class WordPackage:
    """Named parts of an unpacked DOCX, retained as bytes until edited."""

    parts: dict[str, bytes]

    @classmethod
    def read(cls, path: Path) -> WordPackage:
        """Read a DOCX and reject duplicate or missing required parts."""
        try:
            with ZipFile(path) as archive:
                names = archive.namelist()
                if len(names) != len(set(names)):
                    raise ReviewError(f"{path}: duplicate package parts")
                parts = {name: archive.read(name) for name in names}
        except (BadZipFile, OSError) as error:
            raise ReviewError(f"Cannot read Word document {path}: {error}") from error
        for name in ("[Content_Types].xml", "word/document.xml"):
            if name not in parts:
                raise ReviewError(f"{path}: missing {name}")
        return cls(parts)

    def xml(self, name: str) -> etree._Element:
        """Parse a named part, identifying the part when parsing fails."""
        try:
            return parse_xml(self.parts[name])
        except (KeyError, etree.XMLSyntaxError) as error:
            raise ReviewError(f"Cannot read XML part {name}: {error}") from error

    def set_xml(self, name: str, root: etree._Element) -> None:
        """Replace one XML part; other package parts remain untouched."""
        self.parts[name] = serialize_xml(root)

    def stories(self) -> tuple[str, ...]:
        """Return parts that can contain document text and review anchors."""
        return tuple(
            name
            for name in sorted(self.parts)
            if re.fullmatch(
                r"word/(document|footnotes|endnotes|header\d+|footer\d+)\.xml", name
            )
        )

    def write(self, path: Path) -> None:
        """Write a complete package before replacing the destination."""
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary: Path | None = None
        try:
            with NamedTemporaryFile(
                dir=path.parent, suffix=".docx", delete=False
            ) as file:
                temporary = Path(file.name)
                with ZipFile(file, "w", compression=ZIP_DEFLATED) as archive:
                    for name, content in self.parts.items():
                        archive.writestr(name, content)
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
