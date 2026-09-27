"""Reconcile exact Word exports, keeping concurrent and ambiguous edits visible."""

import shutil
import subprocess
from dataclasses import replace
from datetime import datetime

import pytest
from lxml import etree

from quarto_review import pandoc
from quarto_review.errors import ReviewError
from quarto_review.markup import parse
from quarto_review.markup import project as project_text
from quarto_review.project import Project, capture_reference, setup
from quarto_review.quarto import enable, finish_outputs, prepare
from quarto_review.returns import receive
from quarto_review.word.comments import write_comments
from quarto_review.word.identity import read_identity
from quarto_review.word.namespaces import NS, tag
from quarto_review.word.package import WordPackage
from quarto_review.word.reader import read_review
from quarto_review.word.records import WordComment


def export(tmp_path, source):
    (tmp_path / "index.qmd").write_text(source)
    manuscript = setup(tmp_path, author="Writer")
    capture_reference(manuscript)
    record = prepare(
        tmp_path, source, path="index.qmd", output="index.docx", format="docx"
    )
    path = tmp_path / "index.docx"
    pandoc.run(
        ["--from=markdown-smart", "--to=docx", "--output", str(path)],
        source=record["markdown"],
    )
    finish_outputs(tmp_path, ("index.docx",))
    return WordPackage.read(path)


@pytest.mark.integration
def test_returned_reply_resolution_and_repeat_import(tmp_path):
    package = export(tmp_path, "A {==claim==}{>>Explain this.<<}{#c1}.\n")
    comments = list(read_review(package).comments)
    comments[0] = replace(comments[0], resolved=True)
    comments.append(
        WordComment(
            "10",
            "Reviewer",
            "2026-01-02T09:00:00Z",
            "This answers my question.",
            parent_id=comments[0].id,
            resolved=True,
        )
    )
    write_comments(package, comments)
    incoming = tmp_path / "returned.docx"
    package.write(incoming)
    frozen = (tmp_path / "review/reference/index.qmd").read_bytes()
    result = receive(tmp_path, incoming)
    assert result["conflicts"] == []
    assert result["status"] == "applied"
    manuscript = Project.read(tmp_path)
    assert manuscript.metadata.comments["c1"].status == "resolved"
    assert manuscript.metadata.comments["c1"].replies[0].author == "Reviewer"
    assert receive(tmp_path, incoming)["duplicate"] is True
    assert len(Project.read(tmp_path).metadata.comments["c1"].replies) == 1
    assert (tmp_path / "review/reference/index.qmd").read_bytes() == frozen


@pytest.mark.integration
def test_concurrent_comment_edits_leave_working_files_untouched(tmp_path):
    package = export(tmp_path, "A {==claim==}{>>Explain this.<<}{#c1}.\n")
    comments = [
        replace(item, text="Different feedback.")
        for item in read_review(package).comments
    ]
    write_comments(package, comments)
    incoming = tmp_path / "returned.docx"
    package.write(incoming)
    (tmp_path / "index.qmd").write_text("A {==claim==}{>>Local feedback.<<}{#c1}.\n")
    before = {
        name: (tmp_path / name).read_bytes() for name in ("index.qmd", "review.yml")
    }
    result = receive(tmp_path, incoming)
    assert result["status"] == "conflicts"
    assert any(item["kind"] == "comment" for item in result["conflicts"])
    assert {name: (tmp_path / name).read_bytes() for name in before} == before
    assert (tmp_path / result["archive"] / "returned.qmd").is_file()


