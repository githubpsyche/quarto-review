# Public guide and examples

The public site is published at https://githubpsyche.github.io/quarto-review/.
The page introduces the purpose of the extension, explains the local source files, and pairs editing examples with rendered review features.
HTML controls demonstrate the results after the source workflow is explained.
All names, study details and results are synthetic.

## Source and outputs

Maintain examples/walkthrough/index.qmd, reference.qmd, _quarto.yml and README.md.
The frozen reference intentionally differs from the working document in the practice-session sentence.
When revising this synthetic documentation fixture, keep its explanations consistent between working and reference files so they do not become unintended manuscript suggestions.
This fixture maintenance is not the workflow for a live review round, whose reference must remain frozen.

The build uses a temporary copy of those four files.
It enables the development extension there, creates an editable ZIP and renders HTML and Word using Quarto's standard manuscript format.
It checks local links and resources, formatted and literal discussion bodies, comment text and authors, native replies, resolution, tracked changes and the intended ordinary edit.
It also checks that the maintained example files were not changed.

Run from the repository root:

~~~sh
UV_PROJECT_ENVIRONMENT=.venv-dev uv sync --locked
UV_PROJECT_ENVIRONMENT=.venv-dev uv run python tools/build_demo.py
~~~

The output is dist/demo.
For another local build, supply a fresh output directory with --output dist/demo-next.
Generated outputs are ignored by Git.
The build uses only the synthetic example; it does not read, configure or render a separate manuscript project.

## GitHub Pages

.github/workflows/pages.yml checks pull requests, pushes to main and manual dispatches.
It installs the locked Python and browser dependencies and Quarto 1.8.27, runs source tests, browser checks, the explicit review-round example and an isolated wheel check, then builds the guide.
Only successful main builds deploy through GitHub Pages; pull requests cannot deploy.
The guide displays its package version and links to downloads/build-info.json with the commit, modified-tree flag and source hash.
A locally modified build is labelled as such rather than presented as a released commit.
Repository Pages settings must use GitHub Actions as the source.
The build job has read-only repository access; the deployment job has Pages and identity-token permissions.
No personal access token is stored in the repository or workflow.

The public HTML is a read-only review interface.
Visitors can change views and filters, but replies and decisions are made in their own downloaded source.
Word discussion bodies currently preserve stored Markdown text rather than translating it into native Word formatting.
