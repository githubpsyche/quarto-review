"""Finish converted Word documents with native review records and anchors."""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

from lxml import etree

from quarto_review.errors import ReviewError
from quarto_review.markers import PATTERN, decode
from quarto_review.rendering import PreparedRender
from quarto_review.word.comments import write_comments
from quarto_review.word.decisions import apply_decision
from quarto_review.word.identity import write_identity
from quarto_review.word.namespaces import COMMENT_PARTS, NS, tag
from quarto_review.word.package import WordPackage
from quarto_review.word.reader import REVISION_TAGS, read_review
from quarto_review.word.records import WordComment
from quarto_review.word.relationships import DependencyCopier
from quarto_review.word.validation import validate_package

__all__ = ["finish_document"]

_MARKER = "{urn:quarto-review}boundary"


def _properties(element: etree._Element, name: str) -> etree._Element:
    result = element.find(f"./w:{name}", NS)
    if result is None:
        result = etree.Element(tag("w", name))
        if element.tag == tag("w", "pPr") and name == "rPr":
            successor = next(
                (
                    node
                    for node in element
                    if node.tag in {tag("w", "sectPr"), tag("w", "pPrChange")}
                ),
                None,
            )
            element.insert(
                element.index(successor) if successor is not None else len(element),
                result,
            )
        else:
            element.insert(0, result)
    return result


def _split_runs(root: etree._Element) -> Counter[str]:
    """Separate conversion markers from content while retaining run properties."""
    found: Counter[str] = Counter()
    for run in list(root.iter(tag("w", "r"))):
        parent = run.getparent()
        position = parent.index(run)
        properties = run.find("./w:rPr", NS)
        atoms = []
        for leaf in run:
            if leaf is properties:
                continue
            if leaf.tag != tag("w", "t") or not PATTERN.search(leaf.text or ""):
                clone = etree.Element(run.tag, run.attrib)
                if properties is not None:
                    clone.append(deepcopy(properties))
                clone.append(deepcopy(leaf))
                atoms.append(clone)
                continue
            text = leaf.text or ""
            cursor = 0
            for match in list(PATTERN.finditer(text)) + [None]:
                end = match.start() if match else len(text)
                if cursor < end:
                    clone = etree.Element(run.tag, run.attrib)
                    if properties is not None:
                        clone.append(deepcopy(properties))
                    fragment = etree.SubElement(clone, tag("w", "t"), leaf.attrib)
                    fragment.set(tag("xml", "space"), "preserve")
                    fragment.text = text[cursor:end]
                    atoms.append(clone)
                if match is not None:
                    kind, identifier, edge = decode(match)
                    atoms.append(
                        etree.Element(_MARKER, kind=kind, id=identifier, edge=edge)
                    )
                    found[match[0]] += 1
                    cursor = match.end()
        parent.remove(run)
        for offset, atom in enumerate(atoms):
            parent.insert(position + offset, atom)
    return found


