# Development isolation

Use a separate development environment named .venv-dev.
The legacy .venv can be retained by a manuscript or an already-running process and must not be repurposed for development.

```sh
UV_PROJECT_ENVIRONMENT=.venv-dev uv sync --locked
UV_PROJECT_ENVIRONMENT=.venv-dev uv run pytest
```

Always set UV_PROJECT_ENVIRONMENT when invoking uv for this repository.
Do not run a bare uv sync or uv run that would update the legacy environment.
The local ignored work/runtime-pin.json records the preserved runtime and compatibility paths for this workstation.

Develop source changes and run tests on synthetic fixtures in this repository or temporary directories.
Before running any command that enables an extension or writes configuration, check that its target is a fixture.
Do not install development code into a manuscript project, refresh its copied extension assets, run enable there, or use its content as a mutable test fixture.
Do not render that manuscript's Word output or inspect its HTML without a separate request.

The working manuscript, its review metadata, reference and presentation configuration remain owned by the manuscript editing chat.
A runtime pin may change its environment or launchers only.
Existing uncommitted work must be preserved.

## Migration boundary

Existing manuscript files remain authoritative until an explicitly coordinated migration.
Do not maintain a second manuscript copy for ongoing editing.
When the converter is ready, prepare candidate conversions from the latest working source and its frozen reference, recording input hashes.
Verify manuscript text, suggestion wording and decisions, comment anchors including deleted text, reply relationships, attribution and native identities.
Record unsupported native objects as blocking migration issues rather than dropping their information.

Arrange a brief editing pause with the user before the live switch.
During that pause, recheck input hashes and regenerate candidates if the source changed.
Preserve a rollback copy of the current live source, reference and runtime configuration before replacing anything.
The preserved runtime must remain available for that rollback.
Resume manuscript editing only after the coordinated switch has been checked.

Any step that would cross this boundary must be flagged to the user before it is taken.
