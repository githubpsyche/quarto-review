# Verify a review exchange

Use [release checks](release.md) for the complete current-format procedure: Python tests, browser interactions, an explicit review round, an isolated wheel installation and a reproducible public guide build.
The [review-round example](review-round.md) explains how returned candidates are incorporated into current source without replacing newer work.

~~~sh
UV_PROJECT_ENVIRONMENT=.venv-dev uv sync --locked
UV_PROJECT_ENVIRONMENT=.venv-dev uv run pytest -q -m "not private"
UV_PROJECT_ENVIRONMENT=.venv-dev uv run ruff check quarto_review tests tools benchmarks
~~~

Tests use synthetic manuscripts by default.
Pandoc and Quarto must be available for conversion tests.
PDF checks require LuaLaTeX and pdftotext; execution checks require their optional runtimes.
Missing optional dependencies produce explicit skips.
For optional private or installed-style checks, set QUARTO_REVIEW_PRIVATE_DOCX or QUARTO_REVIEW_APA_EXTENSION to local inputs.
Those inputs are copied into temporary test projects and excluded from the shared repository.

The native Word application cycle below is historical schema-1 evidence.
For schema 2, follow the current-format native check in the release guide; `receive` is not its return workflow.

## Word package and schema checks

The regular command checks package relationships, review identifiers, anchors,
references, and leftover conversion markers:

```sh
quarto-review validate --docx manuscript.docx
```

