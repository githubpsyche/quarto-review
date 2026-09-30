"""Recover review boundaries from formatted citation identities, never CSL affixes."""

from __future__ import annotations

import re

from lxml import html

from quarto_review.errors import ReviewError
from quarto_review.markers import PATTERN, decode
from quarto_review.word.namespaces import tag
from quarto_review.word.package import WordPackage


def _positions(text, links, plan):
    """Locate planned edges in unchanged formatted text or fail without guessing."""
    keys = plan["keys"]
    actual = [key for key, _, _ in links]
    if len(keys) != len(set(keys)) or actual != keys:
        raise ReviewError(
            f"Citation group {plan['id']}: formatting reordered, collapsed or omitted citation identities "
            f"(expected {keys}, found {actual}). Anchor the whole group or adjust its source order; "
            "review ranges were not broadened."
        )
    positions = []
    for item in plan["markers"]:
        index = item["index"] - 1
        _, start, end = links[index]
        before, full = item["before"], item["text"]
        if not full.strip():
            position = start if item["side"] == "prefix" else end
        else:
            low, high = (
                (links[index - 1][2] if index else 0, start)
                if item["side"] == "prefix"
                else (end, links[index + 1][1] if index + 1 < len(links) else len(text))
            )
            leading = len(full) - len(full.lstrip())
            cursor = max(0, min(len(full.strip()), len(before) - leading))
            left, right = full.strip()[:cursor], full.strip()[cursor:]

            def pattern(value):
                return r"\s+".join(re.escape(part) for part in re.split(r"\s+", value))

            expression = re.compile("(?P<left>" + pattern(left) + ")" + pattern(right))
            matches = list(expression.finditer(text, low, high))
            if len(matches) != 1:
                raise ReviewError(
                    f"Citation group {plan['id']}: cannot recover the exact review boundary "
                    f"in its {item['side']} {full!r}; the formatted wording differs."
                )
            position = matches[0].end("left")
        positions.append((position, item["token"]))
    # Crossing comments are valid, reversed endpoints for one range are not.
    starts = {}
    for position, token in positions:
        match = PATTERN.fullmatch(token)
        if match is None:
            raise ReviewError("Invalid token in generated citation boundary plan")
        kind, identifier, edge = decode(match)
        if edge == "S":
            starts[kind, identifier] = position
        elif (kind, identifier) in starts and position < starts[kind, identifier]:
            raise ReviewError(f"Citation formatting reversed review range {identifier}")
    return positions


def _slots_and_links(element):
    slots, links, size = [], [], 0

    def text_slot(node, attribute):
        nonlocal size
        value = getattr(node, attribute)
        if value:
            slots.append((node, attribute, size, size + len(value)))
            size += len(value)

    def visit(node):
        start = size
        text_slot(node, "text")
        for child in node:
            visit(child)
            text_slot(child, "tail")
        if node.tag == "a" and node.get("href", "").startswith("#ref-"):
            links.append((node.get("href")[5:], start, size))

    visit(element)
    links.sort(key=lambda entry: entry[1])
    return slots, links, "".join(getattr(node, attr) for node, attr, _, _ in slots)


def _buckets(slots, positions):
    buckets = {}
    for position, token in positions:
        for index, (_, _, start, end) in enumerate(slots):
            if start <= position <= end:
                buckets.setdefault(index, []).append((position - start, token))
                break
        else:
            raise ReviewError("A citation boundary falls outside its formatted text")
    return buckets


def restore_html(source: str, plans) -> str:
    """Restore deferred HTML boundaries without changing citation wording."""
    if not plans:
        return source
    document = html.document_fromstring(source)
    for plan in plans:
        carriers = document.xpath("//*[@id=$id][not(ancestor::nav)]", id=plan["id"])
        if len(carriers) != 1:
            raise ReviewError(
                f"Citation group {plan['id']}: expected one formatted carrier, found {len(carriers)}"
            )
        carrier = carriers[0]
        slots, links, text = _slots_and_links(carrier)
        buckets = _buckets(slots, _positions(text, links, plan))
        for index, entries in buckets.items():
            node, attr, _, _ = slots[index]
            value = getattr(node, attr)
            entries.sort(key=lambda entry: entry[0])
            setattr(node, attr, value[: entries[0][0]])
            parent = node if attr == "text" else node.getparent()
            position = 0 if attr == "text" else parent.index(node) + 1
            for number, (offset, token) in enumerate(entries):
                kind, identifier, edge = decode(PATTERN.fullmatch(token))
                marker = html.Element(
                    "span",
                    {
                        "class": "qr-boundary",
                        "data-review-kind": kind,
                        "data-review-id": identifier,
                        "data-review-edge": edge,
                    },
                )
                marker.tail = value[
                    offset : entries[number + 1][0]
                    if number + 1 < len(entries)
                    else len(value)
                ]
                parent.insert(position, marker)
                position += 1
        carrier.drop_tag()
    return (
        "<!DOCTYPE html>\n"
        + html.tostring(document, encoding="unicode", method="html")
        + "\n"
    )


def restore_word(package: WordPackage, plans) -> WordPackage:
    """Restore marker runs inside each citation before the native review writer."""
    if not plans:
        return package
    result = WordPackage(dict(package.parts))
    remaining = {plan["id"]: plan for plan in plans}
    for story in result.stories():
        root = result.xml(story)
        changed = False
        for start in list(root.iter(tag("w", "bookmarkStart"))):
            name = start.get(tag("w", "name"))
            if name not in remaining:
                continue
            plan = remaining.pop(name)
            identifier = start.get(tag("w", "id"))
            nodes = list(root.iter())
            first = nodes.index(start)
            ends = [
                node
                for node in nodes[first + 1 :]
                if node.tag == tag("w", "bookmarkEnd")
                and node.get(tag("w", "id")) == identifier
            ]
            if len(ends) != 1:
                raise ReviewError(
                    f"Citation group {name}: missing or ambiguous Word bookmark end"
                )
            finish = ends[0]
            slots, links, size, by_link = [], [], 0, {}
            for node in nodes[first + 1 : nodes.index(finish)]:
                if node.tag != tag("w", "t"):
                    continue
                value = node.text or ""
                slots.append((node, "text", size, size + len(value)))
                link = next(
                    (
                        ancestor
                        for ancestor in node.iterancestors()
                        if ancestor.tag == tag("w", "hyperlink")
                    ),
                    None,
                )
                if link is not None and link.get(tag("w", "anchor"), "").startswith(
                    "ref-"
                ):
                    key = link.get(tag("w", "anchor"))[4:]
                    if link not in by_link:
                        by_link[link] = [key, size, size + len(value)]
                        links.append(by_link[link])
                    else:
                        by_link[link][2] = size + len(value)
                size += len(value)
            text = "".join(node.text or "" for node, _, _, _ in slots)
            buckets = _buckets(slots, _positions(text, links, plan))
            for index, entries in buckets.items():
                node = slots[index][0]
                value = node.text or ""
                for offset, token in reversed(
                    sorted(entries, key=lambda entry: entry[0])
                ):
                    value = value[:offset] + token + value[offset:]
                node.text = value
                node.set(tag("xml", "space"), "preserve")
            start.getparent().remove(start)
            finish.getparent().remove(finish)
            changed = True
        if changed:
            result.set_xml(story, root)
    if remaining:
        raise ReviewError(
            f"Missing formatted citation groups in Word: {', '.join(remaining)}"
        )
    return result
