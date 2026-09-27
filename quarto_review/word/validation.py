"""Check package relationships and review invariants independently of export code."""

from __future__ import annotations

from collections import Counter
from pathlib import PurePosixPath

from quarto_review.errors import ReviewError
from quarto_review.markers import PATTERN
from quarto_review.word.namespaces import NS, tag
from quarto_review.word.package import WordPackage
from quarto_review.word.reader import REVISION_TAGS, read_review
from quarto_review.word.relationships import internal_target, relationship_part


def validate_package(package: WordPackage) -> dict:
    """Raise on missing dependencies, duplicate identities, or broken ranges.

    This is an invariant check, not an OOXML schema validator. The development
    verifier uses Microsoft's independent Open XML SDK for schema validation.
    """
    for name in package.parts:
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts:
            raise ReviewError(f"Invalid package part name {name}")
        if name.endswith(".rels"):
            root = package.xml(name)
            ids = [node.get("Id") for node in root]
            if None in ids or len(set(ids)) != len(ids):
                raise ReviewError(
                    f"Duplicate or missing relationship identity in {name}"
                )
            owner = (
                ""
                if name == "_rels/.rels"
                else str(path.parent.parent / path.name.removesuffix(".rels"))
            )
            for node in root:
                if node.get("TargetMode") != "External":
                    target = internal_target(owner, node.get("Target", ""))
                    if target not in package.parts:
                        raise ReviewError(
                            f"{name}: relationship {node.get('Id')} points to missing {target}"
                        )
        elif name.endswith(".xml"):
            root = package.xml(name)
            relationships = relationship_part(name)
            ids = (
                {node.get("Id") for node in package.xml(relationships)}
                if relationships in package.parts
                else set()
            )
            for node in root.iter():
                for attribute, value in node.attrib.items():
                    if attribute.startswith("{" + NS["r"] + "}") and value not in ids:
                        raise ReviewError(f"{name}: undeclared relationship {value}")
    revision_ids = []
    reference_ids = []
    for name in package.stories():
        root = package.xml(name)
        if any(PATTERN.search(value) for value in root.itertext()):
            raise ReviewError(f"{name}: an unfinished conversion marker remains")
        revision_ids.extend(
            node.get(tag("w", "id"))
            for node in root.iter()
            if node.tag in REVISION_TAGS
        )
        reference_ids.extend(
            node.get(tag("w", "id")) for node in root.iter(tag("w", "commentReference"))
        )
    for label, identifiers in (
        ("revision", revision_ids),
        ("comment reference", reference_ids),
    ):
        repeated = [key for key, count in Counter(identifiers).items() if count > 1]
        if None in identifiers or repeated:
            raise ReviewError(
                f"Duplicate or missing {label} identities: {repeated[:8]}"
            )
    review = read_review(package)
    roots = [comment for comment in review.comments if comment.parent_id is None]
    for comment in review.comments:
        if not comment.anchors or comment.id not in reference_ids:
            raise ReviewError(f"Comment {comment.id} is missing its range or reference")
    return {
        "parts": len(package.parts),
        "comments": len(review.comments),
        "threads": len(roots),
        "revisions": len(review.revisions),
    }
