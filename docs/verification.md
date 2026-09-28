# Verify a review exchange

On 27 September 2026, all 114 tests passed with the private and APA fixtures,
Jupyter dependencies, and PDF tools available. A complete native review cycle
also passed in Word for Mac 16.113.2 on macOS 26.5.2. The independent schema
findings and application-specific fixes are in [the compatibility report](status.md).

The built wheel was also installed in an isolated environment and used to render
the example to HTML and DOCX without activating that environment. The packaged
filters and project-local commands worked, and the resulting Word package passed
the review invariant checks.

Live-preview integration tests run both `quarto preview` and
`quarto preview index.qmd`, follow Quarto's browser reload messages, and verify
replies, resolution, prose edits, and a new reference during the same process.
File preview also refreshes a reply edited directly in YAML. Test processes are
closed after the checks; no graphical browser is required.

Run the test suite from the repository with its development environment:

```sh
uv sync --group dev --group execution-tests
uv run pytest
uv run ruff check quarto_review tests benchmarks
```

Tests use synthetic manuscripts by default. Pandoc and Quarto must be on the
path for conversion tests. PDF checks require LuaLaTeX and `pdftotext`. Missing
optional runtimes produce explicit skips. To run private or existing-format
checks, set `QUARTO_REVIEW_PRIVATE_DOCX` to a local fixture and
`QUARTO_REVIEW_APA_EXTENSION` to an installed `apaquarto` extension directory.
Those inputs are read, copied into temporary test projects, and excluded from the
shared repository.

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

## Native Word check

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

Run `uv run python benchmarks/review_processing.py` without other renders or test
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
It also checks narrow-screen position preservation as earlier cards disappear, comment/change counts, status and author filters, unchanged redline colours, no-match messages, Reading view and restoration.
The builder verifies that rendering leaves both the source and frozen reference unchanged.
The regular pytest suite separately checks safe Markdown rendering of change cards, native formatting descriptions and nested changes whose parent deletion has been accepted.
A parameterized regression covers each combination of parent and child decision on both sides of a replacement.

This check exercises the development copy only.
Updating the extension in an active manuscript is a separate deployment step.
