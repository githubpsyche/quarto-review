"""Apply explicitly configured settings to newly rendered Word review files."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from zipfile import ZipFile

import yaml
from lxml import etree

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
# CT_Settings children preceding trackRevisions, in schema order.
PRECEDING = set(
    """writeProtection view zoom removePersonalInformation
removeDateAndTime doNotDisplayPageBoundaries displayBackgroundShape
printPostScriptOverText printFractionalCharacterWidth printFormsData
embedTrueTypeFonts embedSystemFonts saveSubsetFonts saveFormsData mirrorMargins
alignBordersAndEdges bordersDoNotSurroundHeader bordersDoNotSurroundFooter
gutterAtTop hideSpellingErrors hideGrammaticalErrors activeWritingStyle proofState
formsDesign attachedTemplate linkStyles stylePaneFormatFilter stylePaneSortMethod
documentType mailMerge revisionView""".split()
)


def track_changes(path: Path, enabled: bool) -> bool:
    """Change only settings.xml; retain all comment and revision parts byte-for-byte."""
    with ZipFile(path) as archive:
        infos = archive.infolist()
        parts = {info.filename: archive.read(info.filename) for info in infos}
        comment = archive.comment
    original = parts["word/settings.xml"]
    root = etree.fromstring(original)
    flags = root.findall(f"{{{W}}}trackRevisions")
    if len(flags) > 1:
        raise ValueError(f"Duplicate Track Changes settings in {path}")
    if flags:
        flag = flags[0]
        current = flag.get(f"{{{W}}}val", "true") not in {"0", "false", "off"}
        if current == enabled:
            return False
    else:
        flag = etree.Element(f"{{{W}}}trackRevisions")
        position = next(
            (
                i
                for i, node in enumerate(root)
                if etree.QName(node).localname not in PRECEDING
            ),
            len(root),
        )
        root.insert(position, flag)
    flag.set(f"{{{W}}}val", "true" if enabled else "false")
    parts["word/settings.xml"] = etree.tostring(
        root, encoding="UTF-8", xml_declaration=True, standalone=True
    )
    with tempfile.NamedTemporaryFile(
        dir=path.parent, suffix=".docx", delete=False
    ) as tmp:
        temporary = Path(tmp.name)
    try:
        with ZipFile(temporary, "w") as archive:
            archive.comment = comment
            for info in infos:
                archive.writestr(info, parts[info.filename])
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return True


def apply_project_options(directory: Path, outputs: list[str]) -> None:
    """Read project-wide options; omission preserves the reference document setting."""
    directory = directory.resolve()
    config = yaml.safe_load((directory / "_quarto.yml").read_text()) or {}
    options = config.get("quarto-review", {}).get("word", {})
    if not isinstance(options, dict):
        raise ValueError("quarto-review.word must be a mapping")
    if "track-changes" not in options:
        return
    enabled = options["track-changes"]
    if type(enabled) is not bool:
        raise ValueError("quarto-review.word.track-changes must be true or false")
    plans = [
        json.loads(p.read_text())
        for p in (directory / ".quarto/review/plans").glob("*.json")
    ]
    for output in outputs:
        path = (directory / output).resolve()
        if path.suffix.lower() != ".docx":
            continue
        if not path.is_relative_to(directory):
            raise ValueError(f"Word output is outside the project: {path}")
        # A repeated finish call must not modify an already finished package.
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if any(
            Path(p["output"]).name == path.name and p.get("finished_hash") == digest
            for p in plans
        ):
            continue
        track_changes(path, enabled)


if __name__ == "__main__":
    apply_project_options(
        Path(os.environ["QUARTO_REVIEW_PROJECT"]),
        os.environ["QUARTO_PROJECT_OUTPUT_FILES"].splitlines(),
    )
