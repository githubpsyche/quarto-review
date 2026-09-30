"""Import Word review records into QMD and accompanying metadata."""

from __future__ import annotations

import re
import shutil
from collections import Counter
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory

from lxml import etree

from quarto_review import pandoc
from quarto_review.errors import ReviewError
from quarto_review.markers import PATTERN, decode, marker, source_boundary
from quarto_review.markup import parse
from quarto_review.metadata import (
    CommentMetadata,
    NativeObject,
    Reply,
    ReviewMetadata,
    SuggestionMetadata,
    timestamp,
)
from quarto_review.word.equations import source_views
from quarto_review.word.namespaces import NS, tag
from quarto_review.word.package import WordPackage
from quarto_review.word.reader import read_review
from quarto_review.word.records import WordComment, WordReview

__all__ = ["ImportedSource", "import_document", "prepare_import", "restore_source"]


@dataclass(frozen=True)
class ImportedSource:
    """Intermediate package and records required for a source conversion."""

    package: WordPackage
    review: WordReview
    metadata: ReviewMetadata
    comment_ids: dict[str, str]
    revision_ids: dict[tuple[str, str], str]
    expected: Counter[str]
    equations: dict[str, tuple[str, str]]


def _run(text: str) -> etree._Element:
    run = etree.Element(tag("w", "r"))
    leaf = etree.SubElement(run, tag("w", "t"))
    leaf.set(tag("xml", "space"), "preserve")
    leaf.text = text
    return run


def _provenance(comment: WordComment, archive: str) -> dict[str, str]:
    values = {
        "source": archive,
        "word_id": comment.id,
        "paragraph_id": comment.paragraph_id,
        "durable_id": comment.durable_id,
        "initials": comment.initials,
        "date_utc": comment.date_utc,
    }
    return {key: value for key, value in values.items() if value is not None}


def _metadata(
    review: WordReview, author: str, archive: str
) -> tuple[ReviewMetadata, dict[str, str], dict[tuple[str, str], str]]:
    metadata = ReviewMetadata(author=author, created_at=timestamp())
    comment_ids = {
        comment.id: f"c{comment.id.replace('-', 'n')}" for comment in review.comments
    }
    by_id = {comment.id: comment for comment in review.comments}
    for comment in review.comments:
        if comment.parent_id is not None:
            continue
        pending = [
            candidate
            for candidate in review.comments
            if candidate.parent_id is not None
        ]
        replies: list[Reply] = []
        included = {comment.id}
        while pending:
            ready = [
                candidate for candidate in pending if candidate.parent_id in included
            ]
            if not ready:
                break
            for reply in ready:
                replies.append(
                    Reply(
                        id=comment_ids[reply.id],
                        body=reply.text,
                        author=reply.author,
                        date=reply.date,
                        parent_id=comment_ids[reply.parent_id],
                        provenance=_provenance(reply, archive),
                        resolved=reply.resolved,
                    )
                )
                included.add(reply.id)
                pending.remove(reply)
        metadata.comments[comment_ids[comment.id]] = CommentMetadata(
            author=comment.author,
            date=comment.date,
            status="resolved" if comment.resolved else "open",
            replies=tuple(replies),
            provenance=_provenance(comment, archive),
        )
    revision_ids: dict[tuple[str, str], str] = {}
    for number, revision in enumerate(review.revisions, 1):
        identifier = f"s{number}"
        revision_ids[revision.story, revision.path] = identifier
        metadata.suggestions[identifier] = SuggestionMetadata(
            author=revision.author,
            date=revision.date,
            provenance={
                "source": archive,
                "word_id": revision.id,
                "kind": revision.kind,
                "story": revision.story,
                "path": revision.path,
            },
        )
    for comment in by_id.values():
        if comment.parent_id is None and not comment.anchors:
            raise ReviewError(f"Comment {comment.id} has no document anchor")
    return metadata, comment_ids, revision_ids


