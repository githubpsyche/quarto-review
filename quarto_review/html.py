"""Build a read-only review panel with safely formatted, attributed threads."""

from __future__ import annotations

from html import escape

from quarto_review.discussion import render_messages
from quarto_review.rendering import PreparedRender


def review_panel(prepared: PreparedRender) -> str:
    """Present source-owned bodies and metadata-owned replies in one view."""
    messages = {}
    for identifier, item in prepared.metadata.comments.items():
        messages[identifier] = prepared.comments[identifier], item.body_format
        for reply in item.replies:
            messages[reply.id] = reply.body, reply.body_format
    for identifier, (before, after) in prepared.suggestions.items():
        for side, text in (("before", before), ("after", after)):
            if text:
                messages[f"change:{identifier}:{side}"] = text, "markdown"
    bodies = render_messages(messages)
    authors = sorted(
        {item.author for item in prepared.metadata.comments.values() if item.author}
        | {
            item.author
            for item in prepared.metadata.suggestions.values()
            if item.author
        }
        | {
            reply.author
            for item in prepared.metadata.comments.values()
            for reply in item.replies
            if reply.author
        }
    )
    options = '<option value="">All authors</option>' + "".join(
        f"<option>{escape(author)}</option>" for author in authors
    )
    pieces = [
        '<section id="quarto-review" class="qr-panel" aria-label="Manuscript review">',
        '<nav class="qr-controls" aria-label="Review controls">',
        '<label>Text view <select id="qr-view"><option value="review">Redline</option><option value="proposed">Proposed</option><option value="original">Original</option></select></label>',
        f'<label>Author <select id="qr-author">{options}</select></label>',
        '<label>Review <select id="qr-kind"><option value="">Comments and changes</option><option value="comment">Comments</option><option value="suggestion">Changes</option></select></label>',
        '<label>Status <select id="qr-status"><option value="open-pending">Open comments + pending changes</option><option value="resolved-decided">Resolved comments + decided changes</option><option value="">All statuses</option></select></label>',
        '<button type="button" id="qr-previous">Previous</button><button type="button" id="qr-next">Next</button>',
        '<span id="qr-count" role="status"></span></nav>',
        "<h2>Review comments</h2><p>Replies and decisions are made in the manuscript source or through the review commands.</p>",
    ]
    for identifier, item in prepared.metadata.comments.items():
        participants = "\n".join(
            sorted(
                {
                    value
                    for value in [
                        item.author,
                        *[reply.author for reply in item.replies],
                    ]
                    if value
                }
            )
        )
        pieces.append(
            f'<article class="qr-thread" id="qr-thread-{escape(identifier, quote=True)}" data-review-id="{escape(identifier, quote=True)}" data-kind="comment" data-author="{escape(participants, quote=True)}" data-status="{item.status}">'
        )
        pieces.append(
            f'<header><a href="#qr-anchor-{escape(identifier, quote=True)}" data-qr-target="{escape(identifier, quote=True)}">{escape(identifier)}</a> · {escape(item.author or "Unattributed")} · <span class="qr-status">{item.status}</span></header>'
        )
        if item.date:
            pieces.append(f"<time>{escape(item.date)}</time>")
        pieces.append(bodies[identifier])
        for reply in item.replies:
            pieces.append(
                f'<div class="qr-reply" id="qr-reply-{escape(reply.id, quote=True)}" data-parent="{escape(reply.parent_id, quote=True)}"><header>{escape(reply.author or "Unattributed")} · {escape(reply.id)}</header>'
            )
            if reply.date:
                pieces.append(f"<time>{escape(reply.date)}</time>")
            pieces.append(bodies[reply.id] + "</div>")
        pieces.append("</article>")
    pieces.append("<h2>Suggested edits</h2>")
    anchors = {
        member: identifier
        for identifier, item in prepared.metadata.objects.items()
        for member in item.revisions
    }
    for identifier, item in prepared.metadata.suggestions.items():
        anchor = anchors.get(identifier, identifier)
        before, after = prepared.suggestions.get(identifier, ("", ""))
        if before or after:
            kind = "replacement" if before and after else "deletion" if before else "insertion"
        else:
            kind = "native Word change"
        title = f"{item.status.capitalize()} {kind}"
        pieces.append(
            f'<article class="qr-suggestion" id="qr-suggestion-{escape(identifier, quote=True)}" data-kind="suggestion" data-review-id="{escape(identifier, quote=True)}" data-anchor-id="{escape(anchor, quote=True)}" data-author="{escape(item.author or "", quote=True)}" data-status="{item.status}">'
        )
        pieces.append(
            f'<header><a href="#qr-anchor-{escape(anchor, quote=True)}" data-qr-target="{escape(identifier, quote=True)}">{escape(title)}</a> · {escape(item.author or "Unattributed")}</header>'
        )
        pieces.append(f'<p class="qr-change-id">{escape(identifier)}</p>')
        if item.date:
            pieces.append(f'<time datetime="{escape(item.date, quote=True)}">Suggested {escape(item.date)}</time>')
        for side, label, text in (("before", "Removed", before), ("after", "Added", after)):
            if text:
                pieces.append(
                    f'<section class="qr-change-{side}"><h3>{label}</h3>'
                    + bodies[f"change:{identifier}:{side}"]
                    + "</section>"
                )
        if not before and not after:
            pieces.append('<p class="qr-native-change">A formatting, equation or other native Word revision. Inspect its anchored passage; this record has no separate text alternatives.</p>')
        pieces.append("</article>")
    pieces.append("</section>")
    return "\n".join(pieces)
