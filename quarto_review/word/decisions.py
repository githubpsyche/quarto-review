"""Project native review decisions without modifying the archived document."""

from copy import deepcopy

from lxml import etree

from quarto_review.metadata import SuggestionMetadata
from quarto_review.word.namespaces import tag


def apply_decision(node: etree._Element, item: SuggestionMetadata) -> None:
    """Apply a non-pending decision to an owned native XML tree."""
    kind = etree.QName(node).localname
    parent = node.getparent()
    if kind.endswith("PrChange"):
        if item.status == "rejected":
            before = list(node)
            for child in list(parent):
                if child is not node:
                    parent.remove(child)
            for properties in before:
                for child in properties:
                    parent.append(deepcopy(child))
        parent.remove(node)
        return
    insertion = kind in {"ins", "moveTo", "conflictIns"}
    include = (item.status == "accepted") == insertion
    position = parent.index(node)
    children = list(node) if include else []
    parent.remove(node)
    for child in children:
        for leaf in child.iter(tag("w", "delText")):
            leaf.tag = tag("w", "t")
        parent.insert(position, child)
        position += 1
