"""Launch Quarto's Pandoc with review preparation before Markdown parsing."""

from __future__ import annotations

import json
import os
import platform
import re
import shlex
import shutil
import sys
from pathlib import Path

import yaml

from quarto_review.errors import ReviewError

__all__ = ["configure", "main"]


def _real_pandoc(configured: str | None = None) -> Path:
    """Find Quarto's bundled executable without changing the Quarto installation."""
    configured = configured or os.environ.get("QUARTO_PANDOC")
    if configured:
        candidate = Path(configured)
        if candidate.is_dir():
            candidate /= "pandoc.exe" if os.name == "nt" else "pandoc"
        if candidate.is_file() and "quarto-review" not in candidate.name:
            return candidate.resolve()
        if "quarto-review" not in candidate.name:
            raise ReviewError(
                f"The configured QUARTO_PANDOC executable is unavailable: {configured}"
            )
    quarto = shutil.which("quarto")
    if quarto:
        binary = Path(quarto).resolve().parent
        architecture = {"arm64": "aarch64", "AMD64": "x86_64"}.get(
            platform.machine(), platform.machine()
        )
        executable = "pandoc.exe" if os.name == "nt" else "pandoc"
        for candidate in (
            binary / "tools" / architecture / executable,
            binary / "tools" / executable,
        ):
            if candidate.is_file():
                return candidate
    installed = shutil.which("pandoc")
    if installed:
        return Path(installed).resolve()
    raise ReviewError(
        "Cannot locate Pandoc; install Quarto or set QUARTO_PANDOC before enabling review"
    )


def configure(directory: Path) -> None:
    """Write project-local launcher settings while preserving other environment keys."""
    from quarto_review.project import write_text

    name = "quarto-review-pandoc.exe" if os.name == "nt" else "quarto-review-pandoc"
    driver = Path(sys.executable).parent / name
    if not driver.is_file():
        located = shutil.which(name)
        if not located:
            raise ReviewError("Reinstall quarto-review to enable its Pandoc launcher")
        driver = Path(located)
    environment = directory / "_environment.local"
    text = environment.read_text() if environment.exists() else ""
    configured = re.findall(r"(?m)^(?:export\s+)?QUARTO_PANDOC\s*=(.*)$", text)
    if len(configured) > 1:
        raise ReviewError(
            "_environment.local contains multiple QUARTO_PANDOC definitions"
        )
    configured_value = shlex.split(configured[0], comments=True) if configured else []
    if len(configured_value) > 1:
        raise ReviewError("Quote the QUARTO_PANDOC path in _environment.local")
    configured_path = configured_value[0] if configured_value else None
    runtime = directory / ".quarto/review/runtime.json"
    previous = json.loads(runtime.read_text()) if runtime.exists() else {}
    if configured_path and Path(configured_path).resolve() != driver.resolve():
        real = _real_pandoc(configured_path)
    else:
        real = Path(previous["pandoc"]) if previous.get("pandoc") else _real_pandoc()
    if not real.is_file() or real.resolve() == driver.resolve():
        raise ReviewError(
            "The recorded Pandoc executable is missing or points to the review launcher; enable review again with QUARTO_PANDOC set to the real executable"
        )
    values = {
        "QUARTO_PANDOC": str(driver.resolve()),
        "QUARTO_REVIEW_PROJECT": str(directory.resolve()),
        "QUARTO_REVIEW_COMMAND": str(
            driver.with_name(
                "quarto-review.exe" if os.name == "nt" else "quarto-review"
            ).resolve()
        ),
    }
    for key, value in values.items():
        pattern = re.compile(r"(?m)^(?:export\s+)?" + re.escape(key) + r"\s*=.*$")
        matches = list(pattern.finditer(text))
        if len(matches) > 1:
            raise ReviewError(
                f"_environment.local contains multiple {key} definitions; keep one before enabling review"
            )
        setting = key + "=" + json.dumps(value)
        if matches:
            text = text[: matches[0].start()] + setting + text[matches[0].end() :]
        else:
            text = text.rstrip("\n") + ("\n" if text else "") + setting + "\n"
    write_text(
        runtime,
        json.dumps(
            {
                "pandoc": str(real),
                "reader": str(directory / "_extensions/quarto-review/reader.lua"),
            },
            indent=2,
        )
        + "\n",
    )
    write_text(environment, text)
    ignored = directory / ".gitignore"
    rules = ignored.read_text() if ignored.exists() else ""
    additions = [
        rule
        for rule in ("/_environment.local", "/.quarto/")
        if rule not in rules.splitlines()
    ]
    if additions:
        write_text(
            ignored,
            rules.rstrip("\n") + ("\n" if rules else "") + "\n".join(additions) + "\n",
        )


def main(argv: list[str] | None = None) -> int:
    """Forward Pandoc arguments, replacing only Quarto's initial QMD reader."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    try:
        project = os.environ.get("QUARTO_REVIEW_PROJECT")
        if not project:
            raise ReviewError(
                "The project location is missing from the review launcher's environment"
            )
        runtime = json.loads(
            (Path(project) / ".quarto/review/runtime.json").read_text()
        )
        real = Path(runtime["pandoc"])
        if not real.is_file():
            raise ReviewError(
                "The configured Pandoc executable is unavailable; run quarto-review enable again"
            )
        defaults = []
        for index, argument in enumerate(arguments):
            if argument in {"--defaults", "-d"} and index + 1 < len(arguments):
                defaults.append(arguments[index + 1])
            elif argument.startswith("--defaults="):
                defaults.append(argument.split("=", 1)[1])
        for filename in defaults:
            data = yaml.safe_load(Path(filename).read_text())
            reader = data.get("from", "") if isinstance(data, dict) else ""
            if str(reader).replace("\\", "/").endswith("/qmd-reader.lua"):
                arguments.extend(["--from", runtime["reader"]])
                break
        os.execv(str(real), [str(real), *arguments])
    except (OSError, ValueError, ReviewError, yaml.YAMLError, KeyError) as error:
        print(f"quarto-review-pandoc: {error}", file=sys.stderr)
        return 1
    return 0