@pytest.mark.integration
def test_new_word_revisions_retain_reviewer_and_acceptance_views(tmp_path):
    package = export(tmp_path, "A strong effect.\n")
    root = package.xml("word/document.xml")
    paragraph = root.find(".//w:body/w:p", NS)
    run = paragraph.find("./w:r", NS)
    position = paragraph.index(run)
    paragraph.remove(run)
    fragments = []
    for text, kind, identifier in (
        ("A ", None, None),
        ("strong", "del", "20"),
        ("modest", "ins", "21"),
        (" effect.", None, None),
    ):
        leaf_run = etree.Element(tag("w", "r"))
        leaf = etree.SubElement(leaf_run, tag("w", "delText" if kind == "del" else "t"))
        leaf.set(tag("xml", "space"), "preserve")
        leaf.text = text
        if kind:
            wrapper = etree.Element(tag("w", kind))
            wrapper.set(tag("w", "id"), identifier)
            wrapper.set(tag("w", "author"), "Reviewer")
            wrapper.set(tag("w", "date"), "2026-01-02T09:00:00Z")
            wrapper.append(leaf_run)
            fragments.append(wrapper)
        else:
            fragments.append(leaf_run)
    for offset, fragment in enumerate(fragments):
        paragraph.insert(position + offset, fragment)
    package.set_xml("word/document.xml", root)
    incoming = tmp_path / "returned.docx"
    package.write(incoming)
    result = receive(tmp_path, incoming)
    assert result["conflicts"] == []
    source = parse((tmp_path / "index.qmd").read_text())
    assert project_text(source.nodes, "original") == "A strong effect.\n"
    assert project_text(source.nodes, "proposed") == "A modest effect.\n"
    assert {
        item.author for item in Project.read(tmp_path).metadata.suggestions.values()
    } == {"Reviewer"}


@pytest.mark.integration
def test_return_requires_the_exact_export(tmp_path):
    package = export(tmp_path, "A claim.\n")
    identity = read_identity(package)
    assert len(identity["export"]) == 64
    with pytest.raises(ReviewError, match="differs"):
        receive(tmp_path, tmp_path / "index.docx", export_id="0" * 64)


@pytest.mark.integration
def test_header_change_does_not_silently_import(tmp_path):
    package = export(tmp_path, "A claim.\n")
    package.parts["word/header1.xml"] = (
        f'<w:hdr xmlns:w="{NS["w"]}"><w:p><w:r><w:t>New header</w:t></w:r></w:p></w:hdr>'.encode()
    )
    incoming = tmp_path / "returned.docx"
    package.write(incoming)
    before = (
        (tmp_path / "index.qmd").read_bytes(),
        (tmp_path / "review.yml").read_bytes(),
    )
    result = receive(tmp_path, incoming)
    assert result["status"] == "conflicts"
    assert any(item["id"] == "headers" for item in result["conflicts"])
    assert (
        (tmp_path / "index.qmd").read_bytes(),
        (tmp_path / "review.yml").read_bytes(),
    ) == before


@pytest.mark.integration
def test_new_thread_and_reply_merge_with_independent_local_work(tmp_path):
    source = "A {==claim==}{>>Explain this.<<}{#c1}.\n\nA second passage.\n"
    package = export(tmp_path, source)
    existing = list(read_review(package).comments)
    comments = [
        WordComment(
            "11", "Second Reviewer", "2026-01-03T09:00:00Z", "I agree.", parent_id="10"
        ),
        *existing,
        WordComment("10", "Reviewer", "2026-01-02T09:00:00Z", "Clarify this passage."),
    ]
    write_comments(package, comments)
    root = package.xml("word/document.xml")
    paragraph = root.findall(".//w:body/w:p", NS)[1]
    runs = paragraph.findall("./w:r", NS)
    start = etree.Element(tag("w", "commentRangeStart"))
    start.set(tag("w", "id"), "10")
    paragraph.insert(paragraph.index(runs[0]), start)
    end = etree.SubElement(paragraph, tag("w", "commentRangeEnd"))
    end.set(tag("w", "id"), "10")
    run = etree.SubElement(paragraph, tag("w", "r"))
    reference = etree.SubElement(run, tag("w", "commentReference"))
    reference.set(tag("w", "id"), "10")
    package.set_xml("word/document.xml", root)
    incoming = tmp_path / "returned.docx"
    package.write(incoming)
    (tmp_path / "index.qmd").write_text(
        source.replace("Explain this.", "Local clarification.")
        + "\nAn independent local addition.\n"
    )
    result = receive(tmp_path, incoming)
    assert result["status"] == "applied", result["conflicts"]
    manuscript = Project.read(tmp_path)
    assert len(manuscript.metadata.comments) == 2
    assert "Local clarification." in manuscript.documents["index.qmd"].source
    assert "An independent local addition." in manuscript.documents["index.qmd"].source
    imported = next(
        item for key, item in manuscript.metadata.comments.items() if key != "c1"
    )
    assert imported.author == "Reviewer"
    assert imported.replies[0].author == "Second Reviewer"
    assert imported.replies[0].body == "I agree."


