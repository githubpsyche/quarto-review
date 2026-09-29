"""Run the project-local review command after Quarto finishes its outputs."""

import os
import subprocess
import sys
from pathlib import Path

command = os.environ.get("QUARTO_REVIEW_COMMAND")
directory = os.environ.get("QUARTO_REVIEW_PROJECT")
if not command or not directory:
    sys.exit("Enable quarto-review in this project before running its render hook")
# Use the pinned command's interpreter and dependencies, without reinstalling it.
interpreter = Path(command).resolve().parent / (
    "python.exe" if os.name == "nt" else "python"
)
subprocess.run(
    [str(interpreter), str(Path(__file__).with_name("word_options.py"))], check=True
)
sys.exit(subprocess.call([command, "finish", "--project", directory]))
