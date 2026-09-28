# Release checks and evidence

This page records the checks for version 0.2.1.
Run these checks on the exact checkout that will be tagged.
Do not treat earlier schema-1 Word checks as evidence for a completed schema-2 application cycle.

## Recorded evidence

Version 0.2.1 was checked on macOS 26.5.2, Python 3.12.13, Quarto 1.8.27 and Node 24.15.0.
The public Python suite passed 185 tests, with four optional checks skipped and four private tests deselected.
Lint passed.
All six browser groups passed: review panel, author focus, status transitions, independent list, inline markers and media.
The scripted explicit review round passed, including retained local edits and reply provenance.
The built wheel rendered HTML and Word from an isolated installation and passed native package checks.
The [Ubuntu candidate check](https://github.com/githubpsyche/quarto-review/actions/runs/36495604497) passed on commit 58f5062892b26409d1518d3bdaad1bfbd15e0efa: 183 Python tests passed, six optional tests skipped and four private tests deselected.
All six browser groups, the explicit review round, isolated wheel rendering and guide build also passed remotely.
The [follow-up Ubuntu run](https://github.com/githubpsyche/quarto-review/actions/runs/36496526120) confirmed the same totals and listed the six skipped checks: one standalone-Pandoc check, three installed-APAQuarto checks, Jupyter execution and PDF output.
The native schema-2 Word application check below passed on 29 September 2026.
Windows, Word for the web and arbitrary native formatting or embedded objects are outside this application check.

## Automated checks

~~~sh
UV_PROJECT_ENVIRONMENT=.venv-dev uv sync --locked
UV_PROJECT_ENVIRONMENT=.venv-dev uv run ruff check quarto_review tests tools benchmarks
UV_PROJECT_ENVIRONMENT=.venv-dev uv run pytest -q -ra -m "not private"
npm ci
npx --no-install playwright install chromium
UV_PROJECT_ENVIRONMENT=.venv-dev uv run python tools/run_browser_checks.py
UV_PROJECT_ENVIRONMENT=.venv-dev uv run python tools/check_review_round.py --output work/release-round
UV_PROJECT_ENVIRONMENT=.venv-dev uv build --wheel
UV_PROJECT_ENVIRONMENT=.venv-dev uv run python tools/check_package.py dist/quarto_review-0.2.1-py3-none-any.whl
UV_PROJECT_ENVIRONMENT=.venv-dev uv run python tools/build_demo.py --output dist/release-demo
~~~

Use fresh output directories for the review-round and demo checks.
On Linux, Playwright's `install --with-deps chromium` installs required system libraries for CI.
The browser runner serves only synthetic fixtures on an available loopback port and closes its browser and server after checking.
The wheel check installs into a disposable environment and renders using that installed package.

The CI workflow runs tests on pull requests as well as main.
Only successful main builds can deploy the guide; pull requests have read-only repository permissions and do not deploy Pages.
The guide displays its package version and links to build-info.json containing the commit, whether the working tree was modified, and an input hash.
A local uncommitted build is labelled as such and must not be presented as an exact published release.

## Current-format native Word check

The checked runtime is commit 58f5062892b26409d1518d3bdaad1bfbd15e0efa, version 0.2.1, using Word for Mac 16.113.2 (16.113.26092012) on macOS 26.5.2.
Subsequent release changes only document the results, pin installation examples and add the synthetic input fixture.
Use [native-word-cycle.qmd](../tests/fixtures/native-word-cycle.qmd) as both index.qmd and reference.qmd in a fresh directory, enable review rendering, and render Word.
Keep the sent QMD and Word file, then change the working follow-up sentence from brief to two days while leaving its reference fixed.
Record the exact package version or build hash, Word version, operating system and date when repeating the check.

1. Open sent.docx in Word. Confirm no repair warning, correct manuscript author, a readable thread and a pending replacement.
2. Accept the magnitude replacement (large to modest), reject the sample replacement (small to large), reply “The revised magnitude addresses my concern.” and resolve the thread. Save a separate returned-native.docx.
3. Import returned-native.docx into a fresh candidate. Check the reply text, author, date, parent and resolution against the saved Word document.
4. Follow the explicit reconciliation example on a disposable working project that also contains the local two-day edit. Validate and render it again.
5. Reopen that export in Word, inspect the thread and wording, save another copy and import it independently. Verify those records again.

The completed check preserved both original and proposed readings, root and reply text, author, date, parent relationship, anchor and resolution, and the newer local wording as pending changes.
Both candidate imports left the working source and frozen reference unchanged.
Word rounded pending revision timestamps to minutes; message timestamps stayed unchanged.
The final Word-written file had SHA-256 `15dc89d919b00a3a57139c55e6655c5fe1c752c4e831d1b160ad0ac05835ac35`.
Generated files and native user-profile attribution remain in the ignored local test directory.
The application check included manual file opening and the final Save As; it was not an unattended UI test.
The scripted return check is separate evidence and does not substitute for this application cycle.

## Publish a verified candidate

Review the complete source diff and the generated guide against the evidence above.
Update the compatibility report with exact results, skipped checks and any remaining restrictions.
Prepare installation instructions for the intended release tag and publish that tag before deploying the matching guide.
Commit the intended source and create a matching version tag; do not include private manuscripts or local runtime files.
Build release assets from that clean tag, verify their checksums, and publish the wheel, source distribution, release notes and matching guide.
Release notes should distinguish supported current workflows from historical or unverified behaviour.