def prepare_import(
    package: WordPackage, *, author: str, archive: str
) -> ImportedSource:
    """Mark native boundaries before Pandoc can discard review information.

    The returned package is independent of the input. Text revisions become
    ordinary text surrounded by temporary markers. Native records remain in
    the separately extracted review model and the archived original document.
    """
    review = read_review(package)
    metadata, comment_ids, revision_ids = _metadata(review, author, archive)
    equation_groups: dict[tuple[str, str], list[str]] = {}
    for revision in review.revisions:
        match = re.match(r"^(.*?/m:oMath(?:Para)?(?:\[\d+\])?)(?:/|$)", revision.path)
        if match:
            equation_groups.setdefault((revision.story, match[1]), []).append(
                revision_ids[revision.story, revision.path]
            )
    for number, ((story, path), members) in enumerate(equation_groups.items(), 1):
        metadata.objects[f"o{number}"] = NativeObject(
            "equation", archive, story, path, tuple(members)
        )
    equations = source_views(package, metadata.objects)
    from dataclasses import replace

    for identifier, (before, after) in equations.items():
        metadata.objects[identifier] = replace(
            metadata.objects[identifier],
            source_hash=sha256((before + "\0" + after).encode()).hexdigest(),
        )
    grouped_revisions = {
        identifier
        for item in metadata.objects.values()
        for identifier in item.revisions
    }
    converted = WordPackage(dict(package.parts))
    expected: Counter[str] = Counter()
    comments_by_id = {comment.id: comment for comment in review.comments}

    def boundary(kind: str, identifier: str, edge: str) -> str:
        token = marker(kind, identifier, edge)
        expected[token] += 1
        return token

    for name in package.stories():
        root = converted.xml(name)
        ranged_comments = {
            node.get(tag("w", "id"))
            for node in root.iter(tag("w", "commentRangeStart"))
        }
        revisions = [
            revision for revision in review.revisions if revision.story == name
        ]
        located = [
            (revision, root.xpath(revision.path, namespaces=NS)[0])
            for revision in revisions
        ]
        objects = [
            (identifier, root.xpath(item.path, namespaces=NS)[0])
            for identifier, item in metadata.objects.items()
            if item.story == name
        ]
        for node in list(root.iter()):
            if node.tag in {tag("w", "commentRangeStart"), tag("w", "commentRangeEnd")}:
                identifier = comment_ids[node.get(tag("w", "id"))]
                edge = "S" if node.tag == tag("w", "commentRangeStart") else "E"
                replacement = _run(boundary("C", identifier, edge))
                parent = node.getparent()
                if parent.tag in {tag("w", "body"), tag("w", "tc")}:
                    siblings = list(parent)
                    position = siblings.index(node)
                    candidates = (
                        siblings[position + 1 :]
                        if edge == "S"
                        else list(reversed(siblings[:position]))
                    )
                    paragraphs = [
                        paragraph
                        for candidate in candidates
                        for paragraph in candidate.iter(tag("w", "p"))
                    ]
                    if not paragraphs:
                        raise ReviewError(
                            f"{name}: cannot place boundary for comment {identifier}"
                        )
                    paragraph = paragraphs[0]
                    if edge == "S":
                        paragraph.insert(
                            1 if paragraph.find("./w:pPr", NS) is not None else 0,
                            replacement,
                        )
                    else:
                        paragraph.append(replacement)
                    parent.remove(node)
                else:
                    parent.replace(node, replacement)
            elif node.tag == tag("w", "commentReference"):
                # Point comments are represented by their reference when no range exists.
                native_id = node.get(tag("w", "id"))
                comment = comments_by_id[native_id]
                if native_id not in ranged_comments and any(
                    anchor.story == name and anchor.start == anchor.end
                    for anchor in comment.anchors
                ):
                    run = node.getparent()
                    position = run.index(node)
                    for edge in ("S", "E"):
                        leaf = etree.Element(tag("w", "t"))
                        leaf.text = boundary("C", comment_ids[native_id], edge)
                        run.insert(position, leaf)
                        position += 1
                node.getparent().remove(node)
        for identifier, node in objects:
            parent = node.getparent()
            position = parent.index(node)
            parent.remove(node)
            parent.insert(position, _run(boundary("O", identifier, "S")))
            parent.insert(position + 1, _run(boundary("O", identifier, "E")))
        for revision, node in reversed(located):
            identifier = revision_ids[revision.story, revision.path]
            if identifier in grouped_revisions:
                continue
            paragraph_mark = (
                revision.kind in {"ins", "del"}
                and node.getparent().tag == tag("w", "rPr")
                and node.getparent().getparent().tag == tag("w", "pPr")
            )
            math_owner = next(
                (
                    ancestor
                    for ancestor in node.iterancestors()
                    if ancestor.tag == tag("m", "oMath")
                ),
                None,
            )
            math_property = math_owner is not None and not revision.text
            if math_property:
                node.getparent().remove(node)
                if math_owner.getparent().tag == tag("m", "oMathPara"):
                    math_owner = math_owner.getparent()
                parent = math_owner.getparent()
                position = parent.index(math_owner)
                parent.insert(position, _run(boundary("F", identifier, "S")))
                parent.insert(position + 2, _run(boundary("F", identifier, "E")))
            elif (
                revision.kind
                in {"ins", "del", "moveFrom", "moveTo", "conflictIns", "conflictDel"}
                and not paragraph_mark
            ):
                kind = "I" if revision.kind in {"ins", "moveTo", "conflictIns"} else "D"
                parent = node.getparent()
                if parent.tag not in {
                    tag("w", "p"),
                    tag("w", "r"),
                    tag("w", "hyperlink"),
                    tag("w", "ins"),
                    tag("w", "del"),
                }:
                    raise ReviewError(
                        f"{name}:{revision.path}: unsupported structural {revision.kind} revision"
                    )
                position = parent.index(node)
                children = list(node)
                for child in node.iter(tag("w", "delText")):
                    child.tag = tag("w", "t")
                for child in node.iter(tag("w", "delInstrText")):
                    child.tag = tag("w", "instrText")
                parent.remove(node)
                start_mark = _run(boundary(kind, identifier, "S"))
                end_mark = _run(boundary(kind, identifier, "E"))
                if parent.tag == tag("w", "r"):
                    start_mark, end_mark = start_mark[0], end_mark[0]
                for item in [start_mark, *children, end_mark]:
                    parent.insert(position, item)
                    position += 1
            elif revision.kind in {"rPrChange", "pPrChange"} or paragraph_mark:
                properties = node.getparent()
                owner = properties.getparent()
                properties.remove(node)
                if owner.tag == tag("w", "pPr"):
                    owner = owner.getparent()
                if owner.tag == tag("w", "r"):
                    for edge, position in [("E", len(owner)), ("S", 1)]:
                        leaf = etree.Element(tag("w", "t"))
                        leaf.text = boundary("F", identifier, edge)
                        owner.insert(position, leaf)
                elif owner.tag == tag("w", "p"):
                    owner.insert(1, _run(boundary("F", identifier, "S")))
                    owner.append(_run(boundary("F", identifier, "E")))
                else:
                    raise ReviewError(
                        f"{name}:{revision.path}: cannot anchor {revision.kind}"
                    )
            else:
                raise ReviewError(
                    f"{name}:{revision.path}: unsupported {revision.kind} revision"
                )
        # Pandoc's DOCX reader omits bookmarks placed between paragraphs.
        # Move their boundaries inside the adjacent paragraphs in the conversion
        # copy, preserving the native original and the bookmarked content.
        for bookmark in list(
            root.iter(tag("w", "bookmarkStart"), tag("w", "bookmarkEnd"))
        ):
            parent = bookmark.getparent()
            if parent.tag not in {tag("w", "body"), tag("w", "tc")}:
                continue
            start = bookmark.tag == tag("w", "bookmarkStart")
            paragraphs = (
                paragraph
                for sibling in bookmark.itersiblings(preceding=not start)
                for paragraph in (
                    list(sibling.iter(tag("w", "p")))
                    if start
                    else reversed(list(sibling.iter(tag("w", "p"))))
                )
            )
            target = next(paragraphs, None)
            if target is None:
                continue
            parent.remove(bookmark)
            if start:
                target.insert(
                    1 if target.find("./w:pPr", NS) is not None else 0, bookmark
                )
            else:
                target.append(bookmark)
        converted.set_xml(name, root)
    return ImportedSource(
        converted, review, metadata, comment_ids, revision_ids, expected, equations
    )


