# Installation and project lifecycle

The package requires Python 3.12 or later and Quarto; development and CI use Quarto 1.8.27.
Node is used only for browser tests, not for manuscript editing or rendering.
The instructions below select version 0.3.2; its validation scope is recorded in [release evidence](release.md).

## Install a chosen checkout

~~~sh
git clone --branch v0.3.2 https://github.com/githubpsyche/quarto-review.git
cd quarto-review
python3 -m venv .venv-user
source .venv-user/bin/activate
python -m pip install .
~~~

On Windows create the environment with `py -3 -m venv .venv-user` and activate it with `.venv-user\Scripts\Activate.ps1` in PowerShell.
Record `git rev-parse HEAD` with the installed version; an unpinned default branch can change.
For a built wheel, install its actual filename with `python -m pip install /path/to/quarto_review-0.3.2-py3-none-any.whl`.
Do not use a development editable installation for a manuscript that must stay on a fixed runtime.

In the manuscript directory, `quarto-review init --author "Your Name"` initializes an existing plain index.qmd.
For an existing review source or imported candidate, use `quarto-review enable`.
The review author identifies new feedback and does not replace the title-page author.

## What enable changes

| Location | Change |
| --- | --- |
| `_extensions/quarto-review/` | Copies the filters, preview assets and finishing hook; adds generated preview dependencies. |
| `_quarto.yml` | Adds a pre-AST review filter, a post-Quarto citation filter, review paths and a post-render hook while retaining format settings. YAML comments and formatting can be rewritten. |
| `_environment.local` | Sets QUARTO_PANDOC, QUARTO_REVIEW_PROJECT and QUARTO_REVIEW_COMMAND to local absolute paths. |
| `.quarto/review/runtime.json` | Records the original Pandoc executable and reader path. |
| `.gitignore` | Ignores generated runtime and preview dependencies. |

Enable does not advance reference.qmd or rewrite index.qmd.
Initialization and explicit review commands do change source; inspect the resulting source diff.
The environment must remain available after installation because renders call its executables.

## Tracking subsequent Word edits

To enable Word's Track Changes setting in newly rendered review files, add this project-wide setting to `_quarto.yml`:

~~~yaml
quarto-review:
  word:
    track-changes: true
~~~

Set it to `false` to disable that setting, or omit it to preserve the reference document's setting.
This option is read from the project `_quarto.yml`; it is not currently a per-document or profile override.
It governs subsequent edits in Word and does not accept or reject existing revisions, change comment resolutions, or lock editing.
The post-render hook applies it only to newly rendered Word outputs, before native review finishing; an HTML-only render leaves Word files alone.

## Upgrade, clone or move a project

Preserve the current project and runtime before upgrading.
Install the chosen package version in a separate environment and first test it on a copy with its reference, bibliography, figures and original Word archives.
Run enable from that environment in the copied project, validate, then render the formats you use.
After checking the result, coordinate the live switch with anyone editing the manuscript.

A clone does not include ignored local environment settings; install the package and run enable locally.
After moving an environment or project, run enable again to recreate absolute paths.
If enable reports a missing previously recorded Pandoc executable, remove the three generated review variables from _environment.local and the generated .quarto/review/runtime.json, then enable again.
Preserve any pre-existing custom Pandoc configuration before changing it.

## Remove rendering integration

There is no uninstall command yet.
Save the source and original Word assets first.
Remove only the quarto-review pre-AST and post-Quarto citation filters, its post-render hook and its top-level settings from _quarto.yml.
Remove the three generated variables from _environment.local, restoring any original QUARTO_PANDOC setting that existed before enable.
Remove the copied _extensions/quarto-review directory and generated .quarto/review runtime files when no running preview needs them.
Retain unrelated project settings and ignore rules.

Annotated QMD still needs review processing to render correctly.
Removing the integration does not convert it into plain QMD or settle pending decisions; retain the annotated source and use a deliberately checked clean export if leaving the workflow.

## Saving with other editors

Commands check for changes made since they read the source, validate their result, then replace the file atomically.
There is no shared editing lock, and a change between the check and replacement can still be overwritten.
Use one writer at a time, including editors and coding agents, and keep source in version control.
