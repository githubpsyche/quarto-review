# Compatibility and implementation status

## Schema 2: current evidence

The single-source format is implemented with compact spans, crossing ranges, author aliases, Markdown thread blocks and inline suggestion decisions.
Tests cover source-only operations, deletion without removing prose, concurrent-write rejection, comment movement without prose changes, loss-checked candidate conversion, native Word import, HTML/Word output and executed references.
The full non-private regression suite also exercises the existing converter and schema-1 compatibility.
The checked version is 0.3.2; package, Python module and Quarto extension version declarations agree.
Focused checks also verify that opting an imported message into Markdown survives later review operations.
The reproducible checks and recorded results are in [release checks](release.md).
The 0.3.0 schema-2 application cycle with citations and cleanup passed in Word for Mac 16.113.3 on 30 September 2026: accept a prose replacement, reject both fragments of an added citation, reply to and resolve two threads, save, import into a separate candidate, explicitly reconcile while retaining a newer local edit, compact settled prose, export, reopen, save and import again.
This validates the documented explicit workflow on that Word version; it does not establish automatic schema-2 reconciliation or every Word feature.

| Current schema-2 capability | Evidence and boundary |
| --- | --- |
| Source operations and comparison | Automated tests cover text, ranges, decisions, attribution and unchanged references. Saving detects earlier changes but does not lock simultaneous writers. |
| HTML review | Automated synthetic browser checks cover filters, matching state transitions, lists, navigation, author focus, media, keyboard access and reading-view restoration. |
| Word import and export | Automated package, relationship, identity and content checks, plus a completed synthetic Word for Mac 16.113.3 cycle with citations and cleanup. |
| Returned feedback | Scripted and native Word returns both checked through separate candidate import and explicit reconciliation retaining newer local edits. No automatic schema-2 receive/merge. |
| Installed package | A disposable wheel installation renders HTML and Word, including citation targets and cleanup; the check rejects accidental imports from the development checkout. |
| Platform coverage | Development checks on macOS and the automated release checks on Ubuntu passed. Windows and R execution are not established by these checks. |

HTML discussions render basic CommonMark in a single conversion batch.
Regression tests cover formatting, isolated message parsing, literal Word imports, reply and decision preservation, raw HTML, unsafe links and image suppression.
Word discussion bodies still export their stored text rather than translating Markdown into native formatting.
The single-source entry point is index.qmd.
Returned feedback is imported into an explicit candidate; automatic receive is retained only for schema 1.

## Historical schema-1 and native exporter evidence

The implementation supports a basic review cycle: source setup, a fixed
reference, explicit and ordinary edits, HTML review, native Word export, and
reconciliation of a returned Word file. A complete native review cycle passed in
Word for Mac 16.113.2 on 27 September 2026: open, add a reply, resolve a thread,
accept and reject replacements, save, import, render, reopen, and save again.
This check does not establish compatibility with every Word version.

## Historical schema-1 behaviour

The following table and application findings document the older source format and native exporter.
They do not establish automatic return reconciliation for schema 2.

| Area | Evidence |
| --- | --- |
| Source and metadata | CriticMarkup parsing, whitespace, Unicode, code literals, identities, initial bodies in QMD, replies and states in YAML |
| Fixed reference | Frozen QMD/YAML, configuration, bibliography, assets, executed Markdown, additional data inputs, and archived rounds |
| Ordinary edits | Paragraph and word comparison, explicit grouping, no double counting, command-line decisions, and new edits after a decided reference |
| Native Word comments | Initial bodies, original authors/dates, ordered replies, resolution states, crossing ranges, point anchors, and comments on discarded wording |
| Native revisions | Insertions/deletions, paragraph replacements, preserved imported properties and equations, complete decisions, and mixed equation decisions |
| Comment dependencies | Round trip with a hyperlink, custom paragraph style, and numbered list; relationship targets and content types retained |
| Quarto integration | Normal renders, live project/file preview, existing APA Word format, project-selected APA HTML and Darkly HTML, native manuscript title/abstract layout with review ranges, actual Jupyter execution, citations, equations, tables, captions, cross-references, and footnotes |
| Other outputs | Clean PDF wording; HTML original/proposed/redline views, author/status filters, automatic margin comments, adjacent narrow-screen comments, sticky controls, independent visibility, clean reading and restoration, and comment navigation checked through the DOM |
| Returned files | Exact export identity, multiple independent reviewers, new threads/replies, original reviewer attribution, resolution, complete accept/reject decisions, renumbered native revisions, minute-precision timestamps, renamed export identity parts, concurrent local edits, duplicate detection, and conflicts |
| Package validation | Relationship graph and review invariants on every export, plus independent Open XML SDK validation during development |

