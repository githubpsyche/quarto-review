"""Reconcile Word feedback against its exact retained export.

Source edits are applied only when their anchors are unambiguous and concurrent
changes agree. A conflicting return remains archived with a structured report;
the authoring files and reference are left intact for a reviewed resolution.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory

from quarto_review import pandoc
from quarto_review.authoring import escape_comment
from quarto_review.comparison import _edits
from quarto_review.errors import ReviewError
from quarto_review.exchanges import load_export
from quarto_review.markup import (
    Boundary,
    Change,
    Comment,
    Document,
    Highlight,
    Text,
    parse,
    serialize,
)
from quarto_review.markup import project as project_text
from quarto_review.metadata import (
    CommentMetadata,
    Reply,
    ReviewMetadata,
    SuggestionMetadata,
    timestamp,
)
from quarto_review.project import Project, write_text
from quarto_review.word.identity import read_identity
from quarto_review.word.importer import prepare_import, restore_source
from quarto_review.word.package import WordPackage
from quarto_review.word.reader import read_review
from quarto_review.word.records import WordRevision
from quarto_review.word.return_checks import unsupported_changes


@dataclass(frozen=True)
class Span:
    start: int
    end: int
    node: Text


def projection(
    document: Document, decisions: dict[str, str]
) -> tuple[str, list[Span], dict[str, tuple[int, int]]]:
    pieces, spans, locations = [], [], {}
    position = 0

    def visit(nodes):
        nonlocal position
        for node in nodes:
            start = position
            if isinstance(node, Text):
                pieces.append(node.value)
                spans.append(Span(position, position + len(node.value), node))
                position += len(node.value)
            elif isinstance(node, Change):
                visit(
                    node.before if decisions.get(node.id) == "rejected" else node.after
                )
                locations[node.id] = start, position
            elif isinstance(node, (Comment, Highlight)):
                visit(node.content)
            elif isinstance(node, Boundary):
                if node.edge == "start":
                    locations[node.id] = position, position
                elif node.id in locations:
                    locations[node.id] = locations[node.id][0], position

    visit(document.nodes)
    return "".join(pieces), spans, locations


def locate(
    document: Document,
    decisions: dict[str, str],
    text: str,
    *,
    left: str = "",
    right: str = "",
    allow_ranges: bool = False,
) -> tuple[int, int]:
    """Locate exact text with optional surrounding context in the current source."""
    content, spans, _ = projection(document, decisions)
    if text:
        candidates = [match.start() for match in re.finditer(re.escape(text), content)]
    else:
        context = right[:96] if right else left[-96:]
        if not context:
            raise ReviewError(
                "An insertion needs surrounding text to locate its source position"
            )
        pattern = "".join(
            r"\s+" if part.isspace() else re.escape(part)
            for part in re.findall(r"\s+|\S+", context)
        )
        candidates = [
            match.start() if right else match.end()
            for match in re.finditer(pattern, content)
        ]
    if len(candidates) != 1:
        # Conversion often normalizes whitespace. Use a short word context only
        # to disambiguate exact matches, never to replace the selected wording.
        before = re.findall(r"\S+", left)[-5:]
        after = re.findall(r"\S+", right)[:5]
        candidates = [
            offset
            for offset in candidates
            if (
                not before
                or re.findall(r"\S+", content[max(0, offset - 512) : offset])[
                    -len(before) :
                ]
                == before
            )
            and (
                not after
                or re.findall(
                    r"\S+", content[offset + len(text) : offset + len(text) + 512]
                )[: len(after)]
                == after
            )
        ]
    if len(candidates) != 1:
        raise ReviewError(
            f"The returned passage has {len(candidates)} unambiguous source matches: {text[:80]!r}"
        )
    start, end = candidates[0], candidates[0] + len(text)
    first = next((span for span in spans if span.start <= start < span.end), None)
    if first is None:
        first = next((span for span in reversed(spans) if span.end == start), None)
    last = (
        first
        if start == end
        else next(
            (span for span in reversed(spans) if span.start < end <= span.end), None
        )
    )
    if (
        first is None
        or last is None
        or (not allow_ranges and first.node is not last.node)
    ):
        raise ReviewError(
            "The returned passage crosses source annotations or generated content"
        )
    return first.node.start + start - first.start, last.node.start + end - last.start


def _read_source(
    package: WordPackage, author: str, archive: str, directory: Path
) -> tuple[Document, ReviewMetadata]:
    prepared = prepare_import(package, author=author, archive=archive)
    with TemporaryDirectory(prefix="quarto-review-return-") as folder:
        marked = Path(folder) / "marked.docx"
        prepared.package.write(marked)
        markdown = pandoc.run(
            [
                str(marked),
                "--from=docx",
                "--to=markdown-smart+pipe_tables-simple_tables-multiline_tables-grid_tables",
                "--standalone",
                "--wrap=none",
                "--track-changes=all",
            ],
            directory=directory,
        )
    return parse(restore_source(markdown, prepared), "returned.qmd"), prepared.metadata


def _rewrite(document: Document, replacements: dict[str, Comment]) -> Document:
    def visit(nodes):
        result = []
        for node in nodes:
            if isinstance(node, Comment):
                if node.id in replacements:
                    node = replace(node, body=replacements[node.id].body)
                node = replace(node, content=visit(node.content))
            elif isinstance(node, Highlight):
                node = replace(node, content=visit(node.content))
            elif isinstance(node, Change):
                node = replace(node, before=visit(node.before), after=visit(node.after))
            result.append(node)
        return tuple(result)

    return parse(serialize(visit(document.nodes)), document.path)


def _infer_decision(
    document: Document, members: list[str], incoming: str, decisions: dict[str, str]
) -> str:
    """Infer a complete native accept/reject action from its retained text context."""
    candidates = {}
    passages = {}
    for state in ("accepted", "rejected"):
        content, _, locations = projection(
            document, {**decisions, **dict.fromkeys(members, state)}
        )
        if any(member not in locations for member in members):
            raise ReviewError(
                "The removed native revision belongs to an equation or formatting object"
            )
        start = min(locations[member][0] for member in members)
        end = max(locations[member][1] for member in members)
        candidates[state] = content
        passages[state] = content[:start], content[start:end], content[end:]
    if passages["accepted"][1] == passages["rejected"][1]:
        raise ReviewError(
            "The removed revision changes formatting; its decision needs explicit reconciliation"
        )
    for width in (96, 48, 24, 12, 8):
        matches = []
        for state, (left, selected, right) in passages.items():
            sample = left[-width:] + selected + right[:width]
            pattern = "".join(
                r"\s+" if part.isspace() else re.escape(part)
                for part in re.findall(r"\s+|\S+", sample)
            )
            if sample and len(list(re.finditer(pattern, incoming))) == 1:
                matches.append(state)
        if len(matches) == 1:
            return matches[0]
    raise ReviewError(
        "The accept/reject decision cannot be distinguished from other changes at this passage"
    )


def _same_revision(before: WordRevision, after: WordRevision) -> bool:
    """Compare revision content while allowing Word's minute-precision dates."""
    if (before.story, before.kind, before.author, before.text) != (
        after.story,
        after.kind,
        after.author,
        after.text,
    ):
        return False
    if before.date == after.date:
        return True
    if before.date is None or after.date is None:
        return False
    try:
        original = datetime.fromisoformat(before.date)
        returned = datetime.fromisoformat(after.date)
    except ValueError:
        return False
    return original == returned or original.replace(second=0, microsecond=0) == returned


