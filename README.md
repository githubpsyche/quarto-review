# Quarto review

**Write and revise your manuscript in Quarto while collaborators review Word drafts with native comments and tracked changes.**
Quarto review brings supported Word feedback into editable QMD, keeps discussions attached to the text, and exports Word drafts with native review information.
Work in your preferred editor or with a coding assistant, inspect an HTML preview, and render Word when you are ready to share.

Keep manuscript text, suggestions, comments, replies and decisions together in index.qmd.
A frozen reference supplies the comparison for ordinary edits; explicit CriticMarkup lets you control how proposed changes are presented.

[Read the guide and live examples](https://githubpsyche.github.io/quarto-review/) · [Download the example source](https://githubpsyche.github.io/quarto-review/downloads/walkthrough.zip)

The current single-source format is schema 2.
It replaces the separately maintained review.yml used by schema 1.
Existing schema-1 projects remain supported; migration is explicit and creates candidates rather than switching a project.

## Files you maintain

| File | Responsibility |
| --- | --- |
| index.qmd | Manuscript and all current review information |
| reference.qmd | Frozen annotated source for the current review round |
| _quarto.yml and ordinary assets | The manuscript's existing formats, bibliography, figures and execution settings |

There is no mutable review sidecar and no mandatory export journal for schema 2.
Original Word packages may remain as immutable assets when native objects or imported comment relationships require them.
Caches and generated rendering plans are disposable.
Executed Markdown can be retained inside the frozen reference when the manuscript contains code.

## Source syntax

~~~markdown
The study found [a {~~large~>modest~~}{#s1 by=R} difference]{#c1}.

:::: {.review-thread #c1 by=R}
Please qualify the description of the effect size.

::: {.reply #r1 by=A}
I agree with the suggested wording.
:::
::::
~~~

Author aliases are defined once in the QMD front matter:

~~~yaml
review:
  schema: 2
  author: A
  authors:
    A: Example Author
    R: Example Reviewer
~~~

Comment threads can be placed near their passages or together at the end of the file.
Moving a complete thread does not change its anchor or count as an edit to the manuscript.
Open and pending are defaults.
Use .resolved on a thread, and .accepted or .rejected on a suggestion, to record decisions.

Ordinary prose edits need no explicit markup: they are compared with the frozen reference.
CriticMarkup is available when you want to control how a suggested replacement is presented.
Read the [source-format guide](docs/single-source.md) for overlapping ranges, reply relationships, timestamps and native provenance.

## Start a new project

Install Python 3.12 or later and Quarto.
From an installed release, run:

~~~sh
quarto-review init --author "Example Author"
quarto render index.qmd --to html
~~~

Initialization uses an existing plain index.qmd, adds review settings, enables the extension and freezes its reference.
It does not replace the manuscript author field.
For a self-contained example, copy [examples/single-source-proposal](examples/single-source-proposal) into a separate directory and run the following commands there:

~~~sh
quarto-review enable
quarto render index.qmd --to html
~~~

Word output is an explicit render:

~~~sh
quarto render index.qmd --to docx
~~~

Choose the manuscript style through the project's normal Quarto format settings, including installed APAQuarto formats.
The extension provides review controls rather than replacing manuscript layout.
HTML includes original, proposed and redline views, navigation through comments or changes, filters, margin cards and a clean reading view.
Change cards retain before/after wording for accepted and rejected suggestions, including deletions that leave no manuscript text.
Filters select review records without fading the redline text or jumping away from the current passage.
Hover over a change to see who suggested it.
Comment excerpts distinguish original and proposed wording when changes overlap the quoted passage.
The HTML discussion is read-only; source commands make edits.
Comments and replies render basic Markdown formatting, while imported Word feedback retains literal punctuation and line breaks.
See [discussion syntax and output limits](docs/single-source.md#comments-and-ranges) for plain-text messages and Word export behaviour.

## Edit and discuss

~~~sh
quarto-review feedback
quarto-review reply c1 --body "I have clarified the claim."
quarto-review resolve c1
quarto-review reopen c1
quarto-review delete-comment c1
quarto-review accept s1
quarto-review reject s1
quarto-review pending s1
quarto-review comment --text "an exact passage" --body "Explain this."
quarto-review suggest --text "large" --replacement "modest"
quarto-review group --text "the wording already edited" --before "the previous wording"
quarto-review validate
~~~

These operations validate and atomically replace the one QMD source.
Deleting a thread removes its messages and range references, while retaining manuscript text, suggestions and overlapping comments.
Concurrent source changes cause the operation to stop rather than overwrite newer work.
Rendered outputs and the reference are not authoritative copies to edit.

Start a new review round explicitly:

~~~sh
quarto-review reference --new-round
~~~

For executable manuscripts, capture executed inputs with the reference:

~~~sh
quarto-review reference --new-round --execute --to html --to docx
~~~

## Word feedback and migration

Import a reviewed Word file into a new candidate directory:

~~~sh
quarto-review import-docx feedback.docx --into ../feedback-candidate --author "Example Author"
~~~

This preserves native attribution and source identities.
Returned Word feedback is reviewed against an explicitly selected prior version; schema 2 does not silently merge it into an active manuscript.
The older automatic receive workflow remains specific to schema 1.

Convert a schema-1 project and its frozen reference into a separate candidate:

~~~sh
quarto-review migrate --project ../legacy-manuscript --into ../migration-candidate
~~~

Conversion checks manuscript text, suggestion wording, anchors, replies, attribution, decisions and native records.
It produces a hash-bearing report and leaves the original files authoritative.
Candidates contain review sources and required native Word assets; they are not a second manuscript working directory or a complete copy of all rendering dependencies.
Read [migration and development isolation](docs/development-isolation.md) before any live switch.

## Development and evidence

Use the isolated development environment:

~~~sh
UV_PROJECT_ENVIRONMENT=.venv-dev uv sync --locked
UV_PROJECT_ENVIRONMENT=.venv-dev uv run pytest -m "not private"
~~~

Never repurpose the legacy .venv while it protects a pinned manuscript runtime.
Development fixtures must stay separate from that manuscript.
See [status and limits](docs/status.md), [architecture](docs/design.md), and [performance](docs/performance.md).
The historic interactive Word verification applies to the prior source format and exporter; the new format has separate automated tests.

## Public guide and examples

The [public guide](https://githubpsyche.github.io/quarto-review/) explains the local files and editing workflow, pairing source examples with their rendered review annotations.
It demonstrates pending replacements, insertions and deletions, ordinary edits against a frozen reference, overlapping comments, threaded replies, resolution, accepted/rejected suggestions, Markdown discussions and literal imported-style text.
Readers can follow the source-to-output examples, try the HTML controls, and download both the Word output and editable project.

Its maintained source is in [examples/walkthrough](examples/walkthrough).
The [demo build guide](docs/demo.md) explains local builds and the GitHub Pages publishing workflow.
