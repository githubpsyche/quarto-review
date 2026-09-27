"""Read and write Word review records without opening Word."""

from quarto_review.word.package import WordPackage
from quarto_review.word.reader import read_review

__all__ = ["WordPackage", "read_review"]
