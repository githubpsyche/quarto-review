"""Render independent Markdown messages in one Pandoc call, with safe HTML."""

from __future__ import annotations

import json
from html import escape
from pathlib import Path
from urllib.parse import urlsplit

from lxml import etree, html

from quarto_review import pandoc
from quarto_review.errors import ReviewError

_TAGS = set(
    "p em strong a code pre ul ol li blockquote br hr h1 h2 h3 h4 h5 h6".split()
)


def _safe_link(value: str) -> bool:
    if any(ord(char) <= 32 or ord(char) == 127 for char in value):
        return False
    try:
        return urlsplit(value).scheme.lower() in {"", "http", "https", "mailto"}
    except ValueError:
        return False


def _safe_html(element) -> str:
    for child in list(element.iterdescendants()):
        if child.tag == "img":
            # Review messages never load remote images or other active content.
            child.tag, child.text = "span", child.get("alt", "")
        attributes = dict(child.attrib)
        child.attrib.clear()
        if child.tag == "a":
            if _safe_link(attributes.get("href", "")):
                child.set("href", attributes.get("href", ""))
            if "title" in attributes:
                child.set("title", attributes["title"])
        elif child.tag == "ol" and attributes.get("start", "").isdigit():
            child.set("start", attributes["start"])
        if child.tag not in _TAGS:
            child.drop_tag()
    return escape(element.text or "") + "".join(
        etree.tostring(child, method="html", encoding="unicode") for child in element
    )


def render_messages(messages: dict[str, tuple[str, str]]) -> dict[str, str]:
    """Return body containers, retaining plain bodies and batching Markdown ones.

    Only basic CommonMark is supported here: prose, emphasis, lists, links,
    blockquotes and code. Raw HTML is literal and links use a scheme allowlist.
    Source messages are never rewritten by rendering.
    """
    result, markdown = {}, {}
    for identifier, (body, format) in messages.items():
        if format == "plain":
            result[identifier] = (
                '<div class="qr-body qr-body-plain">' + escape(body) + "</div>"
            )
        elif format == "markdown":
            markdown[identifier] = body
        else:
            raise ReviewError(f"Message {identifier}: unsupported body format {format}")
    if not markdown:
        return result
    reader = Path(__file__).with_name("extension") / "discussion-reader.lua"
    converted = pandoc.run(
        ["--from=" + str(reader), "--to=html5", "--wrap=none"],
        source=json.dumps(list(markdown.values())),
    )
    container = html.fragment_fromstring(converted, create_parent="div")
    if len(container) != len(markdown):
        raise ReviewError("Markdown discussion conversion changed the message count")
    for number, (identifier, element) in enumerate(zip(markdown, container), 1):
        if element.tag != "div" or element.get("id") != f"message-{number}":
            raise ReviewError(
                "Markdown discussion conversion changed message identities"
            )
        result[identifier] = '<div class="qr-body">' + _safe_html(element) + "</div>"
    return result
