# Native citations and review

This guide describes native citation support in version 0.3.0. See [release evidence](release.md) for automated checks and the completed Word for Mac cycle.

## The author’s workflow

Use ordinary Quarto citations such as `[@smith2020; @brown2021]` and `@smith2020` in the manuscript.
Keep reference data in the project’s normal bibliography file.
An imported author/year hyperlink can be converted when it explicitly identifies a key in that bibliography.
Comments and suggestions retain their existing identities.
Rendering uses the manuscript project’s bibliography, CSL style and locale.
The author does not run a command for each citation edit or maintain a second copy of citation display text.
A one-time normalization command can bring an older Word import into this format without accepting its pending suggestions.

## Starting from Word

~~~sh
quarto-review import-docx feedback.docx --into manuscript --author "Example Author" --bibliography references.bib
~~~

This imports into a new schema-2 project, copies the bibliography and configures its filename in index.qmd.
The original Word package is retained unchanged.
The import report lists converted links, retained cases and detected citation-manager fields.
A copy of that report lives at `.quarto/review/citation-import.json`; it is a diagnostic, not another authoritative review file.
Import does not infer bibliography records from formatted reference paragraphs.
Supply the bibliography separately and inspect retained cases before sharing an export.

## Converting an existing import

First declare the supplied bibliography through ordinary `bibliography:` metadata in index.qmd or _quarto.yml.
The command reads BibTeX/BibLaTeX, CSL JSON and CSL YAML files.

~~~sh
quarto-review normalize-citations --bibliography references.bib
quarto-review normalize-citations --bibliography references.bib --apply
~~~

The first command only reports proposed conversions and retained cases, including source lines.
The second changes index.qmd and its frozen reference consistently.
Unrelated working edits remain pending; suggestions, threads, replies and attribution retain their identities.
No suggestion is accepted as a side effect.
If saving the working source fails, the reference is restored.
As with other source operations, concurrent editing is detected but files are not locked; use one writer during the conversion.

For example, `([Smith, 2020](#ref-smith2020); [Brown, 2021](#ref-brown2021))` becomes `[@smith2020; @brown2021]`.
`[Smith (2020)](#ref-smith2020)` becomes `@smith2020`.
Narrative year groups and possessive author forms retain their narrative role, using suppress-author citations where needed.
Code, equations and discussion bodies are left alone.
An unknown member prevents partial conversion of its group.
Decided citation text is retained and reported; applying recovery stops before writing either file while such text remains.
Those retained records require separate reconciliation; normalization does not retire review history. Once their decisions are final, `quarto-review compact` can retire settled prose records from source and reference before normalization; review its dry run first.
This avoids converting only one side of the comparison after a decision.
References containing replacements across citation members are also retained for explicit reconciliation.

Recovery makes Quarto responsible for citation spelling and punctuation.
It does not promise pixel-identical output to previously handwritten citation labels: the selected bibliography, CSL and locale determine the result.
Review candidate output before adopting a conversion where exact presentation matters.
Captured executed references are not yet supported by this normalization command.

## Editing after conversion

After upgrading an installed runtime, run `quarto-review enable` in a candidate project to install both citation filters.
Existing projects do not receive development changes automatically.
Then edit QMD normally and render it normally:

~~~markdown
Earlier work [@smith2020; @brown2021] supports this account.
@smith2020 found a similar effect.
~~~

Changing a complete citation key or bracketed group is detected against the frozen reference as an ordinary pending edit.
There is no citation-specific command for each edit.
Explicit local suggestions and comment ranges can also surround citations.
A comment on a whole group uses `[[@smith2020; @brown2021]]{#c1}`.
For a comment on one member, use `[@smith2020; []{#c1-start}@brown2021[]{#c1-end}]` with the normal c1 thread definition.
Change a whole citation or group when a replacement would otherwise split a key or make the combined review syntax ambiguous.

## A reference list with existing review information

Generated bibliographies remain the default.
If imported source entries still contain review information, opt into preserving that source list:

~~~yaml
quarto-review:
  bibliography: source
~~~

Place the entries in exactly one explicit `::: {#refs}` block and retain their `ref-key` anchors.
The late citation filter formats in-text citations through citeproc, omits its generated bibliography and restores the reviewed source block in its original position.
This works for HTML and Word; entry wording and formatting remain owned by the QMD.
Do not combine this mode with `suppress-bibliography: true`, which removes the links needed to recover internal citation review ranges.
Changing BibTeX fields is not tracked as a proposed edit to a source-owned entry.
Moving reviewed entries to a generated bibliography remains a separate author decision.

## Supported boundaries and limits

Synthetic tests cover grouped author–date and numeric citations, narrative edits, possessive recovery, locators outside the reviewed span, same-author year grouping, comments within groups, a pending member addition, nested preview readings, HTML figure captions and native Word review export.
Review cards use the formatted passage, so the cards do not introduce extra citations or independently assign disambiguation suffixes.
Historical citation alternatives no longer present as pending manuscript ranges are explicitly labelled as source syntax.
Comment and reply bodies continue to use basic CommonMark; citations within discussions are not processed.