class _Finisher:
    def __init__(self, prepared: PreparedRender, directory: Path) -> None:
        self.prepared = prepared
        self.directory = directory.resolve()
        self.archives: dict[str, WordPackage] = {}
        self.archive_comments: dict[str, dict[str, WordComment]] = {}
        self.native_revisions: dict[tuple[str, str, str], etree._Element] = {}
        self.revision_ids: dict[tuple[str, str], str] = {}
        self.comment_ids: dict[str, str] = {}
        self.used_revisions: set[str] = set()
        self.used_comments: set[str] = set()
        self.keep_paragraphs: set[etree._Element] = set()
        self.comments = self.build_comments()

    def archive(self, name: str) -> WordPackage:
        if name not in self.archives:
            path = (self.directory / name).resolve()
            if not path.is_relative_to(self.directory):
                raise ReviewError(f"Review archive escapes the project: {name}")
            self.archives[name] = WordPackage.read(path)
        return self.archives[name]

    @staticmethod
    def allocate(preferred: str | None, used: set[str]) -> str:
        if preferred is not None and preferred not in used:
            used.add(preferred)
            return preferred
        number = 0
        while str(number) in used:
            number += 1
        used.add(str(number))
        return str(number)

    def build_comments(self) -> list[WordComment]:
        entries = []
        for identifier, thread in self.prepared.metadata.comments.items():
            entries.append(
                (
                    identifier,
                    self.prepared.comments[identifier],
                    thread,
                    None,
                    thread.status == "resolved",
                )
            )
            entries.extend(
                (
                    reply.id,
                    reply.body,
                    reply,
                    reply.parent_id,
                    thread.status == "resolved"
                    if reply.resolved is None
                    else reply.resolved,
                )
                for reply in thread.replies
            )
        # Reserve original numeric IDs before allocating IDs for new comments.
        for identifier, _, item, _, _ in entries:
            preferred = item.provenance.get("word_id")
            if preferred is not None and preferred not in self.used_comments:
                self.comment_ids[identifier] = self.allocate(
                    preferred, self.used_comments
                )
        for identifier, *_ in entries:
            if identifier not in self.comment_ids:
                self.comment_ids[identifier] = self.allocate(None, self.used_comments)
        result = []
        for identifier, body, item, parent, resolved in entries:
            source = item.provenance.get("source")
            original = None
            if source:
                if source not in self.archive_comments:
                    self.archive_comments[source] = {
                        comment.id: comment
                        for comment in read_review(self.archive(source)).comments
                    }
                original = self.archive_comments[source].get(
                    item.provenance.get("word_id")
                )
            comment = original or WordComment(
                self.comment_ids[identifier], item.author, item.date, body
            )
            result.append(
                replace(
                    comment,
                    id=self.comment_ids[identifier],
                    text=body,
                    author=item.author,
                    date=item.date,
                    resolved=resolved,
                    parent_id=self.comment_ids.get(parent),
                    anchors=(),
                )
            )
        return result

    def revision_id(self, identifier: str, role: str) -> str:
        key = identifier, role
        if key not in self.revision_ids:
            item = self.prepared.metadata.suggestions[identifier]
            self.revision_ids[key] = self.allocate(
                item.provenance.get("word_id"), self.used_revisions
            )
        return self.revision_ids[key]

    def revision(self, identifier: str, kind: str, role: str = "") -> etree._Element:
        item = self.prepared.metadata.suggestions[identifier]
        original_kind = item.provenance.get("kind")
        if original_kind in {"conflictIns", "conflictDel", "moveFrom", "moveTo"}:
            kind = original_kind
        attributes = {}
        if all(key in item.provenance for key in ("source", "story", "path")):
            key = tuple(item.provenance[field] for field in ("source", "story", "path"))
            if key not in self.native_revisions:
                source, story, path = key
                located = self.archive(source).xml(story).xpath(path, namespaces=NS)
                if len(located) != 1:
                    raise ReviewError(
                        f"Suggestion {identifier}: the archived native revision is missing"
                    )
                self.native_revisions[key] = located[0]
            attributes = dict(self.native_revisions[key].attrib)
        element = etree.Element(
            tag("w14" if kind.startswith("conflict") else "w", kind), attributes
        )
        element.set(tag("w", "id"), self.revision_id(identifier, role or kind))
        if item.author is not None:
            element.set(tag("w", "author"), item.author)
        else:
            element.attrib.pop(tag("w", "author"), None)
        if item.date is not None:
            element.set(tag("w", "date"), item.date)
        else:
            element.attrib.pop(tag("w", "date"), None)
        return element

    def object(self, identifier: str) -> etree._Element:
        item = self.prepared.metadata.objects[identifier]
        root = self.archive(item.source).xml(item.story)
        located = root.xpath(item.path, namespaces=NS)
        if len(located) != 1:
            raise ReviewError(f"Object {identifier}: archived equation is unavailable")
        element = located[0]
        members = []
        for member in item.revisions:
            suggestion = self.prepared.metadata.suggestions[member]
            nodes = root.xpath(suggestion.provenance["path"], namespaces=NS)
            if len(nodes) != 1:
                raise ReviewError(
                    f"Object {identifier}: revision {member} is unavailable"
                )
            node = nodes[0]
            members.append((node, suggestion))
            node.set(tag("w", "id"), self.revision_id(member, "object"))
        for node, suggestion in reversed(members):
            if suggestion.status != "pending":
                apply_decision(node, suggestion)
        return deepcopy(element)

    def property(self, identifier: str, targets: list[etree._Element]) -> None:
        item = self.prepared.metadata.suggestions[identifier]
        provenance = item.provenance
        original = self.archive(provenance["source"]).xml(provenance["story"])
        located = original.xpath(provenance["path"], namespaces=NS)
        if len(located) != 1:
            raise ReviewError(
                f"Property suggestion {identifier}: original revision is unavailable"
            )
        revision = located[0]
        original_properties = revision.getparent()
        owner = original_properties.getparent()
        is_paragraph_mark = owner.tag == tag("w", "pPr")
        if is_paragraph_mark:
            paragraphs = [target for target in targets if target.tag == tag("w", "p")]
            targets = paragraphs[:1]
        else:
            targets = [target for target in targets if target.tag == owner.tag]
        if not targets:
            raise ReviewError(
                f"Property suggestion {identifier}: no compatible output anchor"
            )
        for index, target in enumerate(targets):
            if target.tag == tag("w", "p"):
                self.keep_paragraphs.add(target)
            container = _properties(target, "pPr") if is_paragraph_mark else target
            properties = deepcopy(original_properties)
            pending = properties.find(f"./w:{provenance['kind']}", NS)
            if pending is None:
                raise ReviewError(
                    f"Property suggestion {identifier}: archived property is inconsistent"
                )
            pending.set(
                tag("w", "id"), self.revision_id(identifier, f"property:{index}")
            )
            if item.status != "pending":
                apply_decision(pending, item)
            existing = container.find(f"./w:{etree.QName(properties).localname}", NS)
            if existing is not None:
                container.replace(existing, properties)
            else:
                placeholder = _properties(container, etree.QName(properties).localname)
                container.replace(placeholder, properties)

    def story(self, root: etree._Element) -> None:
        active: list[tuple[str, str]] = []
        emitted: set[tuple[str, str]] = set()
        properties: dict[str, list[etree._Element]] = {}
        objects: list[str] = []
        comment_ranges: set[str] = set()

        def wrap(node):
            result = node
            for kind, identifier in reversed(active):
                emitted.add((kind, identifier))
                revision = self.revision(identifier, "ins" if kind == "I" else "del")
                if kind == "D":
                    for leaf in result.iter(tag("w", "t")):
                        leaf.tag = tag("w", "delText")
                revision.append(result)
                result = revision
            return result

        def visit(parent):
            had_marker = any(node.tag == _MARKER for node in parent)
            content_before = False
            for node in list(parent):
                if node.tag == _MARKER:
                    position = parent.index(node)
                    kind, identifier, edge = (
                        node.get("kind"),
                        node.get("id"),
                        node.get("edge"),
                    )
                    parent.remove(node)
                    if kind == "C":
                        if edge == "S":
                            if identifier in comment_ranges:
                                raise ReviewError(
                                    f"Comment {identifier}: duplicate range start"
                                )
                            comment_ranges.add(identifier)
                        elif identifier not in comment_ranges:
                            raise ReviewError(
                                f"Comment {identifier}: range ends without a start"
                            )
                        else:
                            comment_ranges.remove(identifier)
                        mark = etree.Element(
                            tag(
                                "w",
                                "commentRangeStart"
                                if edge == "S"
                                else "commentRangeEnd",
                            )
                        )
                        mark.set(tag("w", "id"), self.comment_ids[identifier])
                        parent.insert(position, wrap(mark))
                        if edge == "E":
                            run = etree.Element(tag("w", "r"))
                            reference = etree.SubElement(
                                run, tag("w", "commentReference")
                            )
                            reference.set(tag("w", "id"), self.comment_ids[identifier])
                            parent.insert(position + 1, wrap(run))
                    elif kind in {"I", "D"}:
                        if edge == "S":
                            active.append((kind, identifier))
                        elif not active or active[-1] != (kind, identifier):
                            raise ReviewError(
                                f"Suggestion {identifier}: crossing text revision boundaries"
                            )
                        else:
                            active.pop()
                            if (kind, identifier) not in emitted:
                                provenance = self.prepared.metadata.suggestions[
                                    identifier
                                ].provenance
                                if "source" not in provenance:
                                    raise ReviewError(
                                        f"Suggestion {identifier}: conversion lost all content"
                                    )
                                original = self.archive(provenance["source"]).xml(
                                    provenance["story"]
                                )
                                native = original.xpath(
                                    provenance["path"], namespaces=NS
                                )
                                if len(native) != 1:
                                    raise ReviewError(
                                        f"Suggestion {identifier}: archived empty revision is unavailable"
                                    )
                                copy = deepcopy(native[0])
                                # Comment anchors are rebuilt from their own boundaries.
                                for child in list(copy.iter()):
                                    if child.tag in {
                                        tag("w", "commentReference"),
                                        tag("w", "commentRangeStart"),
                                        tag("w", "commentRangeEnd"),
                                    }:
                                        child.getparent().remove(child)
                                copy.set(
                                    tag("w", "id"),
                                    self.revision_id(identifier, "empty"),
                                )
                                parent.insert(position, wrap(copy))
                    elif kind == "F":
                        if edge == "S":
                            properties[identifier] = []
                        elif identifier not in properties:
                            raise ReviewError(
                                f"Property suggestion {identifier}: range ends without a start"
                            )
                        else:
                            targets = properties.pop(identifier)
                            paragraph = (
                                parent
                                if parent.tag == tag("w", "p")
                                else next(
                                    (
                                        a
                                        for a in parent.iterancestors()
                                        if a.tag == tag("w", "p")
                                    ),
                                    None,
                                )
                            )
                            if paragraph is not None and paragraph not in targets:
                                targets.append(paragraph)
                            self.property(identifier, targets)
                    elif kind == "O":
                        if edge == "S":
                            objects.append(identifier)
                            parent.insert(position, wrap(self.object(identifier)))
                        elif not objects or objects.pop() != identifier:
                            raise ReviewError(
                                f"Equation {identifier}: crossing object boundaries"
                            )
                    continue
                if node.tag in {
                    tag("w", "r"),
                    tag("m", "oMath"),
                    tag("m", "oMathPara"),
                }:
                    if objects:
                        parent.remove(node)
                        continue
                    content_before = True
                    for targets in properties.values():
                        targets.append(node)
                    position = parent.index(node)
                    parent.remove(node)
                    parent.insert(position, wrap(node))
                elif node.tag not in {tag("w", "pPr"), tag("w", "rPr")}:
                    visit(node)
            if parent.tag == tag("w", "p"):
                for targets in properties.values():
                    targets.append(parent)
                if active and content_before:
                    runs = _properties(_properties(parent, "pPr"), "rPr")
                    kind, identifier = active[-1]
                    runs.append(
                        self.revision(
                            identifier, "ins" if kind == "I" else "del", "paragraph"
                        )
                    )
                if (
                    had_marker
                    and parent not in self.keep_paragraphs
                    and not any(node.tag not in {tag("w", "pPr")} for node in parent)
                ):
                    parent.getparent().remove(parent)

        visit(root)
        if active or properties or objects or comment_ranges:
            raise ReviewError(
                f"A review range crosses the end of a Word story: suggestions {active}, properties {list(properties)}, equations {objects}, comments {sorted(comment_ranges)}"
            )