This is not a complete OOXML schema validator. The separate development tool uses
[Microsoft's Open XML SDK validator](https://learn.microsoft.com/en-us/office/open-xml/word/how-to-validate-a-word-processing-document)
and requires the .NET 8 SDK:

```sh
dotnet run --project tools/WordValidation -- manuscript.docx
```

It opens inputs read-only and returns each error's part and path. When evaluating
a converted manuscript, validate the original and an equivalent plain Quarto
output as well. This distinguishes retained or generator errors from errors
introduced by review processing. Do not report a successful round trip based
only on the absence of Python exceptions.

## Historical schema-1 native Word check

The completed check used a synthetic manuscript with two threads, an existing
reply, a short replacement, and a replacement spanning two paragraphs. Word
opened it without a repair warning and retained the manuscript author. A new
reply and thread resolution returned correctly; the short replacement was
accepted and the paragraph replacement rejected. Repeating the import added
nothing. The regenerated file retained the final text, both replies in order,
and thread states through another Word save. That second return imported with
no changes or conflicts. The frozen QMD and YAML matched their original bytes.

The check used Word's native document API and text accessibility controls, with
no screenshots. Application control is needed only for this compatibility check,
not for ordinary editing, rendering, or return import. Generated test documents
and exchange archives remain in the ignored `work/` directory.

To repeat the check, use a synthetic example rather than an unpublished manuscript:

1. Render the example to DOCX and open it in Word. Confirm there is no repair
   warning and that the manuscript author is the QMD author.
2. Open both comment threads, read the reply, and confirm their authors. Add a
   reply and resolve one thread.
3. Accept one tracked replacement and reject another. Save under a new filename.
4. Run `quarto-review receive` on the saved file. Confirm the reply, resolution,
   decisions, and unchanged text. Repeating the import should add nothing.
5. Render again, reopen in Word, and confirm the same review state.

Record the Word version and platform with the result. A successful schema check
does not replace this application-level test.

## Performance

Run `UV_PROJECT_ENVIRONMENT=.venv-dev uv run python benchmarks/review_processing.py` without other renders or test
suites running. It checks the complete 50,000-word output and all 500 comments,
then reports cold and cached review overhead. Record the raw result alongside
the environment and interpret full-render differences as timing measurements
with ordinary rendering variability.


## Review-panel interaction regression

The synthetic fixture in tests/fixtures/review-panel.qmd includes an accepted section deletion, an accepted insertion, rejected insertion and deletion, pending changes, an open thread with a reply, a deletion-only comment, a resolved thread, and an accepted replacement containing a rejected change.
It contains no manuscript material.
Build its HTML-only preview in the ignored work directory:

```sh
UV_PROJECT_ENVIRONMENT=.venv-dev uv run python tools/build_review_panel_fixture.py
python3 -m http.server 4321 --bind 127.0.0.1 --directory work/review-panel/_output
```

In a separate terminal with Playwright CLI available, open that page and run the reusable interaction checks:

```sh
playwright-cli -s=review-panel open http://127.0.0.1:4321/index.html
playwright-cli -s=review-panel run-code "$(cat tools/check_review_panel.js)"
playwright-cli -s=review-panel close
```

The check changes the actual controls at wide and narrow viewport sizes.
It verifies coherent comment excerpts in all text views, nested decisions in cards, hover attribution for overlapping edits and empty markers, navigation after clicking or scrolling, and reading position when filters hide the selected item.
It also checks narrow-screen position preservation as earlier cards disappear, comment/change counts, status and author filters, unchanged redline colours under status filtering, no-match messages, Reading view and restoration.
Visibility checks hide controls and cards in both orders in Redline, Original and Proposed views, and repeat the toolbar sequence on a narrow screen.
They verify that hiding panels preserves deleted-text visibility and hover attribution, while explicit Reading view shows proposed text and restores the previous view.
The builder verifies that rendering leaves both the source and frozen reference unchanged.
The regular pytest suite separately checks safe Markdown rendering of change cards, native formatting descriptions and nested changes whose parent deletion has been accepted.
A parameterized regression covers each combination of parent and child decision on both sides of a replacement.

This check exercises the development copy only.
Updating the extension in an active manuscript is a separate deployment step.

## Author-specific redline regression

Render the synthetic author fixture with the development environment:

```sh
UV_PROJECT_ENVIRONMENT=.venv-dev uv run python tools/build_review_panel_fixture.py --source tests/fixtures/review-authors.qmd --output work/review-authors
```

Serve the repository root on port 4332, then open the rendered fixture and run its checks:

```sh
python3 -m http.server 4332 --bind 127.0.0.1
playwright-cli -s=review-authors open http://127.0.0.1:4332/work/review-authors/_output/index.html
playwright-cli -s=review-authors run-code "$(cat tools/check_review_authors.js)"
playwright-cli -s=review-authors close
```
The checks cover two authors' insertions, deletions and replacements, changes nested in either side of a replacement, accepted and rejected decisions, comment excerpts, navigation, no-match authors, both viewport layouts, hidden controls, and Reading view restoration.
The same script then checks the media fixture through that server.
If using another port, update `mediaUrl` at the top of the script.
Author filtering must never change source decisions or the Original and Proposed readings.

## Image and media interaction regression

The synthetic `tests/fixtures/review-media.html` fixture loads the development extension directly.
It reproduces the HTML structure of tracked image replacements, including linked images, standalone insertions and deletions, picture elements, SVG, math and unchanged images beside point anchors.
It does not contain manuscript material and does not require a Quarto render.

Serve the repository root on a separate local port:

```sh
python3 -m http.server 4329 --bind 127.0.0.1
```

Open `http://127.0.0.1:4329/tests/fixtures/review-media.html` and click **Run regression checks**.
With Playwright CLI, the same checks can be run as follows:

```sh
playwright-cli -s=review-media open http://127.0.0.1:4329/tests/fixtures/review-media.html
playwright-cli -s=review-media run-code "$(cat tools/check_review_media.js)"
playwright-cli -s=review-media close
```

All 22 checks must pass.
They verify that review filters and hidden controls or cards never remove manuscript images, that Original and Proposed retain the appropriate alternative, and that Reading view restores the prior view when closed.
They also check attribution, preserved image links, single wrapping of picture/SVG/math contents, and continued suppression of genuinely empty annotation blocks.
This guards against counting only text nodes when identifying empty blocks or applying change markup.

## Inline change markers

Visible changed text is the pointer and keyboard target for its review card.
Separate delta badges appear only when a change has no visible content in the selected text view, including point-only changes and hidden deletions or insertions.
This prevents Word revisions that split words into several runs from inserting badges inside those words.
Previous/Next navigation still visits each original review record separately.

The synthetic `tests/fixtures/review-markers.html` fixture reproduces adjacent changes inside a word and includes the existing media checks.
Serve the repository and run `tools/check_review_markers.js` through Playwright CLI on that fixture.
It checks wide and narrow layouts, click and keyboard access, navigation, view and author filters, hidden review cards, Reading view, media preservation, and unchanged decisions and attribution.


## Comment and change status filters

Build the synthetic fixture with `.venv-dev/bin/python tools/build_review_panel_fixture.py --source tests/fixtures/review-status.qmd --output work/review-status`.
Serve the repository locally, open `work/review-status/_output/index.html`, and run `tools/check_review_status.js` through Playwright CLI.
The fixture deliberately places a pending suggestion inside a resolved comment range.
The check verifies the combined open/pending defaults, type-specific status choices, corresponding-state transitions across every review type, each individual state, author filtering, counts, navigation and reading-view restoration at desktop and narrow widths.
It also checks that filtering does not alter the stored decisions or attribution.
The status control initializes its options in JavaScript, so the same behavior works with HTML from an older pinned renderer.


## Independent review list

Build the synthetic long-document fixture with `.venv-dev/bin/python tools/build_review_panel_fixture.py --source tests/fixtures/review-list.qmd --output work/review-list`.
Serve the repository locally, open `work/review-list/_output/index.html`, and run `tools/check_review_list.js` through Playwright CLI.
The check covers all filtered items in manuscript order, expanded discussion and replies, change alternatives, independent list scrolling and navigation, restored expansion and scroll state, explicit passage navigation, empty results, hiding and Reading view.
It checks that the active reading passage stays in place at desktop, tablet and phone widths, and that review decisions and attribution remain unchanged.
List summaries are built when the view is opened or its filters change; full cards are created only for expanded entries.
