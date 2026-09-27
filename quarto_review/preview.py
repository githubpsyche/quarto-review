"""Expose review dependencies to Quarto's existing live-preview watchers."""

from __future__ import annotations

import math
import os
import sys
import time
from pathlib import Path

from quarto_review.errors import ReviewError

PREVIEW_LINKS = {
    "review-state.yml": "../../review.yml",
    "review-reference.json": "../../review/reference/manifest.json",
}
PREVIEW_SIGNAL = "review-update.txt"


def invalidate(directory: Path) -> None:
    """Notify preview after saving review metadata or advancing the reference.

    Quarto 1.8's project preview compares dependency times at second precision.
    Give this generated signal a distinct second for every operation, even when
    decisions arrive faster. File preview also watches it as an extension file.
    No manuscript, reference, or rendered output is changed.
    """
    signal = directory / "_extensions/quarto-review" / PREVIEW_SIGNAL
    if signal.is_symlink() or not signal.is_file():
        return
    try:
        modified = max(math.ceil(time.time()), math.floor(signal.stat().st_mtime) + 1)
        os.utime(signal, (modified, modified))
    except OSError as error:
        # The source operation has already succeeded. Failing it here could make
        # a caller retry and accidentally duplicate a saved reply.
        print(
            f"quarto-review: review state was saved but preview could not be notified ({error}); restart preview if it shows old review state.",
            file=sys.stderr,
        )


def configure(directory: Path, *, reference: str | None = None) -> None:
    """Watch review files without copying or publishing their contents.

    Project preview uses the dependency paths registered in _quarto.yml. File
    preview watches extension files instead, so relative links make the same
    review files visible there. The generated signal distinguishes rapid source
    commands for Quarto's coarser project-preview cache.
    """
    from quarto_review.project import write_text

    extension = directory / "_extensions/quarto-review"
    links = (
        PREVIEW_LINKS
        if reference is None
        else {"review-reference.qmd": "../../" + reference}
    )
    for filename, target in links.items():
        link = extension / filename
        if link.is_symlink():
            if link.readlink() != Path(target):
                raise ReviewError(
                    f"The preview dependency link has an unexpected target: {link}"
                )
            continue
        if link.exists():
            raise ReviewError(
                f"The preview dependency path contains another file: {link}"
            )
        try:
            link.symlink_to(target)
        except OSError as error:
            print(
                f"quarto-review: file preview dependencies could not be linked ({error}); use project preview with `quarto preview` for direct YAML edits.",
                file=sys.stderr,
            )
            break
    signal = extension / PREVIEW_SIGNAL
    if signal.is_symlink():
        raise ReviewError(f"The generated preview signal cannot be a link: {signal}")
    write_text(signal, "Generated preview notification; contains no review content.\n")
    ignored = directory / ".gitignore"
    existing = ignored.read_text() if ignored.exists() else ""
    additions = [
        f"/_extensions/quarto-review/{name}"
        for name in (*links, PREVIEW_SIGNAL)
        if f"/_extensions/quarto-review/{name}" not in existing.splitlines()
    ]
    if additions:
        write_text(
            ignored,
            existing.rstrip("\n")
            + ("\n" if existing else "")
            + "\n".join(additions)
            + "\n",
        )
