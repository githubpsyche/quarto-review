"""Temporary text markers that carry review boundaries through conversion."""

import re

from quarto_review.errors import ReviewError

PATTERN = re.compile(r"QRX([CIDFO])Q([0-9A-F]+)Q([SE])XQR")


def marker(kind: str, identifier: str, edge: str) -> str:
    """Encode a boundary without Markdown punctuation or significant spacing."""
    if kind not in {"C", "I", "D", "F", "O"} or edge not in {"S", "E"}:
        raise ValueError("Unknown review boundary type")
    return f"QRX{kind}Q{identifier.encode().hex().upper()}Q{edge}XQR"


def decode(match: re.Match[str]) -> tuple[str, str, str]:
    """Decode one boundary, rejecting corrupted identifiers."""
    try:
        return match[1], bytes.fromhex(match[2]).decode(), match[3]
    except (ValueError, UnicodeDecodeError) as error:
        raise ReviewError(f"Invalid review boundary {match[0]}") from error


def source_boundary(identifier: str, edge: str) -> str:
    """Represent a crossing range in QMD without duplicating its comment body."""
    return (
        f'[]{{.review-{"start" if edge == "S" else "end"} data-review="{identifier}"}}'
    )
