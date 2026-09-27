# Public walkthrough

The public site is published at https://githubpsyche.github.io/quarto-review/.
Its manuscript doubles as a walkthrough; every feature shown in the text is backed by review data in the example itself.
All names, study details and results are synthetic.

## Source and outputs

Maintain examples/walkthrough/index.qmd, reference.qmd, _quarto.yml and README.md.
The frozen reference intentionally differs from the working document in the practice-session sentence.
Keep unrelated walkthrough explanations consistent between them so they do not become unintended manuscript suggestions.

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

.github/workflows/pages.yml runs on pushes to main and manual dispatch.
It installs the locked Python dependencies and Quarto 1.8.27, runs the non-private regression tests, builds and validates the walkthrough, and deploys the generated site with GitHub's Pages artifact actions.
Repository Pages settings must use GitHub Actions as the source.
The build job has read-only repository access; the deployment job has Pages and identity-token permissions.
No personal access token is stored in the repository or workflow.

The public HTML is a read-only review interface.
Visitors can change views and filters, but replies and decisions are made in their own downloaded source.
Word discussion bodies currently preserve stored Markdown text rather than translating it into native Word formatting.
