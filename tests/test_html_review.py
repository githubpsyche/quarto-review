"""Review cards expose settled changes without restoring them to prose."""

from pathlib import Path

import pytest
from lxml import html

from quarto_review.html import review_panel
from quarto_review.markers import marker
from quarto_review.rendering import prepare_render
from quarto_review.source import read

FIXTURE = Path(__file__).parent / "fixtures/review-panel.qmd"


@pytest.mark.integration
def test_change_cards_keep_alternatives_and_decisions_separate_from_prose():
    model = read(FIXTURE.read_text(), "index.qmd")
    prepared = prepare_render(model.document, model.metadata, native_objects=False)
    assert "This note is for the tutorial only." not in prepared.markdown
    assert "an unnecessary qualification" not in prepared.markdown
    assert "retained phrase" in prepared.markdown
    assert marker("O", "deleted_note", "S") in prepared.markdown
    panel = html.fromstring(review_panel(prepared))
    note = panel.get_element_by_id("qr-suggestion-deleted_note")
    assert note.get("data-status") == "accepted"
    assert note.get("data-kind") == "suggestion"
    assert "Accepted deletion" in note.xpath("./header")[0].text_content()
    assert "Example Author" in note.xpath("./header")[0].text_content()
    assert note.xpath("./time/@datetime") == ["2026-01-03T10:00:00Z"]
    assert note.xpath('.//*[@class="qr-change-before"]//h2')[0].text == "Draft note"
    assert "This note is for the tutorial only." in note.text_content()
    assert not note.xpath('.//*[@class="qr-change-after"]')
    replacement = panel.get_element_by_id("qr-suggestion-pending_word")
    assert replacement.xpath('.//*[@class="qr-change-before"]//p')[0].text == "strong"
    assert replacement.xpath('.//*[@class="qr-change-after"]//p')[0].text == "modest"
    rejected = panel.get_element_by_id("qr-suggestion-rejected_insertion")
    assert "Rejected insertion" in rejected.text_content()
    assert "an unnecessary qualification" in rejected.text_content()
    assert panel.xpath('//*[@id="qr-kind"]/option/@value') == ["", "comment", "suggestion"]
    assert panel.xpath('//*[@id="qr-status"]/option/@value') == ["open-pending", "resolved-decided", ""]


@pytest.mark.integration
def test_change_card_markdown_is_sanitized_and_does_not_execute_html():
    model = read(FIXTURE.read_text().replace(
        "This note is for the tutorial only.",
        '<script>evil()</script>\n\n![tracking](https://example.org/pixel.png)'
        '\n\n[bad](javascript:alert%281%29)',
    ), "index.qmd")
    panel = html.fromstring(review_panel(prepare_render(
        model.document, model.metadata, native_objects=False,
    )))
    note = panel.get_element_by_id("qr-suggestion-deleted_note")
    assert not note.xpath(".//script|.//img|.//iframe")
    assert "<script>evil()</script>" in note.text_content()
    assert "tracking" in note.text_content()
    assert not note.xpath('.//a[starts-with(@href,"javascript:")]')


@pytest.mark.integration
def test_native_formatting_revision_is_described_without_invented_text():
    text = FIXTURE.read_text().replace(
        "A surviving paragraph before the removed section.",
        '[]{#f1-start}Formatted text[]{#f1-end}{~~~>~~}{#f1 by=R}'
        '<!-- review-data: {"provenance":{"kind":"rPrChange"}} -->',
    )
    model = read(text, "index.qmd")
    panel = html.fromstring(review_panel(prepare_render(
        model.document, model.metadata, native_objects=False,
    )))
    card = panel.get_element_by_id("qr-suggestion-f1")
    assert "Pending native Word change" in card.text_content()
    assert "no separate text alternatives" in card.text_content()
    assert not card.xpath('.//*[@class="qr-change-before" or @class="qr-change-after"]')


@pytest.mark.integration
def test_nested_suggestion_keeps_an_inspectable_anchor_after_parent_deletion():
    text = FIXTURE.read_text().replace(
        "This note is for the tutorial only.",
        "A {~~superseded~>revised~~}{#nested by=R} note.",
    )
    model = read(text, "index.qmd")
    prepared = prepare_render(model.document, model.metadata, native_objects=False)
    assert marker("O", "nested", "S") in prepared.markdown
    assert "superseded" not in prepared.markdown
    panel = html.fromstring(review_panel(prepared))
    card = panel.get_element_by_id("qr-suggestion-nested")
    assert "superseded" in card.text_content() and "revised" in card.text_content()
    word = prepare_render(model.document, model.metadata, native_objects=True)
    assert marker("O", "nested", "S") not in word.markdown


@pytest.mark.parametrize("parent_state", ["pending", "accepted", "rejected"])
@pytest.mark.parametrize("child_state", ["pending", "accepted", "rejected"])
@pytest.mark.parametrize("side", ["before", "after"])
def test_parent_card_respects_decisions_within_each_alternative(
    parent_state, child_state, side,
):
    def attrs(identifier, state):
        decision = "" if state == "pending" else f" .{state}"
        return "{#" + identifier + decision + " by=A}"

    child = "A {~~small~>large~~}" + attrs("inner", child_state) + " effect."
    before, after = (child, "A revised claim.") if side == "before" else ("An old claim.", child)
    header = FIXTURE.read_text().split("# Opening")[0]
    model = read(header + "{~~" + before + "~>" + after + "~~}" + attrs("outer", parent_state), "index.qmd")
    prepared = prepare_render(model.document, model.metadata, native_objects=False)
    projected_child = "A " + ("large" if child_state == "accepted" or child_state == "pending" and side == "after" else "small") + " effect."
    expected = (projected_child, after) if side == "before" else (before, projected_child)
    assert prepared.suggestions["outer"] == expected
    # Each child's own alternatives remain inspectable after its decision.
    assert prepared.suggestions["inner"] == ("small", "large")
    # For settled children the parent card agrees with the retained manuscript
    # branch in both views, including rejected parents that retain their before.
    if child_state != "pending":
        for view in ("original", "proposed"):
            use_after = parent_state == "accepted" or parent_state == "pending" and view == "proposed"
            clean = prepare_render(model.document, model.metadata, view=view).markdown.strip()
            assert clean == (header + expected[int(use_after)]).strip()
