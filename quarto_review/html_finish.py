"""Finish review excerpts from the formatted manuscript, without another citeproc run."""

from __future__ import annotations

from collections import Counter

from lxml import html

from quarto_review.discussion import _safe_html
from quarto_review.errors import ReviewError
from quarto_review.markers import marker


def content_roots(document):
    """Return non-overlapping manuscript roots, excluding navigation and cards."""
    mains = document.xpath("//main")
    if not mains:
        body = document.find("body")
        return [body if body is not None else document]
    roots = list(mains)
    for title in document.xpath('//*[@id="title-block-header"]'):
        if not any(main is title or main in title.iterancestors() for main in mains):
            roots.append(title)
    return roots


def _ignored(node):
    if not isinstance(node.tag, str):
        return True
    return (
        node.tag in {"script", "style", "nav"}
        or node.get("id") in {"quarto-review", "TOC"}
        or "qr-panel" in node.get("class", "").split()
    )


def _boundary(node):
    if "qr-boundary" not in node.get("class", "").split():
        return None
    return tuple(node.get("data-review-" + name) for name in ("kind", "id", "edge"))


def _range_body(roots, kind, identifier):
    """Clone only selected content, preserving inline/paragraph structure.

    Before cards choose nested original alternatives; after cards choose nested
    proposed alternatives. Ancestor revisions do not suppress a child's card.
    """
    active = set()
    ancestors = set()
    target = (kind, identifier)
    opposite = "I" if kind == "D" else "D"
    found = 0

    def included():
        return target in active and not any(
            other[0] == opposite and other not in ancestors for other in active
        )

    def visit(node):
        nonlocal ancestors, found
        if _ignored(node):
            return None
        boundary = _boundary(node)
        if boundary:
            current_kind, current_id, edge = boundary
            key = (current_kind, current_id)
            if edge == "S":
                if key == target:
                    ancestors = set(active)
                    found += 1
                active.add(key)
            else:
                active.discard(key)
            return None
        copy = html.Element(node.tag, dict(node.attrib))
        if node.text and included():
            copy.text = node.text
        for child in node:
            piece = visit(child)
            if piece is not None:
                copy.append(piece)
            if child.tail and included():
                if len(copy):
                    copy[-1].tail = (copy[-1].tail or "") + child.tail
                else:
                    copy.text = (copy.text or "") + child.tail
        if copy.text or len(copy):
            return copy
        return None

    container = html.Element("div")
    for root in roots:
        copied = visit(root)
        if copied is not None:
            container.append(copied)
    return container, found


def finish_html(source: str, expected: dict[str, int]) -> str:
    """Verify rendered boundaries and replace citation previews from their ranges.

    This does not add citations to citeproc's input, change the bibliography,
    execute code, or write manuscript source. Unsafe preview markup is stripped.
    """
    document = html.document_fromstring(source)
    roots = content_roots(document)
    found = Counter()
    for root in roots:
        for node in root.iter():
            if any(_ignored(a) for a in [node, *node.iterancestors()]):
                continue
            boundary = _boundary(node)
            if boundary:
                found[marker(*boundary)] += 1
    if found != Counter(expected):
        missing = Counter(expected) - found
        extra = found - Counter(expected)
        raise ReviewError(
            "HTML formatting changed review boundaries; no finished output was saved. "
            f"Missing: {dict(missing)}; unexpected: {dict(extra)}"
        )
    changed = False
    for card in document.xpath('//*[@class="qr-suggestion"]'):
        if card.get("data-status") != "pending":
            continue
        identifier = card.get("data-anchor-id") or card.get("data-review-id")
        for side, kind in (("before", "D"), ("after", "I")):
            bodies = card.xpath(
                './section[@class=$section]/div[@data-qr-rendered-preview="true"]',
                section="qr-change-" + side,
            )
            for body in bodies:
                copied, ranges = _range_body(roots, kind, identifier)
                if not ranges:
                    raise ReviewError(
                        f"Suggestion {identifier}: no rendered {side} range for its citation preview"
                    )
                replacement = html.fragment_fromstring(
                    '<div class="qr-body" data-qr-rendered-preview="true">'
                    + _safe_html(copied)
                    + "</div>"
                )
                body.getparent().replace(body, replacement)
                changed = True
    if not changed:
        return source
    rendered = html.tostring(document, encoding="unicode", method="html")
    return "<!DOCTYPE html>\n" + rendered + "\n"
