# Release checks and evidence

This page records the checks for version 0.3.0 and preserves the earlier 0.2.1 evidence below.
Run these checks on the exact checkout that will be tagged.
Do not treat earlier schema-1 Word checks as evidence for a completed schema-2 application cycle.

## Version 0.3.0 evidence

The release includes native citation review and explicit cleanup of settled prose suggestions.
The isolated macOS release checkout passed 246 public Python tests, with four optional checks skipped and four private tests deselected. The skips require three installed-APAQuarto checks and Jupyter execution.
Lint and all six synthetic browser groups passed, as did the explicit review round, an independent installed-wheel check rendering HTML and Word with citations and cleanup, and the updated guide build.
The live-preview check now handles Quarto project and file preview separately: project preview renders on its reload request; file preview waits for the finished HTML before requesting it.
The Word application check passed on 30 September 2026 using Word for Mac 16.113.3 (16.113.26092714), macOS 26.5.2 (25F84), Python 3.12.13 and Quarto 1.8.27.
Its library input SHA-256 was `3074af18395a2585f99bca89050447a6242f1c3220a0fde5d39af9e659fcaad7`.
The final Word-written file had SHA-256 `db0954c42796c524d03419c5c3e061dbea04641123e57ff598efae746cc775ff`.
This fingerprint identifies package source, including its bundled extension; later documentation and test additions do not change that runtime.

## Current-format native Word check

Use the fictional [native-word-citations.qmd](../tests/fixtures/native-word-citations.qmd) and its bibliography.
The helper prepares a fresh isolated project and verifies each file after the native actions; it does not operate the Word UI or merge returns automatically.
Run each phase from the development environment:

~~~sh
UV_PROJECT_ENVIRONMENT=.venv-dev uv run python tools/check_native_citations.py prepare --output work/native-citations
~~~

1. Open sent.docx in Word. Confirm no repair warning, a readable manuscript and comments, and pending prose and citation changes.
2. Accept large → modest. Reject the added Smith (2022) citation, including its separate separator and year fragments. Reply to the magnitude thread with “The revised magnitude addresses my concern.” and to the second-reference thread with “The second reference is correct.” Resolve both; leave the reviewed-reference-entry thread open. Save returned-native.docx in the test directory.
3. Run the reconcile phase below. It imports a separate candidate, explicitly applies those decisions and discussions, retains the newer local two-day edit, and checks that compacting s0, s1 and s2 preserves the rendered readings, native revision wording and attribution, and complete discussion records. The original Word archive and bibliography remain unchanged.
4. Open reconciled.docx in Word, inspect its citation, comments and remaining local tracked changes, and save reopened-native.docx. Run verify to import it independently and check those records again.

~~~sh
UV_PROJECT_ENVIRONMENT=.venv-dev uv run python tools/check_native_citations.py reconcile --output work/native-citations
UV_PROJECT_ENVIRONMENT=.venv-dev uv run python tools/check_native_citations.py verify --output work/native-citations
~~~

Both candidate imports left the working source, reference and bibliography unchanged.
Cleanup updated settled decisions in both QMD files while retaining the newer local wording as pending changes.
The member comment stayed on Smith (2021), and the reviewed source bibliography entry retained its independent comment.
Word split the added citation into two tracked fragments; both had to be rejected.
On the second save, Word renumbered native review IDs and rounded revision timestamps to minutes. Verification matched complete comment records uniquely and checked their parent relationships under that mapping, along with ordered revision wording and attribution.
Ordinary prose edits receive render-time revision dates; fixed message timestamps remained unchanged.
Raw native files and user-profile attribution stay in ignored local test output, not the published download.
Windows, Word for the web and arbitrary native formatting or embedded objects are outside this application check.

## Historical 0.2.1 evidence

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
UV_PROJECT_ENVIRONMENT=.venv-dev uv run python tools/check_package.py dist/quarto_review-0.3.0-py3-none-any.whl
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

## Historical 0.2.1 native Word check

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