An opt-in private fixture retains all 52 comment records, including five replies,
through Word → QMD → Word and a real Quarto render. Tests compare comment content,
authors, dates, identifiers, states, and anchored text. Imported revisions are
checked for content and attribution, not just XML counts. The fixture is an older
saved draft. A separate manuscript migration was also checked with 47 root threads,
four replies, and 285 original revision identities. Changing its HTML format left
the manuscript source, review metadata, and frozen reference byte-identical.
Its native manuscript HTML was also checked with all 506 source review boundaries
retained across the title block and article. Browser checks covered title and
abstract comments, sticky controls after scrolling, clean reading, restored controls,
and exclusion of copied TOC markers. A synthetic manuscript integration test checks
the native author/affiliation layout, front-matter ranges, replies, and source
preservation. Annotated source YAML remains unsupported; the imported passages
stay in body source and are moved into the title block only during rendering.

## Independent Word validation

Microsoft's Open XML SDK 3.3.0 was run with Microsoft 365 validation rules. The
synthetic APA output and the comment hyperlink/style/list round trip had zero
errors. The general Quarto structure fixture had seven property-order/duplicate
property errors; an ordinary Quarto render of the same content had the same seven
errors without this extension.

The original private file had 12 equation-schema errors and one incomplete
comment-extension element. Its reviewed Quarto output retained the same 12 native
equation errors and had one style-order error also present in ordinary Quarto
output. It introduced no new review-record validation errors in the checked
fixture. Existing native equation XML is retained rather than silently rewritten.

The final native-check export had one style-order error in Quarto's styles part;
after Word saved it, the independent validator reported zero errors. No comment,
reply, or tracked-change schema errors appeared in that check.

These findings are not a claim that all generated files have zero schema errors.
See [verification instructions](verification.md) for the independent validator and
the native Word check.

## Native Word findings

The application check caught issues that XML-only tests had missed. New replies
now receive their own document references, placed after existing replies. Without
those references, Word removed the replies on save. Existing imported ranges stay
intact. Exports use at least Word 2013 compatibility so thread resolution is
available, retaining newer compatibility modes and other document settings.

Word also renames custom XML parts, renumbers revisions, and rounds revision dates
to minutes. Return matching now handles these rewrites while preserving the
original source attribution and timestamp. Ambiguous revision matches and changed
attribution remain conflicts. An unchanged Word save imported with no changes;
the reviewed return imported both decisions, the new reply, and the resolved
thread. A repeated import added nothing, and the frozen reference stayed intact.

## Settled prose cleanup

Schema-2 projects can retire accepted and rejected prose suggestions with `compact`, preserving pending markup and comment discussions.
The comparison reference is updated in the same operation so decisions do not reappear as automatic changes.
Synthetic tests compare Word text, remaining native revision identities and attribution, comment anchors, replies and resolution before and after cleanup.
Native records still needed for formatting or equation export are retained and reported.
Captured executed references are currently unsupported by cleanup; an attempted cleanup stops before saving either file.
This feature does not migrate existing projects or update their installed runtimes automatically.

## Native citations in 0.3.0

Version 0.3.0 includes bibliography-assisted recovery of explicit author/year reference links during schema-2 Word import and a dry-run normalization command for existing schema-2 projects.
Normalization converts source and reference together, preserves unrelated edits and reports ambiguous or protected text.
HTML and Word fixture tests verify comment targets, replies, attribution, pending additions, ordinary narrative edits and unchanged citation formatting under author–date and numeric CSL styles.
Other tests cover reviewed source bibliographies, duplicated image-caption handling in HTML, safe nested review-card previews and refusal of ambiguous formatted ranges.

These changes are not deployed automatically into pinned manuscript runtimes.
Reference-manager fields and unlinked plain-text citations are not recovered.
Collapsed/reordered citation identities, repeated keys and annotations inside narrative components can require whole-group ranges.
See [native citations](citations.md) for the supported workflow and full limits.

## Comments default and Word return guide in 0.3.2

HTML review starts with Comments and status Open, while Changes and the combined view remain available. The default, filters, navigation and restoration passed all six synthetic browser groups; the focused HTML review suite passed 22 tests.
The public guide and editable download now introduce the complete explicit Word return workflow before the feature examples, including a reviewed wording decision, reply transfer and a retained newer local edit. The guide build checked HTML, Word review records and downloads.
The Word import and export implementation is unchanged from 0.3.1; its native Word evidence is retained rather than repeating the application cycle. Native application checks cover Word for Mac 16.113.3, not Windows or Word for the web.

