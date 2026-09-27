"""Review records read independently of a document converter."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class WordAnchor:
    """A range in a story's text, including text proposed for deletion."""

    story: str
    start: int
    end: int
    text: str


@dataclass(frozen=True)
class WordComment:
    """One comment or reply with its native identifiers and original XML."""

    id: str
    author: str | None
    date: str | None
    text: str
    parent_id: str | None = None
    resolved: bool = False
    initials: str | None = None
    paragraph_id: str | None = None
    durable_id: str | None = None
    date_utc: str | None = None
    anchors: tuple[WordAnchor, ...] = ()
    xml: str | None = field(default=None, repr=False)


@dataclass(frozen=True)
class WordRevision:
    """A text, move, or property revision at its original location."""

    id: str
    kind: str
    story: str
    path: str
    author: str | None
    date: str | None
    text: str
    start: int
    end: int
    xml: str = field(repr=False)


@dataclass(frozen=True)
class WordReview:
    """Complete extracted comment records and recognized revision elements."""

    comments: tuple[WordComment, ...]
    revisions: tuple[WordRevision, ...]
    stories: dict[str, str]
