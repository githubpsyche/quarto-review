"""Review commands expose ordinary edits and preserve decisions across rounds."""

import json

from quarto_review.cli import main
from quarto_review.markup import project as project_text
from quarto_review.project import Project, capture_reference, setup


def test_ordinary_edit_can_be_inspected_and_rejected_without_render(tmp_path, capsys):
    (tmp_path / "index.qmd").write_text("A strong effect.\n")
    capture_reference(setup(tmp_path, author="Writer"))
    (tmp_path / "index.qmd").write_text("A modest effect.\n")
    reference = (tmp_path / "review/reference/index.qmd").read_bytes()
    assert main(["feedback", "--project", str(tmp_path), "--status", "pending"]) == 0
    items = json.loads(capsys.readouterr().out)
    assert [(item["before"], item["after"], item["author"]) for item in items] == [
        ("strong", "modest", "Writer")
    ]
    identifier = items[0]["id"]
    assert main(["reject", identifier, "--project", str(tmp_path)]) == 0
    manuscript = Project.read(tmp_path)
    assert manuscript.metadata.suggestions[identifier].status == "rejected"
    assert (
        project_text(
            manuscript.documents["index.qmd"].nodes, decisions={identifier: "rejected"}
        )
        == "A strong effect.\n"
    )
    assert (tmp_path / "review/reference/index.qmd").read_bytes() == reference
    assert not any(item.get("automatic") for item in manuscript.feedback())


def test_new_round_allows_further_author_edits_to_accepted_wording(tmp_path):
    (tmp_path / "index.qmd").write_text("A strong effect.\n")
    capture_reference(setup(tmp_path, author="Writer"))
    (tmp_path / "index.qmd").write_text("A modest effect.\n")
    manuscript = Project.read(tmp_path)
    identifier = manuscript.feedback()[0]["id"]
    manuscript.decide(identifier, "accept")
    capture_reference(Project.read(tmp_path), new_round=True)
    path = tmp_path / "index.qmd"
    path.write_text(path.read_text().replace("modest", "small"))
    feedback = Project.read(tmp_path).feedback()
    automatic = [item for item in feedback if item.get("automatic")]
    assert [(item["before"], item["after"]) for item in automatic] == [
        ("modest", "small")
    ]