def _anchor_replies(
    roots: dict[str, etree._Element], comments: list[WordComment]
) -> None:
    """Give new replies a native reference at their nearest anchored parent.

    Word removes unreferenced replies when saving, even when commentsExtended
    links them correctly. Imported replies can already have their own range;
    retain that range rather than replacing it with the parent's.
    """
    anchors: dict[str, list[etree._Element]] = {}
    for root in roots.values():
        for node in root.iter():
            if node.tag in {
                tag("w", "commentRangeStart"),
                tag("w", "commentRangeEnd"),
                tag("w", "commentReference"),
            }:
                anchors.setdefault(node.get(tag("w", "id")), []).append(node)
    by_id = {comment.id: comment for comment in comments}
    thread_ids: dict[str, set[str]] = {}
    for comment in comments:
        ancestor = comment
        while ancestor.parent_id is not None:
            ancestor = by_id[ancestor.parent_id]
        thread_ids.setdefault(ancestor.id, set()).add(comment.id)

    def marker(node):
        if node.tag == tag("w", "r"):
            children = [child for child in node if child.tag != tag("w", "rPr")]
            return (
                children[0]
                if len(children) == 1
                and children[0].tag == tag("w", "commentReference")
                else None
            )
        return (
            node
            if node.tag in {tag("w", "commentRangeStart"), tag("w", "commentRangeEnd")}
            else None
        )

    for comment in comments:
        if comment.parent_id is None or comment.id in anchors:
            continue
        parent = comment.parent_id
        while parent not in anchors:
            parent = by_id[parent].parent_id
            if parent is None:
                raise ReviewError(f"Reply {comment.id} has no anchored parent")
        members = next(ids for ids in thread_ids.values() if comment.id in ids)
        copies = []
        for node in anchors[parent]:
            # Word orders replies by their document references. Insert after
            # existing replies at this position, including imported boundaries.
            position = (
                node.getparent() if node.tag == tag("w", "commentReference") else node
            )
            following = position.getnext()
            while following is not None:
                candidate = marker(following)
                if candidate is None:
                    break
                if (
                    candidate.tag == node.tag
                    and candidate.get(tag("w", "id")) in members
                ):
                    position = following
                following = following.getnext()
            clone = deepcopy(node)
            clone.set(tag("w", "id"), comment.id)
            copies.append(clone)
            if node.tag == tag("w", "commentReference"):
                run = etree.Element(tag("w", "r"))
                run.append(clone)
                position.addnext(run)
            else:
                position.addnext(clone)
        anchors[comment.id] = copies


