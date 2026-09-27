"""Run the project-local review command after Quarto finishes its outputs."""

import os
import subprocess
import sys

command = os.environ.get("QUARTO_REVIEW_COMMAND")
directory = os.environ.get("QUARTO_REVIEW_PROJECT")
if not command or not directory:
    sys.exit("Enable quarto-review in this project before running its render hook")
sys.exit(subprocess.call([command, "finish", "--project", directory]))