## Citation revision grouping in 0.3.1

Complete citation links inside one contiguous prose insertion or deletion are exported together with their separators as one text revision. A focused Word for Mac 16.113.3 check on 30 September 2026 confirmed that a normal save retained the grouping and that a single current-change acceptance or rejection decided the whole addition. The citation link and adjacent comment were preserved; the pending, accepted and rejected documents were each independently imported.

Automated checks also cover deletions, author-date and numeric citations, replacements containing multiple links, attribution, replies, resolution, source identity and re-export. Partial links and links with additional attributes retain their existing structure. Version 0.3.1 adds this grouping to the citation and cleanup support checked for 0.3.0.

## Explicit limits

References below to returned-file conflict detection describe the schema-1 reconciliation engine.
Schema 2 imports a candidate; comparing it with the version sent and the latest working source remains an explicit user task.

- Review annotations in YAML metadata, including a YAML title or abstract, are
  not supported. Rendering reports omitted annotations rather than dropping them.
  Keep reviewable manuscript passages in the body.
- Native Word comments cannot be anchored inside footnote/endnote text, headers,
  or footers by this exporter. These cases stop export with a diagnostic. A
  comment about a footnote can explicitly anchor to its reference in the body;
  tracked text changes within footnotes are tested.
- Ordinary changes that cross existing annotation boundaries need explicit
  grouping. Returned ambiguous anchors, new point or multiple-range comments,
  partially accepted revision groups, and new native formatting or equation
  changes are retained as conflicts for a source decision.
- Changed drawings, images, embedded objects, headers, and footers in a returned
  file are reported for reconciliation with source assets or Quarto layout.
- Editing generated results in Word does not rewrite code or data. The return is
  retained for a specific source decision when it has no authored passage.
- Picture bullets in imported comments stop export. Comment hyperlinks, styles,
  and ordinary numbered lists are covered; mentions, assignments, and every
  possible embedded comment object are not verified.
- Removing a Word comment is not treated as resolving it. Deleted threads remain
  a conflict so their discussion cannot disappear unnoticed.
- Source files can be registered individually. Combined book outputs, arbitrary
  filter combinations, and all execution engines have not been verified. Quarto
  1.8.27 and actual Jupyter execution were tested on macOS; R execution was not.
- Live preview tests follow Quarto's browser reload messages. Quarto 1.8 project
  preview can reuse stale input when a client repeatedly requests a page during
  rendering. Prefer file preview for a single manuscript and let automatic reload
  finish. Review commands notify both modes; direct YAML editing in file preview
  requires symbolic links, which setup reports if unavailable. Rapid direct YAML
  saves in project preview remain subject to Quarto's second-resolution cache.
- Layout follows Quarto. Import does not promise to reproduce every layout,
  section setting, field, or font from the original Word file.

The source and archive are preserved when a case cannot be reconciled. A diagnostic
is a request to make a concrete source decision, not a claim that the conversion
completed successfully.


## Inspecting settled suggestions in HTML

Review cards now support comments and changes, selected separately in the Review control.
Accepted and rejected changes keep readable before/after text, authors and statuses in their cards while the manuscript retains its decided wording.
Empty change ranges have visible location markers when changes are selected.
Status filtering selects records without fading the manuscript's tracked-change colours.
In Redline, author filtering additionally shows only the selected author’s pending edits, with other authors’ edits projected as proposed wording.
This view preserves decisions, nested edits, figures and other media; Original and Proposed retain their full-document readings.
A synthetic author-focus fixture verifies these behaviours, focused comment excerpts, navigation and restoration on wide and narrow screens.
Nested decisions apply within the alternatives shown in a parent change card.
Filtering preserves the current reading position, including when earlier inline cards disappear.
Navigation follows the selected item or scrolled passage and is not reset by filters or stationary-pointer layout changes.
Hover attribution names the authors of overlapping changes independently of the card filters; Reading view hides these tooltips.
Comment excerpts distinguish original and proposed readings and identify empty alternatives.
On 28 September 2026, the public suite passed with 170 tests, 4 optional-runtime skips and 4 private tests deselected.
Synthetic browser checks passed at desktop and narrow widths for these behaviours, accepted section deletion, rejected insertion, empty results and clean reading/restoration.
Native formatting and equation revisions without separate text alternatives are described as native Word changes and linked to the corresponding passage.
Their detailed Word formatting is not reconstructed in a text card.