def _enable_modern_comments(package: WordPackage) -> None:
    """Use at least Word 2013 compatibility so thread resolution is available."""
    settings = package.xml("word/settings.xml")
    compat = settings.find("./w:compat", NS)
    if compat is None:
        compat = etree.Element(tag("w", "compat"))
        # CT_Settings places compatibility after note properties and before
        # document variables, revision IDs, math settings, and later features.
        successors = {
            "docVars",
            "rsids",
            "mathPr",
            "uiCompat97To2003",
            "attachedSchema",
            "themeFontLang",
            "clrSchemeMapping",
            "doNotIncludeSubdocsInStats",
            "doNotAutoCompressPictures",
            "forceUpgrade",
            "captions",
            "readModeInkLockDown",
            "smartTagType",
            "schemaLibrary",
            "shapeDefaults",
            "doNotEmbedSmartTags",
            "decimalSymbol",
            "listSeparator",
            "docId",
        }
        following = next(
            (node for node in settings if etree.QName(node).localname in successors),
            None,
        )
        settings.insert(
            settings.index(following) if following is not None else len(settings),
            compat,
        )
    mode = compat.find("./w:compatSetting[@w:name='compatibilityMode']", NS)
    if mode is None:
        mode = etree.SubElement(compat, tag("w", "compatSetting"))
        mode.set(tag("w", "name"), "compatibilityMode")
        mode.set(tag("w", "uri"), "http://schemas.microsoft.com/office/word")
    value = mode.get(tag("w", "val"), "0")
    if not value.isdigit():
        raise ReviewError(f"Invalid Word compatibility mode: {value}")
    if int(value) < 15:
        mode.set(tag("w", "val"), "15")
    package.set_xml("word/settings.xml", settings)