def _comment_body(text: str) -> str:
    """Escape Markdown punctuation in an imported plain-text comment body."""
    return re.sub(r"([\\`*_{}\[\]<>])", r"\\\1", text)


def restore_source(markdown: str, prepared: ImportedSource) -> str:
    """Restore source annotations only after checking every boundary survived."""
    actual = Counter(match[0] for match in PATTERN.finditer(markdown))
    if actual != prepared.expected:
        missing = list((prepared.expected - actual).elements())
        extra = list((actual - prepared.expected).elements())
        raise ReviewError(
            f"Conversion changed review boundaries; missing {missing[:8]}, extra {extra[:8]}"
        )
    comments = {prepared.comment_ids[c.id]: c for c in prepared.review.comments}
    emitted: set[str] = set()

    def replace(match: re.Match[str]) -> str:
        kind, identifier, edge = decode(match)
        if kind == "O":
            before, after = prepared.equations[identifier]
            return (
                "{~~" + before + "~>" + after + "~~}{#" + identifier + "}"
                if edge == "S"
                else ""
            )
        if kind in {"I", "D"}:
            delimiter = "++" if kind == "I" else "--"
            return (
                "{" + delimiter if edge == "S" else delimiter + "}{#" + identifier + "}"
            )
        result = source_boundary(identifier, edge)
        if edge == "E" and identifier not in emitted:
            emitted.add(identifier)
            if kind == "F":
                result += "{~~" + "~>" + "~~}{#" + identifier + "}"
            elif comments[identifier].parent_id is None:
                result += (
                    "{>>"
                    + _comment_body(comments[identifier].text)
                    + "<<}{#"
                    + identifier
                    + "}"
                )
        return result

    source = PATTERN.sub(replace, markdown)
    document = parse(source, "index.qmd")
    prepared.metadata.validate({"index.qmd": document})
    return source


