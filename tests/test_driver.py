"""Keep Quarto launcher setup local and preserve a chosen Pandoc executable."""

import json
import shutil
from pathlib import Path

import pytest

from quarto_review.errors import ReviewError
from quarto_review.pandoc_driver import configure
from quarto_review.project import capture_reference, setup
from quarto_review.quarto import prepare


def test_configuration_preserves_other_keys_and_custom_pandoc(tmp_path):
    executable = shutil.which("pandoc")
    if executable is None:
        pytest.skip("Pandoc is not installed")
    environment = tmp_path / "_environment.local"
    environment.write_text(f'OTHER_SETTING="retained"\nQUARTO_PANDOC="{executable}"\n')
    configure(tmp_path)
    runtime = tmp_path / ".quarto/review/runtime.json"
    assert json.loads(runtime.read_text())["pandoc"] == str(Path(executable).resolve())
    assert 'OTHER_SETTING="retained"' in environment.read_text()
    first = environment.read_text()
    configure(tmp_path)
    assert environment.read_text() == first
    assert json.loads(runtime.read_text())["pandoc"] == str(Path(executable).resolve())


def test_missing_executed_annotation_is_not_silently_discarded(tmp_path):
    (tmp_path / "index.qmd").write_text(
        '---\ntitle: "{++Title++}{#s1}"\n---\n\nBody.\n'
    )
    manuscript = setup(tmp_path, author="Writer")
    capture_reference(manuscript)
    with pytest.raises(ReviewError, match="omitted review annotations s1"):
        prepare(
            tmp_path, "Body.\n", path="index.qmd", output="index.docx", format="docx"
        )