def finish_document(
    package: WordPackage, prepared: PreparedRender, directory: Path
) -> WordPackage:
    """Return a finished copy only after every conversion boundary is accounted for.

    ``directory`` contains the authoring project and its archived Word sources.
    The input package and source files are not modified.
    """
    result = WordPackage(dict(package.parts))
    roots = {name: result.xml(name) for name in result.stories()}
    found: Counter[str] = Counter()
    for root in roots.values():
        found.update(_split_runs(root))
    if found != prepared.expected:
        missing = list((prepared.expected - found).elements())
        extra = list((found - prepared.expected).elements())
        raise ReviewError(
            f"Word conversion changed review boundaries; missing {missing[:8]}, extra {extra[:8]}"
        )
    finisher = _Finisher(prepared, directory)
    for name, root in roots.items():
        finisher.story(root)
        if (
            name != "word/document.xml"
            and root.find(".//w:commentReference", NS) is not None
        ):
            raise ReviewError(
                f"Word does not support a comment anchored inside {name}. "
                "Keep the source comment or anchor it explicitly to the note reference in the document body."
            )
    for root in roots.values():
        _coalesce_revisions(root)
    _anchor_replies(roots, finisher.comments)
    if finisher.comments:
        _enable_modern_comments(result)
    identifiers = {
        number: source for (source, _), number in finisher.revision_ids.items()
    }
    used = {
        node.get(tag("w", "id"))
        for root in roots.values()
        for node in root.iter()
        if node.tag in REVISION_TAGS
    }
    seen = set()
    mapping = []
    for name, root in roots.items():
        tree = root.getroottree()
        for node in root.iter():
            if node.tag not in REVISION_TAGS:
                continue
            original_id = node.get(tag("w", "id"))
            if original_id in seen:
                node.set(tag("w", "id"), finisher.allocate(None, used))
            seen.add(node.get(tag("w", "id")))
            if original_id not in identifiers:
                raise ReviewError(
                    f"A native revision has no source identity: {name}:{tree.getpath(node)}"
                )
            mapping.append(
                {
                    "id": identifiers[original_id],
                    "word_id": node.get(tag("w", "id")),
                    "story": name,
                    "path": tree.getpath(node),
                    "kind": etree.QName(node).localname,
                }
            )
        result.set_xml(name, root)
    # Preserve extension attributes for imported comments before updating the
    # common thread fields. The archive retains all untouched original parts.
    for key in ("extended", "ids", "extensible"):
        name = COMMENT_PARTS[key][0]
        combined = None
        for archive in finisher.archives.values():
            if name in archive.parts:
                incoming = archive.xml(name)
                if combined is None:
                    combined = incoming
                else:
                    combined.extend(incoming)
        if combined is not None:
            result.set_xml(name, combined)
    copiers = {}
    comments = []
    items = dict(prepared.metadata.comments)
    items.update(
        {
            reply.id: reply
            for thread in prepared.metadata.comments.values()
            for reply in thread.replies
        }
    )
    source_ids = {
        number: identifier for identifier, number in finisher.comment_ids.items()
    }
    for comment in finisher.comments:
        source = items[source_ids[comment.id]].provenance.get("source")
        if source and comment.xml:
            if source not in copiers:
                copiers[source] = DependencyCopier(finisher.archive(source), result)
            comment = replace(comment, xml=copiers[source].comment(comment.xml))
        comments.append(comment)
    write_comments(result, comments)
    write_identity(
        result,
        {
            "comments": {value: key for key, value in finisher.comment_ids.items()},
            "revisions": mapping,
        },
    )
    inventory = validate_package(result)
    if inventory["comments"] != len(finisher.comments):
        raise ReviewError(
            "The completed Word file has an inconsistent comment inventory"
        )
    return result


