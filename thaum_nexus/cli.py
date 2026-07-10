from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .data_model import BoardState
from .knowledge_base import KnowledgeBase
from .note_io import ResearchNote
from .solver import solve


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] not in {
        "solve",
        "solve-note",
        "read-current-note",
        "apply-current-note",
        "inventory-notes",
        "load-inventory-note",
        "wheelchair",
        "-h",
        "--help",
    }:
        # Backward-compatible shortcut:
        #   python -m thaum_nexus.cli board.json
        argv.insert(0, "solve")

    parser = argparse.ArgumentParser(description="Thaumcraft Nexus command-line tools.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    solve_parser = subparsers.add_parser("solve", help="Solve a BoardState JSON file.")
    solve_parser.add_argument("board", type=Path, help="Path to board JSON")
    solve_parser.add_argument("--project-root", type=Path, default=None)
    solve_parser.set_defaults(func=_solve_board_command)

    note_parser = subparsers.add_parser("solve-note", help="Solve a Thaumcraft research-note JSON/NBT export.")
    note_parser.add_argument("note", type=Path, help="Path to note JSON exported from the client")
    note_parser.add_argument("--project-root", type=Path, default=None)
    note_parser.set_defaults(func=_solve_note_command)

    current_parser = subparsers.add_parser(
        "read-current-note",
        help="Attach to the running Minecraft client, export the open Thaumcraft note, and solve it.",
    )
    current_parser.add_argument("--project-root", type=Path, default=None)
    current_parser.add_argument("--output", type=Path, default=None)
    current_parser.add_argument("--pid", help="Minecraft JVM pid. Omit to auto-detect.")
    current_parser.add_argument("--solver-mode", choices=("inventory", "optimal"), default="inventory")
    current_parser.add_argument("--no-build", action="store_true", help="Do not rebuild java-agent before attaching.")
    current_parser.add_argument("--timeout", type=float, default=20.0)
    current_parser.set_defaults(func=_read_current_note_command)

    apply_parser = subparsers.add_parser(
        "apply-current-note",
        help="Attach to Minecraft, solve the open Thaumcraft note, and send placement packets.",
    )
    apply_parser.add_argument("--project-root", type=Path, default=None)
    apply_parser.add_argument("--note-output", type=Path, default=None)
    apply_parser.add_argument("--plan-output", type=Path, default=None)
    apply_parser.add_argument("--result-output", type=Path, default=None)
    apply_parser.add_argument("--pid", help="Minecraft JVM pid. Omit to auto-detect.")
    apply_parser.add_argument("--solver-mode", choices=("inventory", "optimal"), default="inventory")
    apply_parser.add_argument("--delay-ms", type=int, default=120, help="Delay between placement packets.")
    apply_parser.add_argument("--verify-delay-ms", type=int, default=600, help="Delay after the last packet.")
    apply_parser.add_argument("--no-build", action="store_true", help="Do not rebuild java-agent before attaching.")
    apply_parser.add_argument("--timeout", type=float, default=40.0)
    apply_parser.set_defaults(func=_apply_current_note_command)

    inventory_parser = subparsers.add_parser(
        "inventory-notes",
        help="Attach to Minecraft and list unsolved Thaumcraft research notes in the open research-table container.",
    )
    inventory_parser.add_argument("--project-root", type=Path, default=None)
    inventory_parser.add_argument("--output", type=Path, default=None)
    inventory_parser.add_argument("--pid", help="Minecraft JVM pid. Omit to auto-detect.")
    inventory_parser.add_argument("--no-build", action="store_true", help="Do not rebuild java-agent before attaching.")
    inventory_parser.add_argument("--timeout", type=float, default=20.0)
    inventory_parser.set_defaults(func=_inventory_notes_command)

    load_note_parser = subparsers.add_parser(
        "load-inventory-note",
        help="Move/swap one container slot into the research-table note slot.",
    )
    load_note_parser.add_argument("slot", type=int, help="Container slot from inventory-notes output")
    load_note_parser.add_argument("--project-root", type=Path, default=None)
    load_note_parser.add_argument("--result-output", type=Path, default=None)
    load_note_parser.add_argument("--pid", help="Minecraft JVM pid. Omit to auto-detect.")
    load_note_parser.add_argument("--no-build", action="store_true", help="Do not rebuild java-agent before attaching.")
    load_note_parser.add_argument("--timeout", type=float, default=20.0)
    load_note_parser.set_defaults(func=_load_inventory_note_command)

    wheelchair_parser = subparsers.add_parser(
        "wheelchair",
        help="Dry-run or apply batch solving for every unsolved research note in the open research table/inventory.",
    )
    wheelchair_parser.add_argument("--project-root", type=Path, default=None)
    wheelchair_parser.add_argument("--pid", help="Minecraft JVM pid. Omit to auto-detect.")
    wheelchair_parser.add_argument("--solver-mode", choices=("inventory", "optimal"), default="inventory")
    wheelchair_parser.add_argument("--apply", action="store_true", help="Actually synthesize/place aspects and swap notes.")
    wheelchair_parser.add_argument("--max-notes", type=int, default=36)
    wheelchair_parser.add_argument("--delay-ms", type=int, default=120)
    wheelchair_parser.add_argument("--verify-delay-ms", type=int, default=800)
    wheelchair_parser.add_argument("--no-build", action="store_true", help="Do not rebuild java-agent before attaching.")
    wheelchair_parser.add_argument("--timeout", type=float, default=60.0)
    wheelchair_parser.set_defaults(func=_wheelchair_command)

    args = parser.parse_args(argv)
    return args.func(args)


def _solve_board_command(args: argparse.Namespace) -> int:
    board = BoardState.from_dict(json.loads(args.board.read_text(encoding="utf-8")))
    kb = KnowledgeBase.load(args.project_root)
    solution = solve(board, kb)
    print(json.dumps(solution.to_dict(), ensure_ascii=False, indent=2))
    return 0


def _solve_note_command(args: argparse.Namespace) -> int:
    note = ResearchNote.load(args.note)
    kb = KnowledgeBase.load(args.project_root)
    solution = solve(note.board, kb)
    print(
        json.dumps(
            {
                "note": {
                    "researchKey": note.research_key,
                    "source": note.source,
                    "complete": note.complete,
                    "copies": note.copies,
                },
                "board": note.board.to_dict(),
                "solution": solution.to_dict(),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _read_current_note_command(args: argparse.Namespace) -> int:
    from .client_bridge import read_and_solve_current_note

    result = read_and_solve_current_note(
        args.project_root,
        output_path=args.output,
        pid=args.pid,
        build_if_needed=not args.no_build,
        timeout=args.timeout,
        solve_mode=args.solver_mode,
    )
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0


def _apply_current_note_command(args: argparse.Namespace) -> int:
    from .client_bridge import read_solve_and_apply_current_note

    result = read_solve_and_apply_current_note(
        args.project_root,
        note_output_path=args.note_output,
        plan_path=args.plan_output,
        result_path=args.result_output,
        pid=args.pid,
        delay_ms=args.delay_ms,
        verify_delay_ms=args.verify_delay_ms,
        build_if_needed=not args.no_build,
        timeout=args.timeout,
        solve_mode=args.solver_mode,
    )
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0


def _inventory_notes_command(args: argparse.Namespace) -> int:
    from .client_bridge import export_inventory_notes

    payload, output, stdout, stderr = export_inventory_notes(
        args.project_root,
        output_path=args.output,
        pid=args.pid,
        build_if_needed=not args.no_build,
        timeout=args.timeout,
    )
    payload["inventoryJson"] = str(output)
    payload["attacher"] = {"stdout": stdout, "stderr": stderr}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _load_inventory_note_command(args: argparse.Namespace) -> int:
    from .client_bridge import load_inventory_note_slot

    payload, output, stdout, stderr = load_inventory_note_slot(
        args.slot,
        args.project_root,
        result_path=args.result_output,
        pid=args.pid,
        build_if_needed=not args.no_build,
        timeout=args.timeout,
    )
    payload["loadResultJson"] = str(output)
    payload["attacher"] = {"stdout": stdout, "stderr": stderr}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _wheelchair_command(args: argparse.Namespace) -> int:
    from .client_bridge import solve_all_inventory_notes

    payload = solve_all_inventory_notes(
        args.project_root,
        pid=args.pid,
        apply=args.apply,
        max_notes=args.max_notes,
        delay_ms=args.delay_ms,
        verify_delay_ms=args.verify_delay_ms,
        build_if_needed=not args.no_build,
        timeout=args.timeout,
        solve_mode=args.solver_mode,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
