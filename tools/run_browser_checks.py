"""Run the synthetic browser checks with the locked Playwright CLI."""

from __future__ import annotations

import functools
import json
import subprocess
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ("panel", "authors", "status", "list")


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def run() -> None:
    cli = ROOT / "node_modules/@playwright/cli/playwright-cli.js"
    if not cli.is_file():
        raise SystemExit("Run npm ci and npx playwright install chromium first.")
    for fixture in FIXTURES:
        subprocess.run(
            [
                sys.executable,
                "tools/build_review_panel_fixture.py",
                "--source",
                f"tests/fixtures/review-{fixture}.qmd",
                "--output",
                f"work/browser-checks/{fixture}",
            ],
            cwd=ROOT,
            check=True,
        )
    handler = functools.partial(QuietHandler, directory=str(ROOT))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_port}"
    with TemporaryDirectory(prefix="runner-", dir=ROOT / "work/browser-checks") as temp:
        directory = Path(temp)
        session = directory.name
        config = directory / "browser.json"
        config.write_text(
            json.dumps(
                {
                    "browser": {
                        "browserName": "chromium",
                        "launchOptions": {"channel": "chromium", "headless": True},
                    }
                }
            )
        )

        def command(*args):
            result = subprocess.run(
                ["node", str(cli), f"-s={session}", *args],
                cwd=directory,
                capture_output=True,
                text=True,
            )
            if result.returncode or "### Error" in result.stdout:
                raise RuntimeError(result.stdout + result.stderr)
            return result.stdout

        checks = [
            (name, f"/work/browser-checks/{name}/_output/index.html")
            for name in FIXTURES
        ]
        checks += [
            (name, f"/tests/fixtures/review-{name}.html")
            for name in ("markers", "media")
        ]
        try:
            command("open", origin + checks[0][1], "--config", str(config))
            for name, path in checks:
                command("goto", origin + path)
                script = directory / "check.js"
                source = (ROOT / f"tools/check_review_{name}.js").read_text()
                script.write_text(
                    "async (page) => { await ("
                    + source
                    + ")(page); return 'QUARTO_REVIEW_BROWSER_PASS'; }"
                )
                result = command("run-code", "--filename", str(script))
                if '### Result\n"QUARTO_REVIEW_BROWSER_PASS"' not in result:
                    raise RuntimeError(result)
                print(f"PASS: {name}", flush=True)
        finally:
            try:
                command("close")
            finally:
                server.shutdown()
                server.server_close()
                thread.join()


if __name__ == "__main__":
    run()
