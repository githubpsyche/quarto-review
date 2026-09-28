# Single-source review format

Schema 2 stores one complete, editable review document in index.qmd.
Its frozen counterpart defaults to reference.qmd.
Set review.reference to another relative QMD path if required; it must stay inside the project and cannot be the working source.

## Authors and attribution

The review.authors mapping defines stable aliases for display names.
The review.author alias selects the current author for newly created review items.
Every saved message and suggestion has its own by attribute.
Changing the current author therefore does not reattribute previous feedback.
Imported unattributed messages can retain an alias mapped to null; the current author must be named.

The optional at attribute preserves a timestamp exactly.
Reading or rendering an undated message does not invent a date.
Commands timestamp new messages once.
Known dates, precision and time-zone offsets survive conversion.

## Comments and ranges

The common case uses an ordinary bracketed span:

~~~markdown
A [claim needing clarification]{#c1}.
~~~

The definition of c1 is a fenced div, located anywhere at a valid block boundary in the same file:

~~~markdown
:::: {.review-thread #c1 by=R}
Explain the evidence.

::: {.reply #r1 by=A}
I have added the result.
:::
::::
~~~

Discussion bodies use basic CommonMark: paragraphs, emphasis, links, lists, blockquotes and code render as formatting in the HTML panel and margin cards.
Each message is parsed independently, so link definitions and unclosed code fences cannot affect another message.
Manuscript-specific filters, citations, executable code and Quarto shortcodes do not run inside discussions.
Raw HTML is displayed literally, unsafe link schemes are removed, and Markdown images show their alternative text without loading an image.
The manuscript itself follows Quarto's normal Markdown rendering.

An optional format=plain attribute on a thread or reply preserves literal punctuation and line breaks.
Conversion from legacy sources and Word imports writes this attribute without changing the stored body.
Older schema-2 messages carrying a native Word identity also default to plain text unless format=markdown explicitly opts in.
New schema-2 messages and replies default to Markdown, including replies to imported plain comments.
The format belongs to each message, so replying, resolving and reopening do not reinterpret earlier feedback.

This formatting change applies to HTML display.
Word export retains the stored body text, including Markdown punctuation in authored messages; it does not yet translate that markup into Word character or paragraph formatting.

A reply defaults to the initial message as its parent.
Use to=r1 when replying to another reply.
Messages remain inside their root thread; separate replies must have unique IDs.
Fences containing nested div examples should be longer than the fences inside those examples.

For overlapping ranges, use explicit boundaries:

~~~markdown
A []{#c1-start}modest []{#c2-start}difference[]{#c1-end} between conditions[]{#c2-end}.
~~~

These boundaries refer to c1 and c2; they contain no discussion state.
A point comment uses adjacent start/end markers.
Further disjoint ranges for the same thread use numbered pairs, such as c1-2-start and c1-2-end.
An imported reply with its own anchor uses the same notation with the reply's ID.
Boundary IDs with these suffixes are reserved by this format.
Ranges must be paired; crossing different comments is allowed, while overlapping ranges of the same comment are rejected.

Removing a thread definition alone while leaving its markers is an error.
The delete-comment command removes the definition, its replies and their markers in one validated source update.
It preserves the selected text and other annotations.
Deleted discussions remain absent from subsequent outputs, even when they exist in the frozen reference.

## Suggestions and decisions

Empty navigation anchors such as `[]{#ref-example .anchor}` are document structure, so adding, removing or renaming them does not create an automatic wording suggestion.
The current anchor is retained in the output; nearby wording edits are still tracked.
Anchor syntax shown literally in code and changes to visible links remain tracked.


~~~markdown
The difference was {~~large~>modest~~}{#s1 by=R}.
The replication was {++independent ++}{#s2 by=A}.
~~~

Pending is implicit.
Add .accepted or .rejected to a suggestion's attributes to record its disposition.
Removing either class returns it to pending.
Both wording alternatives remain available.
HTML shows accepted wording as ordinary manuscript text and omits rejected wording.
To inspect the retained decision, choose Changes under Review, then Accepted or Rejected under Status.
Cards show the original and proposed text, author and status beside the passage.
Accepted deletions and rejected insertions have a Δ location marker even when no text remains there.
Previous and Next visit matching changes in manuscript order, starting from the selected item or current passage.
Changing a filter keeps the reader at the current passage; it does not jump to the first match.
When changes are nested, the outer card applies the inner decisions while each inner card retains its own alternatives.
Native formatting and equation revisions with no separate text alternatives are identified as native Word changes and linked to their passage.

The panel beside the passage has Previous, Next and Hide buttons above its review cards.
Its List view shows every item matching the author, review-type and status filters, interleaved in manuscript order.
The Review list toolbar button opens this view even when At passage uses inline cards on a narrow screen.
Entries show nearby manuscript text, attribution and status; expanding an entry reveals its full discussion or change alternatives without scrolling the document.
Previous and Next move within the list while this view is active.
Go to passage switches to At passage and navigates to the anchor.
Returning to List restores expanded entries and its independent scroll position.
Hiding the review cards or entering Reading view hides the list as well.
Review defaults to Comments and changes; Status defaults to Open comments + pending changes.
The count includes only the selected review types and counts matches across the document, not just cards currently visible beside the text.
Status options depend on Review: Open, Resolved or All statuses for comments; Pending, Accepted or rejected, Accepted, Rejected or All statuses for changes.
With both types selected, Status offers Open comments + pending changes, Resolved comments + decided changes, and All statuses.
Switching review type translates Open to Pending and Resolved to Accepted or rejected, or their combined equivalents.
Accepted and Rejected broaden to the corresponding resolved or decided filter when changing type; switching back to Changes retains both decisions.
All statuses remains selected across types.
Pending changes can still appear when their associated comments are resolved.
Combined options are display filters, not new source statuses.
An incompatible status selection resets to All statuses when the review type changes.
In Redline, choosing an author highlights only that author's pending changes.
Other authors' pending insertions appear as ordinary proposed text and their deletions are hidden.
Accepted and rejected decisions remain in force; filtering never changes them.
Selecting All authors restores the complete redline.
Original and Proposed always show the whole document in their selected reading, regardless of the author filter.
Review and Status select cards and location markers without changing this text projection.
The explanation below the controls identifies the active author and text view.
When a comment spans changes, its excerpt compares the selected author's before and after readings against everyone else's proposed wording.
Nested edits respect the surrounding edit: a change within another author's deleted passage remains inspectable in its card without restoring that passage.
Hover over changed text or its Δ marker to see who suggested it, together with the change identifier and status.
Overlapping changes retain each author in the tooltip, independently of the card filters.
Comment excerpts show separate Original and Proposed readings in Redline view when they differ.
Original and Proposed views quote only their corresponding reading; an empty reading is identified explicitly.
These are display controls, not commands to accept or resolve anything.
Hide controls and Hide review cards change only panel visibility, preserving the selected text view even when both panels are hidden.
Reading view explicitly hides both panels and attribution tooltips and displays clean proposed text.
Show review restores the panels and the previously selected text view.

Comments are open by default.
Add .resolved to the thread div to resolve it; removing that class reopens it.
Imported replies can have a resolved=true or resolved=false override when Word stores a distinct state.
Explicitly resolving or reopening a thread normalizes all replies and removes redundant overrides.
Replying does not implicitly reopen a resolved thread.

A recorded decision must be reopened before its selected wording is rewritten within the same round.
Once a new reference includes that decision, further edits to its selected wording are ordinary changes in the new round.
Ordinary prose edits are compared with the frozen reference.
Discussion edits and attribution/state changes are excluded from that prose comparison.
An automatically detected edit can be made explicit when a command accepts or rejects it.

## Native information

Some imported Word information has no concise prose notation.
An adjacent, nonrendered review-data HTML comment retains those records with their owning annotation.
On messages it immediately follows the opening div line.
On suggestions it immediately follows the attributes.
The JSON payload stores provenance or, for native objects, the object's descriptor and its revision records.
The converter retains imported identities, dates, per-reply states and native relationships.

This technical information is not a separate editable database.
It must not be removed simply to shorten a file.
Original Word packages can remain immutable dependencies for native equations, formatting revisions or comment relationships.
Unsupported constructs fail with a diagnostic rather than being silently flattened.

## References and generated material

Capturing a reference freezes the complete QMD, not a separate collection of current comment metadata.
The extension never updates it during ordinary rendering.
A new round preserves the previous reference under review/rounds before replacing it.

When executed input has been captured, the frozen QMD carries format-specific Markdown under review.compiled.
This preserves the output needed for comparison without introducing a second active review file.
The working QMD remains readable source; the compiled data belongs only to the frozen snapshot.

Temporary parse caches, execution records and Word finishing plans are generated data.
They do not supersede the QMD.
Schema-2 Word export does not require an exchange journal.

## Compatibility and boundaries

The legacy QMD/review.yml format remains readable and writable through its existing operations.
A project containing both a schema-2 index.qmd and review.yml is rejected because ownership would be ambiguous.
Use migrate to produce separate verified candidates instead of changing a project's schema in place.

The current single-source project entry point is index.qmd.
One file contains its review definitions; definitions in other files are not implicitly searched.
Review annotations in YAML title or abstract values are unsupported.
Keep reviewable passages in body source, with presentation filters handling placement where necessary.

The extension's existing native Word limitations still apply; see status.md.
Returned Word files can be imported into candidates, but automatic divergent-history merging is not part of schema 2.
There is no automatic live migration or runtime installation into other projects.
