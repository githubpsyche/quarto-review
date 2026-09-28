"""Install a built wheel in isolation and render the packaged example."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]


def check(wheel: Path) -> None:
    wheel = wheel.resolve()
    with TemporaryDirectory(prefix="quarto-review-wheel-") as temporary:
        directory = Path(temporary)
        environment = directory / "venv"
        subprocess.run(
            ["uv", "venv", "--python", sys.executable, str(environment)], check=True
        )
        binary = environment / ("Scripts" if os.name == "nt" else "bin")
        python = binary / ("python.exe" if os.name == "nt" else "python")
        subprocess.run(
            ["uv", "pip", "install", "--python", str(python), str(wheel)], check=True
        )
        project = directory / "manuscript"
        shutil.copytree(
            ROOT / "examples/single-source-proposal",
            project,
            ignore=shutil.ignore_patterns(
                "_output", ".quarto", "_extensions", "_environment.local"
            ),
        )
        env = {
            key: value
            for key, value in os.environ.items()
            if key
            not in {"QUARTO_PANDOC", "QUARTO_REVIEW_PROJECT", "QUARTO_REVIEW_COMMAND"}
        }
        env["PATH"] = str(binary) + os.pathsep + env["PATH"]
        subprocess.run(
            [
                str(
                    binary
                    / ("quarto-review.exe" if os.name == "nt" else "quarto-review")
                ),
                "enable",
            ],
            cwd=project,
            env=env,
            check=True,
        )
        for target in ("html", "docx"):
            subprocess.run(
                ["quarto", "render", "index.qmd", "--to", target, "--quiet"],
                cwd=project,
                env=env,
                check=True,
            )
        script = """
import importlib.metadata, sys
from pathlib import Path
import quarto_review
from quarto_review.word.package import WordPackage
from quarto_review.word.validation import validate_package
assert Path(quarto_review.__file__).resolve().is_relative_to(Path(sys.prefix).resolve())
assert quarto_review.__version__ == importlib.metadata.version('quarto-review')
outputs = [p for p in Path('.').rglob('*.docx') if '.quarto' not in p.parts]
assert outputs
for path in outputs:
    result = validate_package(WordPackage.read(path))
    assert result['comments'] > 0
assert list(Path('.').rglob('*.html'))
print('PASS: isolated installed wheel renders HTML and Word with native review records')
"""
        subprocess.run(
            [str(python), "-I", "-c", script], cwd=project, env=env, check=True
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", type=Path)
    check(parser.parse_args().wheel)
