# Development boundary

Read CONTRIBUTING.md and docs/development-isolation.md before runtime changes.

- Use UV_PROJECT_ENVIRONMENT=.venv-dev for every uv command.
- The legacy .venv is reserved for compatibility with a live manuscript and points to a preserved runtime.
- Do not repoint or reinstall that legacy environment.
- Develop and test only in this repository and disposable fixtures.
- Do not modify, install into, migrate, render Word for, or inspect HTML from the live manuscript project without specific authorization.
- Keep its source, review metadata, frozen reference and presentation files under the manuscript chat's ownership.
- Consult the ignored work/runtime-pin.json for local runtime paths.
- Candidate migrations must use the latest live inputs and be revalidated during a user-coordinated editing pause before switching.
- Preserve all pre-existing uncommitted work and rollback material.
- Flag any step that would break this separation before taking it.