def _coalesce_revisions(root: etree._Element) -> None:
    """Join one suggestion across runs and wholly revised citation links."""
    text_revisions = {
        tag("w", name) for name in ("ins", "del", "moveFrom", "moveTo")
    } | {tag("w14", "conflictIns"), tag("w14", "conflictDel")}
    for parent in reversed(list(root.iter())):
        previous = None
        for node in list(parent):
            if (
                previous is not None
                and node.tag in text_revisions
                and node.tag == previous.tag
                and node.attrib == previous.attrib
            ):
                previous.extend(node)
                parent.remove(node)
            else:
                previous = node
        _lift_citation_revision(parent)


def _lift_citation_revision(link: etree._Element) -> None:
    """Represent a wholly revised citation link inside its text revision.

    Word permits hyperlink fields made of runs inside an insertion or deletion,
    but not a ``w:hyperlink`` element. Using a field for this one case allows the
    adjacent separator to join the same revision without extending the link's
    visible range. Partial links and links with other attributes stay untouched.
    """
    anchor = link.get(tag("w", "anchor"), "")
    if (
        link.tag != tag("w", "hyperlink")
        or not anchor.startswith(("ref-", "ref_"))
        or set(link.attrib) != {tag("w", "anchor")}
        or '"' in anchor
        or len(link) != 1
        or link[0].tag not in {tag("w", "ins"), tag("w", "del")}
    ):
        return
    revision = link[0]
    instruction = "delInstrText" if revision.tag == tag("w", "del") else "instrText"

    def field_run(kind: str, text: str | None = None) -> etree._Element:
        run = etree.Element(tag("w", "r"))
        node = etree.SubElement(run, tag("w", instruction if text else "fldChar"))
        if text is None:
            node.set(tag("w", "fldCharType"), kind)
        else:
            node.set(tag("xml", "space"), "preserve")
            node.text = text
        return run

    children = list(revision)
    replacement = etree.Element(revision.tag, revision.attrib)
    replacement.append(field_run("begin"))
    replacement.append(field_run("", f' HYPERLINK \\l "{anchor}" '))
    replacement.append(field_run("separate"))
    replacement.extend(children)
    replacement.append(field_run("end"))
    link.getparent().replace(link, replacement)
