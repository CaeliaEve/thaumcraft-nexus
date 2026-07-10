#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from thaum_nexus.client_bridge import read_and_solve_current_note, read_solve_and_apply_current_note


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Attach to the running GTNH/Minecraft client, export the open Thaumcraft note, and solve it."
    )
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--output", type=Path, default=None, help="Where to write note JSON")
    parser.add_argument("--solution-output", type=Path, default=Path("runtime/current_solution.json"))
    parser.add_argument("--apply", action="store_true", help="Also send the placements to the open research table.")
    parser.add_argument("--apply-plan-output", type=Path, default=None)
    parser.add_argument("--apply-result-output", type=Path, default=None)
    parser.add_argument("--pid", help="Minecraft JVM pid. Omit to auto-detect.")
    parser.add_argument("--solver-mode", choices=("inventory", "optimal"), default="inventory")
    parser.add_argument("--delay-ms", type=int, default=120, help="Delay between placement packets when --apply is used.")
    parser.add_argument("--verify-delay-ms", type=int, default=600)
    parser.add_argument("--no-build", action="store_true", help="Do not rebuild java-agent before attaching.")
    parser.add_argument("--timeout", type=float, default=20.0)
    args = parser.parse_args(argv)

    if args.apply:
        result = read_solve_and_apply_current_note(
            args.project_root,
            note_output_path=args.output,
            plan_path=args.apply_plan_output,
            result_path=args.apply_result_output,
            pid=args.pid,
            delay_ms=args.delay_ms,
            verify_delay_ms=args.verify_delay_ms,
            build_if_needed=not args.no_build,
            timeout=max(args.timeout, 40.0),
            solve_mode=args.solver_mode,
        )
        payload = result.to_dict()
    else:
        result = read_and_solve_current_note(
            args.project_root,
            output_path=args.output,
            pid=args.pid,
            build_if_needed=not args.no_build,
            timeout=args.timeout,
            solve_mode=args.solver_mode,
        )
        payload = result.to_dict()

    solution_output = args.solution_output
    if not solution_output.is_absolute():
        solution_output = args.project_root / solution_output
    solution_output.parent.mkdir(parents=True, exist_ok=True)
    solution_output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    payload["solutionJson"] = str(solution_output)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
