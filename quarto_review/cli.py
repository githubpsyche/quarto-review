"""Commands for inspecting source and native Word review information."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from quarto_review.errors import ReviewError
from quarto_review.markup import Change, Comment, parse, walk
from quarto_review.markup import project as project_text
from quarto_review.word import WordPackage, read_review


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Review Quarto manuscripts and Word feedback."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser(
        "inspect", help="Read native Word comments and revisions as JSON."
    )
    inspect.add_argument("document", type=Path)
    inspect.add_argument(
        "--include-xml",
        action="store_true",
        help="Include original XML in each record.",
    )
    imported = commands.add_parser(
        "import-docx", help="Create a new QMD project from a reviewed Word file."
    )
    imported.add_argument("document", type=Path)
    imported.add_argument("--into", type=Path, required=True)
    imported.add_argument("--author", required=True)
    imported.add_argument("--legacy", action="store_true")
    imported.add_argument(
        "--bibliography",
        type=Path,
        help="Recover explicit citation links using this bibliography.",
    )
    citations = commands.add_parser(
        "normalize-citations",
        help="Recover native Quarto citation syntax without changing review decisions.",
    )
    citations.add_argument("--project", type=Path, default=Path.cwd())
    citations.add_argument("--bibliography", type=Path, required=True)
    citations.add_argument(
        "--apply",
        action="store_true",
        help="Update source and reference; otherwise report a dry run.",
    )
    source = commands.add_parser(
        "parse", help="Read CriticMarkup without changing a source file."
    )
    source.add_argument("document", type=Path)
    source.add_argument(
        "--view", choices=["original", "proposed", "review"], default="review"
    )
    initialized = commands.add_parser(
        "init", help="Register QMD annotations and enable Quarto review."
    )
    initialized.add_argument("--project", type=Path, default=Path.cwd())
    initialized.add_argument("--author", required=True)
    initialized.add_argument(
        "--legacy", action="store_true", help="Create the previous QMD/YAML format."
    )
    initialized.add_argument("--source", action="append", default=[])
    initialized.add_argument("--include", action="append", default=[])
    initialized.add_argument(
        "--execute",
        action="store_true",
        help="Execute the document before freezing its reference.",
    )
    initialized.add_argument(
        "--to",
        action="append",
        default=[],
        help="Format to execute; repeat for multiple formats.",
    )
    enabled = commands.add_parser(
        "enable", help="Enable rendering for an existing review project."
    )
    enabled.add_argument("--project", type=Path, default=Path.cwd())
    reference = commands.add_parser(
        "reference", help="Freeze the current source and metadata."
    )
    reference.add_argument("--project", type=Path, default=Path.cwd())
    reference.add_argument("--new-round", action="store_true")
    reference.add_argument("--include", action="append", default=[])
    reference.add_argument("--execute", action="store_true")
    reference.add_argument("--to", action="append", default=[])
    feedback = commands.add_parser(
        "feedback", help="List review threads and suggestions as JSON."
    )
    feedback.add_argument("--project", type=Path, default=Path.cwd())
    feedback.add_argument("--id", dest="identifier")
    feedback.add_argument(
        "--status", choices=["open", "resolved", "pending", "accepted", "rejected"]
    )
    feedback.add_argument("--author")
    reply = commands.add_parser("reply", help="Append an attributed reply.")
    reply.add_argument("identifier")
    reply.add_argument("--project", type=Path, default=Path.cwd())
    reply.add_argument("--body", required=True)
    reply.add_argument("--author")
    for action in (
        "resolve",
        "reopen",
        "accept",
        "reject",
        "pending",
        "delete-comment",
    ):
        decision = commands.add_parser(
            action, help=f"{action.capitalize()} a review item."
        )
        decision.add_argument("identifier")
        decision.add_argument("--project", type=Path, default=Path.cwd())
    prepared = commands.add_parser(
        "prepare", help="Prepare Quarto's executed Markdown from stdin."
    )
    prepared.add_argument("--project", type=Path, required=True)
    prepared.add_argument("--source", required=True)
    prepared.add_argument("--output", required=True)
    prepared.add_argument("--format", choices=["docx", "html", "clean"], required=True)
    finished = commands.add_parser(
        "finish", help="Finish Word files created by a Quarto render."
    )
    finished.add_argument("--project", type=Path, default=Path.cwd())
    finished.add_argument("--output", action="append")
    synchronized = commands.add_parser(
        "sync", help="Register new typed CriticMarkup annotations."
    )
    synchronized.add_argument("--project", type=Path, default=Path.cwd())
    synchronized.add_argument("--author")
    returned = commands.add_parser(
        "receive", help="Reconcile a returned Word file with its retained export."
    )
    returned.add_argument("document", type=Path)
    returned.add_argument("--project", type=Path, default=Path.cwd())
    returned.add_argument("--export", dest="export_id")
    returned.add_argument("--author")
    validated = commands.add_parser(
        "validate", help="Check source records or a Word package."
    )
    validated.add_argument("--project", type=Path, default=Path.cwd())
    validated.add_argument("--docx", type=Path)
    for name in ("comment", "suggest", "group"):
        annotation = commands.add_parser(
            name, help="Add a comment, propose wording, or group an existing edit."
        )
        annotation.add_argument("--project", type=Path, default=Path.cwd())
        annotation.add_argument("--source", default="index.qmd")
        annotation.add_argument("--text", required=True)
        annotation.add_argument("--start", type=int)
        annotation.add_argument("--author")
        annotation.add_argument(
            {"comment": "--body", "suggest": "--replacement", "group": "--before"}[
                name
            ],
            required=True,
        )
    migrated = commands.add_parser(
        "migrate",
        help="Create verified single-source candidates; never switch the live project.",
    )
    migrated.add_argument("--project", type=Path, default=Path.cwd())
    migrated.add_argument("--into", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run one operation, writing machine-readable review records to stdout."""
    arguments = _parser().parse_args(argv)
    try:
        if arguments.command == "migrate":
            from quarto_review.migration import migrate

            print(json.dumps(migrate(arguments.project, arguments.into), indent=2))
            return 0
        if arguments.command == "receive":
            from quarto_review.returns import receive

            result = receive(
                arguments.project,
                arguments.document,
                export_id=arguments.export_id,
                author=arguments.author,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 2 if result["conflicts"] else 0
        elif arguments.command in {"sync", "validate", "comment", "suggest", "group"}:
            from quarto_review.authoring import annotate, synchronize
            from quarto_review.project import Project
            from quarto_review.word.validation import validate_package

            if arguments.command == "sync":
                result = synchronize(arguments.project, author=arguments.author)
            elif arguments.command == "validate" and arguments.docx:
                result = validate_package(WordPackage.read(arguments.docx))
            else:
                manuscript = Project.read(arguments.project)
                if arguments.command == "validate":
                    result = {
                        "sources": list(manuscript.documents),
                        "items": len(manuscript.feedback()),
                    }
                else:
                    result = {
                        "id": annotate(
                            manuscript,
                            arguments.source,
                            arguments.text,
                            body=getattr(arguments, "body", None),
                            replacement=getattr(arguments, "replacement", None),
                            before=getattr(arguments, "before", None),
                            start=arguments.start,
                            author=arguments.author,
                        )
                    }
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif arguments.command in {
            "init",
            "enable",
            "reference",
            "feedback",
            "reply",
            "resolve",
            "reopen",
            "accept",
            "reject",
            "pending",
            "delete-comment",
            "prepare",
            "finish",
        }:
            from quarto_review.project import Project, capture_reference, setup
            from quarto_review.quarto import enable, finish_outputs, prepare

            if arguments.command == "init":
                project = setup(
                    arguments.project,
                    author=arguments.author,
                    sources=tuple(arguments.source) or ("index.qmd",),
                    single_source=not arguments.legacy,
                )
                enable(arguments.project)
                result = {
                    "project": str(project.directory),
                    "reference": capture_reference(
                        project,
                        execute=arguments.execute,
                        formats=tuple(arguments.to),
                        include=tuple(arguments.include),
                    )["id"],
                }
            elif arguments.command == "enable":
                enable(arguments.project)
                result = {"project": str(arguments.project.resolve()), "enabled": True}
            elif arguments.command == "reference":
                result = capture_reference(
                    Project.read(arguments.project),
                    new_round=arguments.new_round,
                    include=tuple(arguments.include),
                    execute=arguments.execute,
                    formats=tuple(arguments.to),
                )
            elif arguments.command == "prepare":
                result = prepare(
                    arguments.project,
                    sys.stdin.read(),
                    path=arguments.source,
                    output=arguments.output,
                    format=arguments.format,
                )
            elif arguments.command == "finish":
                result = {
                    "finished": finish_outputs(
                        arguments.project,
                        tuple(arguments.output) if arguments.output else None,
                    )
                }
            else:
                project = Project.read(
                    arguments.project, validate_decisions=arguments.command != "pending"
                )
                if arguments.command == "feedback":
                    result = project.feedback()
                    if arguments.identifier:
                        result = [
                            item
                            for item in result
                            if item["id"] == arguments.identifier
                            or any(
                                reply["id"] == arguments.identifier
                                for reply in item.get("replies", [])
                            )
                        ]
                    if arguments.status:
                        result = [
                            item
                            for item in result
                            if item.get("status") == arguments.status
                        ]
                    if arguments.author:
                        result = [
                            item
                            for item in result
                            if item.get("author") == arguments.author
                            or any(
                                reply["author"] == arguments.author
                                for reply in item.get("replies", [])
                            )
                        ]
                elif arguments.command == "reply":
                    result = {
                        "id": project.reply(
                            arguments.identifier,
                            arguments.body,
                            author=arguments.author,
                        )
                    }
                elif arguments.command == "delete-comment":
                    project.delete_comment(arguments.identifier)
                    result = {"id": arguments.identifier, "action": arguments.command}
                else:
                    project.decide(arguments.identifier, arguments.command)
                    result = {"id": arguments.identifier, "action": arguments.command}
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif arguments.command == "inspect":
            review = read_review(WordPackage.read(arguments.document))
            result = asdict(review)
            if not arguments.include_xml:
                for record in [*result["comments"], *result["revisions"]]:
                    record.pop("xml", None)
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif arguments.command == "normalize-citations":
            from quarto_review.citations import normalize_project

            print(
                json.dumps(
                    normalize_project(
                        arguments.project, arguments.bibliography, apply=arguments.apply
                    ),
                    ensure_ascii=False,
                    indent=2,
                )
            )
        elif arguments.command == "import-docx":
            from quarto_review.word.importer import import_document

            metadata = import_document(
                arguments.document,
                arguments.into,
                author=arguments.author,
                single_source=not arguments.legacy,
                bibliography=arguments.bibliography,
            )
            print(
                json.dumps(
                    {
                        "project": str(arguments.into.resolve()),
                        **(
                            {
                                "citations": json.loads(
                                    (
                                        arguments.into
                                        / ".quarto/review/citation-import.json"
                                    ).read_text()
                                )
                            }
                            if arguments.bibliography
                            else {}
                        ),
                        "comments": len(metadata.comments),
                        "replies": sum(
                            len(item.replies) for item in metadata.comments.values()
                        ),
                        "suggestions": len(metadata.suggestions),
                    },
                    indent=2,
                )
            )
        elif arguments.command == "parse":
            from quarto_review.source import is_single, read

            text = arguments.document.read_text(encoding="utf-8")
            model = read(text, str(arguments.document)) if is_single(text) else None
            document = (
                model.document
                if model is not None
                else parse(text, str(arguments.document))
            )
            if arguments.view != "review":
                print(
                    project_text(
                        document.nodes,
                        arguments.view,
                        {k: v.status for k, v in model.metadata.suggestions.items()}
                        if model
                        else None,
                    ),
                    end="",
                )
            else:
                records = [
                    asdict(node)
                    for node in walk(document.nodes)
                    if isinstance(node, (Change, Comment))
                ]
                print(json.dumps(records, ensure_ascii=False, indent=2))
        return 0
    except (ReviewError, OSError) as error:
        print(f"quarto-review: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
