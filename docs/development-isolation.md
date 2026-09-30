# Development and manuscript isolation

Develop in `.venv-dev` and use synthetic fixtures in ignored work directories.
Do not install development changes into a manuscript project as part of testing.

~~~sh
UV_PROJECT_ENVIRONMENT=.venv-dev uv sync --locked
UV_PROJECT_ENVIRONMENT=.venv-dev uv run pytest -m "not private"
~~~

Always set UV_PROJECT_ENVIRONMENT when invoking uv in this repository.
An existing `.venv` may belong to a manuscript runtime; do not repurpose it.
Local maintainers can record protected runtimes in ignored work/runtime-pin.json.
Preserve unrelated uncommitted work.

## Upgrades and migrations

The working manuscript and its reference remain authoritative until the project owner approves a switch.
Prepare conversions from the latest inputs in a separate candidate directory, including the original Word assets when required.
Verify text, suggestions, anchors, replies, attribution, decisions and native records.
Record unsupported objects as unresolved cases, not successful conversions.

To convert a schema-1 project and its frozen reference into a separate schema-2 candidate, run:

~~~sh
quarto-review migrate --project ../legacy-manuscript --into ../migration-candidate
~~~

Conversion checks manuscript text, suggestion wording, anchors, replies, attribution, decisions and native records.
It produces a hash-bearing report and leaves the original files authoritative.
Candidates contain review sources and required native Word assets; they are not a complete copy of the manuscript's rendering dependencies.

Coordinate a brief editing pause before switching, check that the inputs have not changed, and retain a recoverable prior version in version control or a separate copy.
Do not replace later manuscript work with an older candidate.
An HTML or Word render and inspection of a private manuscript require the owner's authorization; synthetic fixtures are the default development inputs.
Flag work that would cross this boundary before taking it.

## Historical pinned runtime support

The Track Changes option was also made available to an existing pinned 0.2 runtime by updating its installed `finish.py` and `word_options.py`.
That hook uses the preserved runtime's interpreter and dependencies, without installing development code into it.
This describes the earlier compatibility work; follow the [installation guide](installation.md#upgrade-clone-or-move-a-project) for a normal version upgrade.
