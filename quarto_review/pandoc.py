"""Run Pandoc with explicit formats and useful failure messages."""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path

from quarto_review.errors import ReviewError


def command() -> list[str]:
    """Find the configured Pandoc, a local installation, or Quarto's Pandoc."""
    configured = os.environ.get("QUARTO_REVIEW_PANDOC")
    executable = configured or shutil.which("pandoc")
    if executable:
        return [executable]
    quarto = shutil.which("quarto")
    if quarto:
        return [quarto, "pandoc"]
    raise ReviewError("Install Quarto or Pandoc, or set QUARTO_REVIEW_PANDOC")


def run(
    arguments: Sequence[str],
    *,
    source: str | None = None,
    directory: Path | None = None,
) -> str:
    """Convert input while keeping the process invocation separate from a shell."""
    try:
        result = subprocess.run(
            [*command(), *arguments],
            input=source,
            cwd=directory,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as error:
        raise ReviewError(f"Could not start Pandoc: {error}") from error
    if result.returncode:
        raise ReviewError(
            f"Pandoc failed: {result.stderr.strip() or result.stdout.strip()}"
        )
    if "[WARNING]" in result.stderr:
        raise ReviewError(
            f"Pandoc reported an incomplete conversion: {result.stderr.strip()}"
        )
    return result.stdout