Word can split one citation suggestion into separate tracked fragments at hyperlink boundaries, such as the separator and added year. Accept or reject every fragment belonging to that suggestion before reconciling its QMD decision. The version 0.3.0 application check rejected both fragments and retained the adjacent member comment, reply and resolution.

For internal group ranges, citation links must remain available.
The installed late filter enables them when necessary; an explicit `link-citations: false` is incompatible and produces an error.
A CSL style that reorders or collapses the linked identities beyond an unambiguous contiguous mapping produces an error instead of silently moving a comment.
Anchor the whole group in those cases.
Repeated keys, annotations inside a narrative citation’s components, and boundaries within locator wording changed by CSL are not supported by member-level recovery.

The converter recovers explicit author/year reference links, not arbitrary plain citations, numerical labels or reference-manager fields.
Zotero, EndNote and native Word citation-field recovery need their own import adapters.
Those originals remain archived and detected fields are reported; their detection does not mean their citation identities were recovered.

## Separate responsibilities

The bibliography owns reference identities and bibliographic data.
Quarto and citeproc own citation wording, grouping, punctuation and disambiguation.
The QMD owns manuscript wording, suggested alternatives and review discussions.
The review extension owns the association between review records and the content being reviewed.
The frozen reference remains the comparison baseline, not a second editable manuscript.

Import/normalization and review rendering are different operations.
An import can recover a citation identity without deciding whether the collaborator’s addition should be accepted.
Normalization must transform the current source and comparison reference consistently and must preserve unrelated working edits.
It must not create accepted “technical changes.”

## Recovery policy

Use explicit citation identities or links matching a supplied bibliography.
Do not guess a reference from an author/year string: different papers can share that display text.
Unknown keys, partially recovered fields and ambiguous structures remain intact and appear in a location-specific report.
The original Word file stays preserved.
Structured Word fields need format-specific support; recovering an internal reference link is not equivalent to supporting every reference manager.

The first converter targets explicit `#ref-key` and `#ref_key` links.
It preserves narrative versus parenthetical use, citation groups and review records.
A dry run reports both conversions and retained cases before any source file changes.

## Rendered review cards

A pending suggestion’s citation preview must come from its formatted manuscript range.
Running citeproc independently over each card could change author disambiguation, numbering or year suffixes.
Adding card citations to the manuscript’s citation-processing input could instead change the manuscript bibliography.
Neither is acceptable.
The HTML finishing stage therefore copies the formatted range into the card, retaining safe inline formatting and removing duplicate IDs and active content.
Nested pending alternatives use the card’s original/proposed reading rather than concatenating both alternatives.
Historical alternatives no longer present in the rendered document use an explicitly labelled source-only fallback.

## Review boundaries within a citation group

Do not pass review markers to citeproc as citation prefixes or suffixes.
Experiments show that even zero-width spans can alter punctuation, sorting and author/year collapsing.

Instead, parse review boundaries into a temporary citation plan before formatting.
Strip those boundaries from the Cite node and retain its normal citation identities, prefixes, suffixes and mode.
A temporary enclosing span/bookmark connects the formatted group with that plan.
After citeproc, recover the reviewed range from the linked citation identities and restore the HTML boundaries or Word marker runs before native review finishing.
Temporary identifiers and plans are generated render state, not QMD authoring syntax.

A plan must distinguish a citation’s label from the separator or explanatory prefix included in an insertion/deletion.
It must also detect reordered or collapsed groups that no longer yield an unambiguous contiguous range.
If a boundary cannot be recovered, rendering must fail with a diagnostic identifying the affected citation group; dropping or broadening a comment is not a fallback.
Numeric range collapse, repeated keys and boundaries inside a key are not claimed as supported.

## The reference list

A new Quarto manuscript should use its generated bibliography normally.
An imported reference list with active review information cannot simply be replaced by a generated list.
The explicit source bibliography mode retains source-owned reference entries while formatting native in-text citations with the selected CSL.
Never infer that comments on references are disposable, or claim support for reviewing BibTeX field changes merely because a reference list renders.
Migrating those reviewed entries into a generated bibliography is a separate, explicit operation.

## Required verification

Use synthetic fixtures, including non-APA styles, and test both HTML and DOCX.
Verify citation wording against the same document without review markup.
Verify comment targets, suggestion alternatives, authors, replies and decisions, not just counts.
Cover grouped citations, narrative citations, locators, punctuation ownership, nested edits, collapsed years, unknown keys and source syntax beside CriticMarkup.
A normalization must be idempotent, retain unrelated edits and fail without partially writing a project.
Check that a render never writes manuscript sources or bibliography data.

The live manuscript is not a development fixture and its pinned runtime is not upgraded by this work.
