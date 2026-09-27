"""Freeze actual executed inputs without later render mutations to the reference."""

import json

from quarto_review.execution import compiled_inputs, record_execution
from quarto_review.project import capture_reference, setup
from quarto_review.quarto import prepare


def test_compiled_reference_retains_outputs_and_detects_only_prose_edits(tmp_path):
    original = "A strong effect.\n\n```{python}\nprint(42)\n```\n"
    (tmp_path / "index.qmd").write_text(original)
    manuscript = setup(tmp_path, author="Writer")
    executed = "A strong effect.\n\n::: {.cell-output}\n42\n:::\n"
    record_execution(manuscript, "index.qmd", "docx", executed)
    manifest = capture_reference(manuscript)
    assert manifest["compiled"]["index.qmd:docx"]
    reference = tmp_path / "review/reference"
    files = {
        str(path.relative_to(reference)): path.read_bytes()
        for path in reference.rglob("*")
        if path.is_file()
    }
    (tmp_path / "index.qmd").write_text(original.replace("strong", "modest"))
    record = prepare(
        tmp_path,
        executed.replace("strong", "modest"),
        path="index.qmd",
        output="index.docx",
        format="docx",
    )
    assert len(record["automatic_suggestions"]) == 1
    assert "42" in record["markdown"]
    assert {
        str(path.relative_to(reference)): path.read_bytes()
        for path in reference.rglob("*")
        if path.is_file()
    } == files


def test_stale_execution_is_not_frozen(tmp_path):
    (tmp_path / "index.qmd").write_text("First.\n")
    manuscript = setup(tmp_path, author="Writer")
    record_execution(manuscript, "index.qmd", "html", "First.\n")
    (tmp_path / "index.qmd").write_text("Second.\n")
    assert compiled_inputs(manuscript) == {}
    manifest = capture_reference(manuscript)
    assert manifest["compiled"] == {}
    assert (
        json.loads((tmp_path / "review/reference/manifest.json").read_text())
        == manifest
    )


def test_changed_generated_value_is_compared_without_a_prose_edit(
    tmp_path, monkeypatch
):
    (tmp_path / "index.qmd").write_text("```{python}\nprint('calculated value')\n```\n")
    (tmp_path / "data.txt").write_text("42")
    manuscript = setup(tmp_path, author="Writer")
    monkeypatch.setenv("QUARTO_REVIEW_INCLUDE", '["data.txt"]')
    record_execution(manuscript, "index.qmd", "docx", "The calculated value is 42.\n")
    manifest = capture_reference(manuscript, include=("data.txt",))
    assert manifest["includes"] == ["data.txt"]
    monkeypatch.delenv("QUARTO_REVIEW_INCLUDE")
    (tmp_path / "data.txt").write_text("43")
    assert compiled_inputs(manuscript) == {}
    record = prepare(
        tmp_path,
        "The calculated value is 43.\n",
        path="index.qmd",
        output="index.docx",
        format="docx",
    )
    assert len(record["automatic_suggestions"]) == 1
    assert (tmp_path / "review/reference/data.txt").read_text() == "42"