@pytest.mark.integration
@pytest.mark.parametrize(
    "state,expected",
    [("accepted", "A modest effect.\n"), ("rejected", "A strong effect.\n")],
)
def test_returned_decision_is_applied_to_existing_source_suggestion(
    tmp_path, state, expected
):
    package = export(tmp_path, "A {~~strong~>modest~~}{#s1} effect.\n")
    root = package.xml("word/document.xml")
    for node in list(root.xpath(".//w:ins | .//w:del", namespaces=NS)):
        parent, position = node.getparent(), node.getparent().index(node)
        include = (state == "accepted") == (node.tag == tag("w", "ins"))
        parent.remove(node)
        if include:
            for child in list(node):
                for leaf in child.iter(tag("w", "delText")):
                    leaf.tag = tag("w", "t")
                parent.insert(position, child)
                position += 1
    package.set_xml("word/document.xml", root)
    incoming = tmp_path / "returned.docx"
    package.write(incoming)
    result = receive(tmp_path, incoming)
    assert result["conflicts"] == []
    manuscript = Project.read(tmp_path)
    assert manuscript.metadata.suggestions["s1"].status == state
    assert (
        project_text(manuscript.documents["index.qmd"].nodes, decisions={"s1": state})
        == expected
    )


@pytest.mark.integration
def test_untracked_word_edit_requires_author_and_becomes_a_suggestion(tmp_path):
    package = export(tmp_path, "A strong effect.\n")
    root = package.xml("word/document.xml")
    for node in root.iter(tag("w", "t")):
        node.text = node.text.replace("strong", "modest")
    package.set_xml("word/document.xml", root)
    incoming = tmp_path / "returned.docx"
    package.write(incoming)
    assert receive(tmp_path, incoming)["status"] == "conflicts"
    result = receive(tmp_path, incoming, author="Reviewer")
    assert result["conflicts"] == []
    manuscript = Project.read(tmp_path)
    assert (
        project_text(manuscript.documents["index.qmd"].nodes, "original")
        == "A strong effect.\n"
    )
    assert project_text(manuscript.documents["index.qmd"].nodes) == "A modest effect.\n"
    assert next(iter(manuscript.metadata.suggestions.values())).author == "Reviewer"