def receive(
    directory: Path,
    incoming: Path,
    *,
    export_id: str | None = None,
    author: str | None = None,
) -> dict:
    """Import one returned Word file, or retain a conflict report without partial edits."""
    manuscript = Project.read(directory)
    if manuscript.source is not None:
        raise ReviewError(
            "Single-source return review is explicit: import-docx into a new candidate "
            "directory, then compare with the version sent; receive does not modify this project"
        )
    directory = manuscript.directory
    package = WordPackage.read(incoming)
    identity = read_identity(package)
    identifier = export_id or identity.get("export")
    if not identifier:
        raise ReviewError(
            "This file has no retained export identity; provide --export with the exact export hash"
        )
    if export_id and identity.get("export") and export_id != identity["export"]:
        raise ReviewError(
            "The specified export differs from the identity retained in Word"
        )
    exported, export_directory = load_export(directory, identifier)
    digest = sha256(incoming.read_bytes()).hexdigest()
    stage = directory / "review/exchanges/returns" / digest
    receipt = stage / "receipt.json"
    if receipt.exists():
        previous = json.loads(receipt.read_text())
        if previous["status"] == "applied":
            return {**previous, "duplicate": True}
    stage.mkdir(parents=True, exist_ok=True)
    original = stage / "incoming.docx"
    if not original.exists():
        original.write_bytes(incoming.read_bytes())
    archive = str(original.relative_to(directory))
    baseline_package = WordPackage.read(export_directory / "document.docx")
    baseline, returned = read_review(baseline_package), read_review(package)
    source = exported["source"]
    if source not in manuscript.documents:
        raise ReviewError(f"Export source {source} is no longer registered")
    current = manuscript.documents[source]
    initial_bytes = {
        name: (directory / name).read_bytes()
        for name in [*manuscript.metadata.sources, "review.yml"]
    }
    metadata = ReviewMetadata.from_mapping(asdict(manuscript.metadata))
    decisions = {key: item.status for key, item in metadata.suggestions.items()}
    changes = []
    conflicts = [
        {**item, "source": source}
        for item in unsupported_changes(baseline_package, package)
    ]
    baseline_comments = {comment.id: comment for comment in baseline.comments}
    durable = {
        comment.durable_id: comment.id
        for comment in baseline.comments
        if comment.durable_id
    }
    source_ids = exported["identity"]["comments"]
    mapping = {}
    known_baseline = {}
    for comment in returned.comments:
        old_id = durable.get(comment.durable_id)
        if old_id is None and comment.id in baseline_comments:
            candidate = baseline_comments[comment.id]
            if (comment.durable_id is None or candidate.durable_id is None) and (
                comment.author,
                comment.date,
            ) == (candidate.author, candidate.date):
                old_id = comment.id
        if old_id is not None:
            mapping[comment.id] = source_ids[old_id]
            known_baseline[comment.id] = baseline_comments[old_id]
        else:
            # A later return may contain a comment already imported from this export.
            prior = next(
                (
                    key
                    for key, item in metadata.comments.items()
                    if item.provenance.get("export") == identifier
                    and item.provenance.get("durable_id") == comment.durable_id
                    and comment.durable_id
                ),
                None,
            )
            prior_reply = next(
                (
                    reply.id
                    for item in metadata.comments.values()
                    for reply in item.replies
                    if reply.provenance.get("export") == identifier
                    and reply.provenance.get("durable_id") == comment.durable_id
                    and comment.durable_id
                ),
                None,
            )
            mapping[comment.id] = (
                prior or prior_reply or f"c{digest[:16]}_{comment.id.replace('-', 'n')}"
            )
    comment_updates = {}
    existing_anchors = []
    patches = []
    annotations = current.annotations()

    def conflict(kind: str, item: str, reason: str) -> None:
        conflicts.append({"kind": kind, "id": item, "reason": reason, "source": source})

    returned_comments = {comment.id: comment for comment in returned.comments}

    def thread_depth(comment) -> int:
        parents = set()
        while comment.parent_id in returned_comments:
            if comment.parent_id in parents:
                raise ReviewError(
                    "The returned comments contain a circular reply relationship"
                )
            parents.add(comment.parent_id)
            comment = returned_comments[comment.parent_id]
        return len(parents)

    for comment in sorted(returned.comments, key=thread_depth):
        local_id = mapping[comment.id]
        before = known_baseline.get(comment.id)
        provenance = {"source": archive, "export": identifier, "word_id": comment.id}
        for key in ("durable_id", "paragraph_id", "initials", "date_utc"):
            value = getattr(comment, key)
            if value is not None:
                provenance[key] = value
        if comment.parent_id is not None:
            if comment.parent_id not in mapping:
                conflict(
                    "reply", local_id, "The returned reply has an unavailable parent"
                )
                continue
            parent = mapping[comment.parent_id]
            root = next(
                (
                    key
                    for key, item in metadata.comments.items()
                    if key == parent
                    or any(reply.id == parent for reply in item.replies)
                ),
                None,
            )
            if root is None:
                conflict("reply", local_id, "The parent thread could not be imported")
                continue
            thread = metadata.comments[root]
            prior = next(
                (reply for reply in thread.replies if reply.id == local_id), None
            )
            reply = Reply(
                local_id,
                comment.text,
                comment.author,
                comment.date,
                parent,
                provenance,
                resolved=comment.resolved,
            )
            if prior is None:
                metadata.comments[root] = replace(
                    thread, replies=(*thread.replies, reply)
                )
                changes.append({"kind": "reply", "id": local_id, "thread": root})
            elif comment.text != prior.body:
                if before is not None and comment.text == before.text:
                    pass  # The local edit is independent of the returned feedback.
                elif before is None or prior.body != before.text:
                    conflict(
                        "reply",
                        local_id,
                        "The reply was edited both locally and in Word",
                    )
                else:
                    metadata.comments[root] = replace(
                        thread,
                        replies=tuple(
                            reply if item.id == local_id else item
                            for item in thread.replies
                        ),
                    )
                    changes.append({"kind": "reply-edit", "id": local_id})
            if (
                prior is not None
                and before is not None
                and comment.resolved != before.resolved
            ):
                thread = metadata.comments[root]
                metadata.comments[root] = replace(
                    thread,
                    replies=tuple(
                        replace(item, resolved=comment.resolved)
                        if item.id == local_id
                        else item
                        for item in thread.replies
                    ),
                )
                changes.append(
                    {
                        "kind": "reply-status",
                        "id": local_id,
                        "resolved": comment.resolved,
                    }
                )
            continue
        if local_id in metadata.comments:
            local = annotations.get(local_id)
            if not isinstance(local, Comment):
                conflict(
                    "comment", local_id, "The original comment has no source anchor"
                )
                continue
            thread = metadata.comments[local_id]
            remote_status = "resolved" if comment.resolved else "open"
            old_status = ("resolved" if before.resolved else "open") if before else None
            if comment.text != local.body:
                if before is not None and comment.text == before.text:
                    pass
                elif before is None or local.body != before.text:
                    conflict(
                        "comment",
                        local_id,
                        "The initial comment was edited both locally and in Word",
                    )
                else:
                    comment_updates[local_id] = replace(local, body=comment.text)
                    changes.append({"kind": "comment-edit", "id": local_id})
            if old_status is not None and remote_status != old_status:
                if thread.status not in {old_status, remote_status}:
                    conflict(
                        "status",
                        local_id,
                        "The comment status changed both locally and in Word",
                    )
                else:
                    thread = replace(thread, status=remote_status)
                    changes.append(
                        {"kind": "status", "id": local_id, "status": remote_status}
                    )
            if before:
                existing_anchors.append((comment.id, before.id, local_id))
            metadata.comments[local_id] = replace(thread, provenance=provenance)
        else:
            try:
                if len(comment.anchors) != 1 or not comment.anchors[0].text:
                    raise ReviewError(
                        "A new point or multi-range comment needs an explicit source anchor"
                    )
                anchor = comment.anchors[0]
                story = returned.stories[anchor.story]
                start, end = locate(
                    current,
                    decisions,
                    anchor.text,
                    left=story[: anchor.start],
                    right=story[anchor.end :],
                    allow_ranges=True,
                )
                opening = f'[]{{.review-start data-review="{local_id}"}}'
                closing = f'[]{{.review-end data-review="{local_id}"}}{{>>{escape_comment(comment.text)}<<}}{{#{local_id}}}'
                patches.extend([(start, start, opening), (end, end, closing)])
                metadata.comments[local_id] = CommentMetadata(
                    comment.author,
                    comment.date,
                    "resolved" if comment.resolved else "open",
                    provenance=provenance,
                )
                changes.append({"kind": "comment", "id": local_id, "text": anchor.text})
            except ReviewError as error:
                conflict("anchor", local_id, str(error))
    returned_known = {source_ids[item.id] for item in known_baseline.values()}
    for native_id, local_id in source_ids.items():
        if local_id not in returned_known:
            conflict(
                "missing-comment",
                local_id,
                "The exported comment or reply was removed in Word; deletion is not treated as resolution",
            )

    # Native suggestions are read separately from comment bodies. The complete
    # imported source remains available even when a source anchor is ambiguous.
    remote_document, remote_metadata = _read_source(
        package, metadata.author, archive, directory
    )
    write_text(stage / "returned.qmd", remote_document.source)
    remote_metadata.write(stage / "returned-review.yml")
    native_map = {
        (item["story"], item["word_id"]): item
        for item in exported["identity"]["revisions"]
    }
    baseline_revisions = {(item.story, item.id): item for item in baseline.revisions}
    pending = {}
    present = set()
    for local_id, item in remote_metadata.suggestions.items():
        key = item.provenance.get("story"), item.provenance.get("word_id")
        old = baseline_revisions.get(key)
        native = next(
            (
                revision
                for revision in returned.revisions
                if (revision.story, revision.id) == key
            ),
            None,
        )
        alternatives = [
            (candidate_key, candidate)
            for candidate_key, candidate in baseline_revisions.items()
            if candidate_key not in present
            and native is not None
            and _same_revision(candidate, native)
        ]
        if len(alternatives) > 1:
            located = [
                (candidate_key, candidate)
                for candidate_key, candidate in alternatives
                if (candidate.start, candidate.end) == (native.start, native.end)
            ]
            if len(located) == 1:
                alternatives = located
        if len(alternatives) > 1:
            conflict(
                "suggestion",
                local_id,
                "Several exported revisions match this returned revision; confirm its source identity",
            )
            continue
        if alternatives:
            key, old = alternatives[0]
            present.add(key)
        elif old is not None and native is not None and key not in present:
            present.add(key)
            conflict(
                "suggestion",
                native_map[key]["id"],
                "An exported native revision was rewritten in Word",
            )
        else:
            pending[local_id] = item
    missing = set(baseline_revisions) - present
    remote_decisions = {
        key: "rejected" if key in pending else "accepted"
        for key in remote_metadata.suggestions
    }
    remote_text, _, remote_locations = projection(remote_document, remote_decisions)
    for remote_id, item in pending.items():
        node = remote_document.annotations().get(remote_id)
        try:
            if not isinstance(node, Change) or not node.before and not node.after:
                raise ReviewError(
                    "This native formatting or equation revision needs an explicit source decision"
                )
            before, after = (
                project_text(node.before, "original"),
                project_text(node.after),
            )
            previously_imported = [
                key
                for key, known in metadata.suggestions.items()
                if known.provenance.get("export") == identifier
                and known.provenance.get("word_id") == item.provenance.get("word_id")
                and known.provenance.get("story") == item.provenance.get("story")
                and known.author == item.author
                and known.date == item.date
            ]
            if len(previously_imported) == 1:
                prior_id = previously_imported[0]
                prior_node = current.annotations().get(prior_id)
                if isinstance(prior_node, Change) and (
                    project_text(prior_node.before, "original"),
                    project_text(prior_node.after),
                ) == (before, after):
                    continue
                raise ReviewError(
                    f"Previously imported suggestion {prior_id} changed again; reconcile its previous returned version"
                )
            first, last = remote_locations[remote_id]
            start, end = locate(
                current,
                decisions,
                before,
                left=remote_text[:first],
                right=remote_text[last:],
            )
            local_id = f"s{digest[:16]}_{remote_id}"
            markup = "{~~" + before + "~>" + after + "~~}{#" + local_id + "}"
            patches.append((start, end, markup))
            metadata.suggestions[local_id] = replace(
                item, provenance={**item.provenance, "export": identifier}
            )
            changes.append(
                {
                    "kind": "suggestion",
                    "id": local_id,
                    "before": before,
                    "after": after,
                    "author": item.author,
                }
            )
        except ReviewError as error:
            conflict("suggestion", remote_id, str(error))
    base_document, base_metadata = _read_source(
        baseline_package,
        metadata.author,
        str((export_directory / "document.docx").relative_to(directory)),
        directory,
    )
    base_decisions = {}
    source_review = parse(exported["render"]["authored_review_source"], source)
    authored_metadata = ReviewMetadata.from_mapping(
        exported["render"]["authored_metadata"]
    )
    base_ids = {
        (item.provenance.get("story"), item.provenance.get("word_id")): key
        for key, item in base_metadata.suggestions.items()
    }
    groups = {}
    for key, native in native_map.items():
        groups.setdefault(native["id"], set()).add(key)
    for native_id, group in groups.items():
        absent = group & missing
        if not absent:
            continue
        try:
            if absent != group:
                raise ReviewError(
                    "Only part of the exported suggestion was accepted or rejected; reconcile its grouping"
                )
            state = _infer_decision(
                base_document,
                [base_ids[key] for key in group],
                remote_text,
                base_decisions,
            )
            local_id = native_id
            node = source_review.annotations().get(local_id)
            if not isinstance(node, Change):
                raise ReviewError(
                    "This rendered suggestion does not have an unambiguous authored source identity"
                )
            if local_id not in metadata.suggestions:
                before, after = (
                    project_text(node.before, "original"),
                    project_text(node.after),
                )
                authored_text, _, authored_locations = projection(source_review, {})
                first, last = authored_locations[local_id]
                start, end = locate(
                    current,
                    decisions,
                    after,
                    left=authored_text[:first],
                    right=authored_text[last:],
                )
                patches.append((start, end, serialize((node,))))
                metadata.suggestions[local_id] = authored_metadata.suggestions[local_id]
            prior = metadata.suggestions[local_id]
            if prior.status not in {"pending", state}:
                raise ReviewError(
                    "The local decision conflicts with the returned Word decision"
                )
            selected = node.after if state == "accepted" else node.before
            metadata.suggestions[local_id] = replace(
                prior,
                status=state,
                provenance={
                    **prior.provenance,
                    "decided_text_hash": sha256(
                        project_text(selected).encode()
                    ).hexdigest(),
                },
            )
            base_decisions.update(
                dict.fromkeys((base_ids[key] for key in group), state)
            )
            changes.append({"kind": "decision", "id": local_id, "status": state})
        except ReviewError as error:
            conflict("decision", native_id, str(error))
    base_text, _, base_locations = projection(base_document, base_decisions)
    for incoming_id, before_id, local_id in existing_anchors:
        remote_range = remote_locations.get(f"c{incoming_id.replace('-', 'n')}")
        before_range = base_locations.get(f"c{before_id.replace('-', 'n')}")
        if remote_range != before_range:
            conflict(
                "anchor",
                local_id,
                "The existing comment range changed in Word; confirm its source range",
            )
    if remote_text.strip() != base_text.strip() and not any(
        item["kind"] == "decision" for item in conflicts
    ):
        if not author:
            conflict(
                "untracked-content",
                source,
                "The returned text or formatting changed outside native revisions; provide --author to attribute reconstructed suggestions",
            )
        else:
            for number, (old_start, old_end, new_start, new_end) in enumerate(
                _edits(base_text, remote_text), 1
            ):
                try:
                    before, after = (
                        base_text[old_start:old_end],
                        remote_text[new_start:new_end],
                    )
                    start, end = locate(
                        current,
                        decisions,
                        before,
                        left=base_text[:old_start],
                        right=base_text[old_end:],
                    )
                    local_id = f"u{digest[:16]}_{number}"
                    patches.append(
                        (
                            start,
                            end,
                            "{~~" + before + "~>" + after + "~~}{#" + local_id + "}",
                        )
                    )
                    metadata.suggestions[local_id] = SuggestionMetadata(
                        author,
                        None,
                        provenance={
                            "source": archive,
                            "export": identifier,
                            "untracked": "true",
                            "imported_at": timestamp(),
                        },
                    )
                    changes.append(
                        {
                            "kind": "untracked-suggestion",
                            "id": local_id,
                            "before": before,
                            "after": after,
                            "author": author,
                        }
                    )
                except ReviewError as error:
                    conflict("untracked-content", source, str(error))
    for first, second in zip(sorted(patches), sorted(patches)[1:]):
        if first[1] > second[0]:
            conflict("overlap", source, "Returned edits overlap in the current source")
    result = {
        "version": 1,
        "status": "conflicts" if conflicts else "applied",
        "export": identifier,
        "return": digest,
        "changes": changes,
        "conflicts": conflicts,
        "archive": str(stage.relative_to(directory)),
    }
    if not conflicts:
        revised = current.source
        for start, end, replacement in sorted(patches, reverse=True):
            revised = revised[:start] + replacement + revised[end:]
        document = parse(revised, source)
        if comment_updates:
            document = _rewrite(document, comment_updates)
        documents = {**manuscript.documents, source: document}
        metadata.imports[digest] = archive
        metadata.validate(documents)
        for name, content in initial_bytes.items():
            if (directory / name).read_bytes() != content:
                raise ReviewError(
                    f"{name} changed during return reconciliation; no source changes were applied"
                )
        # Keep the pre-import working state alongside the return for inspection.
        for name, content in initial_bytes.items():
            path = stage / "before" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        write_text(directory / source, document.source)
        metadata.write(directory / "review.yml")
    write_text(receipt, json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return result