def import_document(
    source: Path,
    destination: Path,
    *,
    author: str,
    single_source: bool = False,
    bibliography: Path | None = None,
) -> ReviewMetadata:
    """Create a new source project while preserving the original Word file.

    Existing destinations are rejected. Conversion happens in a temporary
    directory and is published only after every review boundary is accounted for.
    """
    source, destination = source.resolve(), destination.resolve()
    if bibliography is not None and not single_source:
        raise ReviewError(
            "Citation recovery requires single-source import; omit --legacy"
        )
    if bibliography is not None:
        bibliography = bibliography.resolve()
        from quarto_review.citations import bibliography_keys

        citation_keys = bibliography_keys(bibliography)
    if destination.exists():
        raise ReviewError(f"Import destination already exists: {destination}")
    package = WordPackage.read(source)
    digest = sha256(source.read_bytes()).hexdigest()
    archive = (
        f"assets/review/{digest}.docx"
        if single_source
        else f"review/exchanges/{digest}.docx"
    )
    prepared = prepare_import(package, author=author, archive=archive)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(
        prefix=".quarto-review-import-", dir=destination.parent
    ) as folder:
        project = Path(folder) / "project"
        project.mkdir()
        intermediate = Path(folder) / "marked.docx"
        prepared.package.write(intermediate)
        markdown = pandoc.run(
            [
                str(intermediate),
                "--from=docx",
                "--to=markdown-smart+pipe_tables-simple_tables-multiline_tables-grid_tables",
                "--standalone",
                "--wrap=none",
                "--extract-media=assets",
                "--track-changes=all",
            ],
            directory=project,
        )
        qmd = restore_source(markdown, prepared)
        prepared.metadata.imports[digest] = archive
        if single_source:
            from quarto_review.migration import convert_verified

            qmd = convert_verified(parse(qmd, "index.qmd"), prepared.metadata)
        else:
            prepared.metadata.write(project / "review.yml")
        if bibliography is not None:
            import json

            import yaml

            from quarto_review.citations import normalize_source
            from quarto_review.source import frontmatter, read

            normalized = normalize_source(read(qmd), citation_keys)
            qmd = normalized.text
            front, body_start = frontmatter(qmd)
            front["bibliography"] = bibliography.name
            qmd = (
                "---\n"
                + yaml.safe_dump(front, sort_keys=False, allow_unicode=True)
                + "---\n"
                + qmd[body_start:]
            )
            shutil.copyfile(bibliography, project / bibliography.name)
            report = normalized.report()
            fields = []
            for story in package.stories():
                root = package.xml(story)
                instructions = " ".join(
                    root.xpath(
                        ".//w:instrText/text() | .//w:fldSimple/@w:instr", namespaces=NS
                    )
                )
                if re.search(
                    r"CITATION|CSL_CITATION|ZOTERO_ITEM|EN\.CITE", instructions, re.I
                ):
                    fields.append(
                        {
                            "story": story,
                            "reason": "Citation-manager fields require explicit recovery; this pass recovers reference links only. The original Word file is archived.",
                        }
                    )
            report["native_fields"] = fields
            location = project / ".quarto/review/citation-import.json"
            location.parent.mkdir(parents=True, exist_ok=True)
            location.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        (project / "index.qmd").write_text(qmd, encoding="utf-8")
        archived = project / archive
        archived.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, archived)
        from quarto_review.project import Project, capture_reference

        capture_reference(Project.read(project))
        project.rename(destination)
    return prepared.metadata