@pytest.mark.integration
def test_accepted_ordinary_edit_with_title_does_not_reappear_on_render(tmp_path):
    if not shutil.which("quarto"):
        pytest.skip("Quarto is not installed")
    original = "---\ntitle: Manuscript\nformat: docx\n---\n\nA strong effect.\n"
    (tmp_path / "index.qmd").write_text(original)
    manuscript = setup(tmp_path, author="Writer")
    enable(tmp_path)
    capture_reference(manuscript)
    (tmp_path / "index.qmd").write_text(original.replace("strong", "modest"))

    def render():
        completed = subprocess.run(
            ["quarto", "render", "index.qmd"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr
        return WordPackage.read(tmp_path / "index.docx")

    package = render()
    root = package.xml("word/document.xml")
    for node in list(root.xpath(".//w:ins | .//w:del", namespaces=NS)):
        parent, position = node.getparent(), node.getparent().index(node)
        parent.remove(node)
        if node.tag == tag("w", "ins"):
            for child in list(node):
                parent.insert(position, child)
                position += 1
    package.set_xml("word/document.xml", root)
    incoming = tmp_path / "returned.docx"
    package.write(incoming)
    result = receive(tmp_path, incoming)
    assert result["conflicts"] == []
    assert len(Project.read(tmp_path).metadata.suggestions) == 1
    assert (
        next(iter(Project.read(tmp_path).metadata.suggestions.values())).status
        == "accepted"
    )
    assert read_review(render()).revisions == ()


@pytest.mark.integration
def test_independent_reviewers_can_return_the_same_export(tmp_path):
    package = export(tmp_path, "A strong effect.\n\nA large sample.\n")
    frozen = (tmp_path / "review/reference/index.qmd").read_bytes()
    for author, before, after in (
        ("First Reviewer", "strong", "modest"),
        ("Second Reviewer", "large", "small"),
    ):
        returned = WordPackage(dict(package.parts))
        root = returned.xml("word/document.xml")
        for node in root.iter(tag("w", "t")):
            node.text = node.text.replace(before, after)
        returned.set_xml("word/document.xml", root)
        incoming = tmp_path / f"{author}.docx"
        returned.write(incoming)
        result = receive(tmp_path, incoming, author=author)
        assert result["status"] == "applied", result["conflicts"]
    manuscript = Project.read(tmp_path)
    assert (
        project_text(manuscript.documents["index.qmd"].nodes)
        == "A modest effect.\n\nA small sample.\n"
    )
    assert {item.author for item in manuscript.metadata.suggestions.values()} == {
        "First Reviewer",
        "Second Reviewer",
    }
    assert (tmp_path / "review/reference/index.qmd").read_bytes() == frozen
    assert not any(item.get("automatic") for item in manuscript.feedback())


@pytest.mark.integration
def test_renumbered_native_revisions_keep_their_source_identity(tmp_path):
    package = export(tmp_path, "A {~~strong~>modest~~}{#s1} effect.\n")
    root = package.xml("word/document.xml")
    for index, node in enumerate(root.xpath(".//w:ins | .//w:del", namespaces=NS), 100):
        node.set(tag("w", "id"), str(index))
    package.set_xml("word/document.xml", root)
    incoming = tmp_path / "renumbered.docx"
    package.write(incoming)
    result = receive(tmp_path, incoming)
    assert result["status"] == "applied", result["conflicts"]
    assert set(Project.read(tmp_path).metadata.suggestions) == {"s1"}


@pytest.mark.integration
def test_native_save_renaming_dates_and_paragraph_revisions(tmp_path):
    """Reproduce the harmless rewrites observed in a Word for Mac save."""
    source = (
        "A {=={~~large~>small~~}{#s1} effect==}{>>Explain this.<<}{#c1}.\n\n"
        "{~~Old first.\n\nOld second.~>New first.\n\nNew second.~~}{#s2}\n"
    )
    package = export(tmp_path, source)
    from quarto_review.word.identity import PART

    package.parts["customXml/item1.xml"] = package.parts.pop(PART)
    relations = package.xml("word/_rels/document.xml.rels")
    for relation in relations:
        if relation.get("Target") == "../" + PART:
            relation.set("Target", "../customXml/item1.xml")
    package.set_xml("word/_rels/document.xml.rels", relations)
    types = package.xml("[Content_Types].xml")
    for item in types:
        if item.get("PartName") == "/" + PART:
            item.set("PartName", "/customXml/item1.xml")
    package.set_xml("[Content_Types].xml", types)
    root = package.xml("word/document.xml")
    for number, node in enumerate(root.xpath(".//w:ins | .//w:del", namespaces=NS), 3):
        node.set(tag("w", "id"), str(number))
        date = datetime.fromisoformat(node.get(tag("w", "date")))
        node.set(tag("w", "date"), date.replace(second=0, microsecond=0).isoformat())
    package.set_xml("word/document.xml", root)
    incoming = tmp_path / "word-saved.docx"
    package.write(incoming)
    dates = {
        key: item.date
        for key, item in Project.read(tmp_path).metadata.suggestions.items()
    }
    result = receive(tmp_path, incoming)
    assert result["status"] == "applied", result["conflicts"]
    assert result["changes"] == []
    assert (tmp_path / "index.qmd").read_text() == source
    manuscript = Project.read(tmp_path)
    assert {
        key: item.date for key, item in manuscript.metadata.suggestions.items()
    } == dates
    assert receive(tmp_path, incoming)["duplicate"] is True


@pytest.mark.integration
def test_changed_revision_attribution_is_not_a_harmless_word_save(tmp_path):
    package = export(tmp_path, "A {~~strong~>modest~~}{#s1} effect.\n")
    root = package.xml("word/document.xml")
    root.find(".//w:ins", NS).set(tag("w", "author"), "Different Reviewer")
    package.set_xml("word/document.xml", root)
    incoming = tmp_path / "changed-author.docx"
    package.write(incoming)
    before = {
        name: (tmp_path / name).read_bytes() for name in ("index.qmd", "review.yml")
    }
    result = receive(tmp_path, incoming)
    assert result["status"] == "conflicts"
    assert any(item["kind"] == "suggestion" for item in result["conflicts"])
    assert {name: (tmp_path / name).read_bytes() for name in before} == before
