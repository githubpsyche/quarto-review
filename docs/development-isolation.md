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

Coordinate a brief editing pause before switching, check that the inputs have not changed, and retain a recoverable prior version in version control or a separate copy.
Do not replace later manuscript work with an older candidate.
An HTML or Word render and inspection of a private manuscript require the owner's authorization; synthetic fixtures are the default development inputs.
Flag work that would cross this boundary before taking it.
