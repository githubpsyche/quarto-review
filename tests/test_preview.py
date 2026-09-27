"""Live previews must refresh comments, decisions, and a newly frozen reference."""

import os
import shutil
import signal
import socket
import subprocess
import time
from urllib.error import URLError
from urllib.request import urlopen

import pytest
from websockets.sync.client import connect

from quarto_review.preview import PREVIEW_SIGNAL, configure, invalidate
from quarto_review.project import Project, capture_reference, setup
from quarto_review.quarto import enable


@pytest.mark.integration
@pytest.mark.parametrize("file_preview", [False, True], ids=["project", "file"])
def test_preview_refreshes_review_metadata_and_reference(tmp_path, file_preview):
    if not shutil.which("quarto"):
        pytest.skip("Quarto is not installed")
    source = "---\ntitle: Live review\nauthor: Manuscript Author\nformat: html\n---\n\nA clear finding.\n\nA {==claim==}{>>Explain this.<<}{#c1}.\n"
    (tmp_path / "index.qmd").write_text(source)
    (tmp_path / "_quarto.yml").write_text(
        "project:\n  type: default\n  output-dir: _output\n"
    )
    manuscript = setup(tmp_path, author="Reviewer")
    enable(tmp_path)
    capture_reference(manuscript)
    with socket.socket() as socket_probe:
        socket_probe.bind(("127.0.0.1", 0))
        port = socket_probe.getsockname()[1]
    arguments = ["quarto", "preview"]
    if file_preview:
        arguments.append("index.qmd")
    arguments.extend(["--to", "html", "--port", str(port), "--no-browser"])
    log = tmp_path / "preview.log"
    with log.open("w") as output:
        process = subprocess.Popen(
            arguments,
            cwd=tmp_path,
            stdout=output,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )

    def await_page(predicate):
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            assert process.poll() is None, log.read_text()
            try:
                with urlopen(
                    f"http://127.0.0.1:{port}/index.html", timeout=5
                ) as response:
                    page = response.read().decode()
                if predicate(page):
                    return page
            except (OSError, URLError):
                pass
            time.sleep(0.1)
        pytest.fail("The preview did not refresh:\n" + log.read_text()[-8000:])

    def refresh(action, predicate):
        # Follow Quarto's actual browser protocol: wait for its reload message
        # before requesting the page. Polling GET during rendering creates a
        # second, competing render in Quarto's project preview.
        with connect(f"ws://127.0.0.1:{port}/", proxy=None, close_timeout=1) as client:
            action()
            deadline = time.monotonic() + 25
            while True:
                message = client.recv(timeout=max(0, deadline - time.monotonic()))
                if message.startswith("reload"):
                    break
        with urlopen(f"http://127.0.0.1:{port}/index.html", timeout=25) as response:
            page = response.read().decode()
        assert predicate(page), (
            "The reloaded page has stale review state:\n" + log.read_text()[-8000:]
        )

    try:
        page = await_page(lambda page: "Explain this." in page)
        assert "Manuscript Author" in page
        original_reference = (tmp_path / "review/reference/manifest.json").read_bytes()
        refresh(
            lambda: Project.read(tmp_path).reply(
                "c1", "A reply added while preview is running."
            ),
            lambda page: "A reply added while preview is running." in page,
        )
        refresh(
            lambda: Project.read(tmp_path).decide("c1", "resolve"),
            lambda page: 'data-status="resolved"' in page,
        )
        assert (
            tmp_path / "review/reference/manifest.json"
        ).read_bytes() == original_reference
        assert not (tmp_path / "_output/review.yml").exists()
        refresh(
            lambda: (tmp_path / "index.qmd").write_text(
                source.replace("clear", "modest")
            ),
            lambda page: 'data-review-kind="I"' in page,
        )
        refresh(
            lambda: capture_reference(Project.read(tmp_path), new_round=True),
            lambda page: "modest" in page and 'data-review-kind="I"' not in page,
        )
        if file_preview:
            metadata = tmp_path / "review.yml"
            refresh(
                lambda: metadata.write_text(
                    metadata.read_text().replace(
                        "A reply added while preview is running.",
                        "A reply edited directly in YAML.",
                    )
                ),
                lambda page: "A reply edited directly in YAML." in page,
            )
        assert "ERROR:" not in log.read_text()
    finally:
        if process.poll() is None:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGTERM)
            else:
                process.terminate()
            process.wait(timeout=10)


def test_preview_invalidation_preserves_edited_outputs_and_authoring(tmp_path):
    source = tmp_path / "index.qmd"
    source.write_text("A {==claim==}{>>Explain.<<}{#c1}.")
    manuscript = setup(tmp_path, author="Reviewer")
    (tmp_path / "_extensions/quarto-review").mkdir(parents=True)
    configure(tmp_path)
    capture_reference(manuscript)
    reference = (tmp_path / "review/reference/review.yml").read_bytes()
    output = tmp_path / "index.html"
    output.write_text("<p>A claim.</p>")
    edited = "<p>An independently edited output.</p>"
    output.write_text(edited)
    manuscript.reply("c1", "Explanation.")
    assert output.read_text() == edited
    assert source.read_text() == "A {==claim==}{>>Explain.<<}{#c1}."
    assert (tmp_path / "review/reference/review.yml").read_bytes() == reference


def test_failed_preview_notification_does_not_fail_a_saved_reply(
    tmp_path, capsys, monkeypatch
):
    (tmp_path / "index.qmd").write_text("A {==claim==}{>>Explain.<<}{#c1}.")
    manuscript = setup(tmp_path, author="Reviewer")
    extension = tmp_path / "_extensions/quarto-review"
    extension.mkdir(parents=True)
    configure(tmp_path)

    def unavailable(*args):
        raise OSError("read-only generated signal")

    monkeypatch.setattr("quarto_review.preview.os.utime", unavailable)
    identifier = manuscript.reply("c1", "Explanation.")
    assert Project.read(tmp_path).metadata.comments["c1"].replies[0].id == identifier
    assert (
        "review state was saved but preview could not be notified"
        in capsys.readouterr().err
    )


def test_rapid_preview_updates_have_distinct_second_resolution(tmp_path):
    extension = tmp_path / "_extensions/quarto-review"
    extension.mkdir(parents=True)
    configure(tmp_path)
    signal = extension / PREVIEW_SIGNAL
    modified = int(signal.stat().st_mtime)
    for _ in range(3):
        invalidate(tmp_path)
        current = int(signal.stat().st_mtime)
        assert current > modified
        modified = current
