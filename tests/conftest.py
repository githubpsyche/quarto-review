"""Small synthetic Word packages with known review relationships."""

import pytest
from lxml import etree

from quarto_review.word.comments import write_comments
from quarto_review.word.namespaces import NS, tag
from quarto_review.word.package import WordPackage, serialize_xml
from quarto_review.word.records import WordComment


@pytest.fixture
def word_package() -> WordPackage:
    """A document containing two overlapping comments and an unanchored reply."""
    document = etree.fromstring(
        f'''<w:document xmlns:w="{NS["w"]}"><w:body>
      <w:p><w:r><w:t xml:space="preserve">An </w:t></w:r>
        <w:commentRangeStart w:id="0"/>
        <w:r><w:t>old</w:t></w:r>
        <w:commentRangeStart w:id="2"/>
        <w:del w:id="3" w:author="A. Reviewer" w:date="2026-01-02T09:00:00Z"><w:r><w:delText xml:space="preserve"> strong</w:delText></w:r></w:del>
        <w:ins w:id="4" w:author="A. Reviewer" w:date="2026-01-02T09:00:00Z"><w:r><w:t xml:space="preserve"> modest</w:t></w:r></w:ins>
        <w:commentRangeEnd w:id="0"/><w:r><w:commentReference w:id="0"/></w:r>
        <w:r><w:t xml:space="preserve"> claim</w:t></w:r>
        <w:commentRangeEnd w:id="2"/><w:r><w:commentReference w:id="2"/></w:r>
        <w:r><w:t>.</w:t></w:r>
      </w:p>
      <w:p><w:r><w:t>Second paragraph.</w:t></w:r></w:p>
      <w:sectPr/>
    </w:body></w:document>'''.encode()
    )
    types = etree.fromstring(
        f'''<Types xmlns="{NS["ct"]}">
      <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
      <Default Extension="xml" ContentType="application/xml"/>
      <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
    </Types>'''.encode()
    )
    relationships = etree.Element(tag("pr", "Relationships"), nsmap={None: NS["pr"]})
    etree.SubElement(
        relationships,
        tag("pr", "Relationship"),
        Id="rId1",
        Type=f"{NS['r']}/officeDocument",
        Target="word/document.xml",
    )
    package = WordPackage(
        {
            "word/document.xml": serialize_xml(document),
            "[Content_Types].xml": serialize_xml(types),
            "_rels/.rels": serialize_xml(relationships),
            "word/media/retained.bin": b"An unrelated part must remain unchanged.",
        }
    )
    write_comments(
        package,
        [
            WordComment(
                "0",
                "A. Reviewer",
                "2026-01-02T09:00:00Z",
                "Clarify the claim.\nExplain the evidence.",
                initials="AR",
            ),
            WordComment(
                "1",
                "B. Author",
                "2026-01-03T10:00:00Z",
                "I have revised the wording.",
                parent_id="0",
            ),
            WordComment(
                "2",
                "C. Reviewer",
                "2026-01-04T11:00:00Z",
                "Check this wording.",
                resolved=True,
            ),
        ],
    )
    return package
