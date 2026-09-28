# Discussion formatting measurement

A batch of 500 synthetic Markdown messages converted and sanitized in 0.171 seconds during discussion-formatting development.
Each message contained emphasis, a list, a link and a second paragraph.
The batch uses one Pandoc process and parses each message independently.
Plain-text messages require no conversion process.
This measures discussion HTML generation in one local run, not a complete Quarto render.

# Single-source reader measurement

A synthetic input of approximately 50,000 manuscript words, 500 comments and 500 suggestions parsed and validated in 0.191 seconds during schema-2 development.
The source contained 293,251 characters.
This measures the new reader in one local run; it does not include Quarto rendering, output conversion or a cold-process startup.
It is not an end-to-end performance guarantee.

# Review processing performance

The benchmark creates a temporary manuscript containing 50,000 prose words and
500 comment threads. It changes one word in each of 100 paragraphs after capturing
the reference. No private manuscript content is used.

The core measurement times source preparation and native Word finishing. The full
measurement compares otherwise equivalent Quarto DOCX renders with and without
review processing. It verifies that both outputs retain the entire manuscript
and that the review output retains all 500 comments. The first pair measures cold
local review caches; subsequent pairs provide the cached median.

Run it with:

```sh
UV_PROJECT_ENVIRONMENT=.venv-dev uv run python benchmarks/review_processing.py
```

For diagnostic runs, `--paragraphs` changes the document size and `--pairs`
changes the number of paired renders. Set `QUARTO_REVIEW_TIMING=1` to print timing
checkpoints inside the Quarto filter.

The first complete integration benchmark exposed a slow initial Pandoc parse of
raw CriticMarkup. Although the Python review stages took less than one second,
the full render added approximately 74 seconds. A pre-AST filter alone did not
avoid that initial parse. The integration now uses a project-local Pandoc launcher
and reader so review syntax is prepared before Markdown is parsed.

The revised integration meets the two-second target on this fixture. On macOS
26.5.2 (arm64), Python 3.12.14, and Quarto 1.8.27, the first paired render added
1.14 seconds. The median of the next three review renders exceeded the median
ordinary render by 1.47 seconds. Both generated documents retained all 50,000
words, and the review document retained all 500 comments.

| Measurement | Cold | Cached |
| --- | ---: | ---: |
| Review preparation and Word finishing | 1.11 s | 0.64 s |
| Additional time in complete Quarto renders | 1.14 s | 1.47 s |

The complete renders include ordinary rendering variability, so their differences
need not equal the isolated Python stages. These measurements establish performance
for this synthetic prose fixture, not for every manuscript or output format.
The [recorded results](../benchmarks/results/2026-09-27-macos-arm64.json) include
all four paired render times and the fixture counts.
