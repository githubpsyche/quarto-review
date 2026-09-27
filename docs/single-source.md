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

~~~markdown
The difference was {~~large~>modest~~}{#s1 by=R}.
The replication was {++independent ++}{#s2 by=A}.
~~~

Pending is implicit.
Add .accepted or .rejected to a suggestion's attributes to record its disposition.
Removing either class returns it to pending.
Both wording alternatives remain available.

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
