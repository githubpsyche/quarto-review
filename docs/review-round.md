# A complete review round with the current source format

This is the schema-2 workflow: one working QMD and a frozen reference.
Import creates a separate candidate; there is no automatic merge into the working manuscript.
The `receive` command belongs to the older schema-1 workflow.

## Send an identified version

Validate the working source and render Word:

~~~sh
quarto-review validate
quarto render index.qmd --to docx
~~~

Retain that exact Word file and its corresponding QMD, reference, configuration and assets, for example in an identified Git commit plus the exported file.
The review-round reference may be older than the version sent; it is not necessarily the correct base for assessing a returned draft.
Do not advance the reference merely because a draft was sent.

Our example starts with a pending suggestion changing large to modest in a comment range:

~~~markdown
The study found [a {~~large~>modest~~}{#s1 by=A} effect]{#c1}.
The follow-up was brief.
~~~

The comment asks the author to qualify the magnitude.
While the reviewer reads the Word draft, the author changes the second sentence locally to “The follow-up lasted two days.”
The reviewer accepts the magnitude change, replies “The revised magnitude addresses my concern.” and resolves the thread.

## Inspect the return independently

~~~sh
quarto-review import-docx returned.docx --into ../feedback-candidate --author "Example Author"
quarto-review feedback --project ../feedback-candidate
~~~

Compare three states: the version sent, the returned candidate, and the current working source.
For this example:

| Passage or record | Sent | Returned | Current local action |
| --- | --- | --- | --- |
| Magnitude | Pending large → modest | Modest, no pending revision | Accept existing s1 after checking the return against the sent version. |
| Comment | Open, no reply | Resolved with reviewer reply | Transfer the reply and recorded resolution to existing c1. |
| Follow-up | Brief | Brief | Retain the newer local two-day sentence. |

Word removes revision records when a change is accepted or rejected.
The returned candidate alone therefore cannot tell you which decision produced its text; compare it with the exact draft sent.
Imported QMD identifiers may differ from the working identifiers.
Match discussion records using native provenance, authorship, message text and the anchored passage, not identifier spelling alone.
If the return and local source both changed the same passage incompatibly, settle that conflict explicitly before applying either version.

## Apply only the reviewed differences

For the matched suggestion, run `quarto-review accept s1` in the working project.
For the matched thread, transfer the new reply with its original author, date and parent relationship, and record its resolved state.
Do not use your default-author reply command to impersonate the returning reviewer.
Preserve the imported review-data alongside transferred records and copy their referenced immutable Word archives into the working project's assets/review directory.
Retain the corresponding review.imports entries.
Where QMD identifiers must be renamed to avoid a collision, update parent and range references together without changing the native Word identities.
Plain-text imported bodies should keep their format marker; do not reinterpret reviewer punctuation as Markdown inadvertently.

These transfers currently require source-level review; there is no general command that safely merges arbitrary returned threads.
Do not replace index.qmd wholesale with the candidate when newer local edits exist.
The candidate is evidence for the decisions, not a second authoritative manuscript.

Validate the working source, inspect its proposed reading, and render the next Word draft when ready.
Check the reply's author and date, its parent, the thread's state, the accepted wording and the retained local edit.
Leave the frozen reference unchanged until deliberately beginning another review round.

## Reproduce this exact example

From the extension repository:

~~~sh
UV_PROJECT_ENVIRONMENT=.venv-dev uv run python tools/check_review_round.py --output work/example-round
~~~

Use a fresh output directory each time.
The script produces sent.qmd, sent.docx, returned.docx, a candidate, the reconciled working project, reconciled.docx and report.json.
It applies only the explicit decisions described above and checks attribution, reply provenance and relationships, anchored text, the unchanged reference and the retained local edit.
It is a case-specific demonstration, not a reusable automatic merge algorithm.

The returned file is generated from scripted reviewer choices.
Passing this check establishes package and source behaviour, not that Microsoft Word itself preserves the same records when opening and saving.
The separate native Word check in the release guide remains necessary.
