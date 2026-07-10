from __future__ import annotations

from contextlib import contextmanager
import importlib
import json
import os
import shutil
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .data_model import Solution
from .knowledge_base import KnowledgeBase
from .note_io import ResearchNote
from .paths import app_root, is_frozen, resource_root, runtime_root
from .resources import ResourcePlan, plan_resource_usage
from .solver import SearchConfig, solve


JAVA_HELPER_MEMORY_FLAGS = ["-Xms16m", "-Xmx128m"]
SOLVER_MODE_INVENTORY = "inventory"
SOLVER_MODE_OPTIMAL = "optimal"
DEFAULT_SOLVER_MODE = SOLVER_MODE_INVENTORY
SOLVER_MODES = frozenset({SOLVER_MODE_INVENTORY, SOLVER_MODE_OPTIMAL})
_ATTACH_LOCK_STATE = threading.local()


class OperationCancelled(RuntimeError):
    """Raised when a GUI/user cancellation request stops an in-flight operation."""


class UnsafeAgentStateError(RuntimeError):
    """Raised when a mutating Java Agent may still be running in the target JVM."""


@dataclass(frozen=True)
class CurrentNoteResult:
    note: ResearchNote
    solution: Any
    note_json_path: Path
    resource_plan: ResourcePlan | None = None
    solve_mode: str = DEFAULT_SOLVER_MODE
    stdout: str = ""
    stderr: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "noteJson": str(self.note_json_path),
            "attacher": {
                "stdout": self.stdout,
                "stderr": self.stderr,
            },
            "note": {
                "researchKey": self.note.research_key,
                "source": self.note.source,
                "complete": self.note.complete,
                "copies": self.note.copies,
            },
            "board": self.note.board.to_dict(),
            "solution": self.solution.to_dict(),
            "solveMode": self.solve_mode,
        }
        if self.resource_plan is not None:
            payload["resources"] = self.resource_plan.to_dict()
        return payload


@dataclass(frozen=True)
class ApplyResult:
    current: CurrentNoteResult
    apply_plan_path: Path
    apply_result_path: Path
    apply_payload: dict[str, Any]
    stdout: str = ""
    stderr: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = self.current.to_dict()
        payload["applyPlanJson"] = str(self.apply_plan_path)
        payload["applyResultJson"] = str(self.apply_result_path)
        payload["apply"] = self.apply_payload
        payload["applyAttacher"] = {
            "stdout": self.stdout,
            "stderr": self.stderr,
        }
        return payload


@dataclass(frozen=True)
class JavaProcess:
    pid: str
    display_name: str
    java_path: str = ""
    command_line: str = ""

    @property
    def label(self) -> str:
        return f"{self.pid}  {self.display_name}".rstrip()

    @property
    def search_text(self) -> str:
        return f"{self.display_name} {self.command_line} {self.java_path}".lower()


@dataclass(frozen=True)
class JavaRuntime:
    java: str
    java_home: Path | None = None
    major: int | None = None
    tools_jar: Path | None = None
    source: str = "default"


def export_current_note(
    project_root: Path | str | None = None,
    *,
    output_path: Path | str | None = None,
    pid: str | int | None = None,
    build_if_needed: bool = True,
    timeout: float = 20.0,
    stop_event: Any | None = None,
) -> tuple[dict[str, Any], Path, str, str]:
    """Attach to the running Minecraft client and export current research-note JSON."""

    root = _project_root(project_root)
    if output_path is None:
        output = _resolve_runtime_path(
            project_root,
            None,
            f"current_note_{uuid.uuid4().hex[:12]}.json",
        )
    else:
        output = Path(output_path)
        if not output.is_absolute():
            output = app_root(project_root) / output
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()

    completed = _run_attacher(
        root,
        ["export", str(output)],
        pid=pid,
        build_if_needed=build_if_needed,
        timeout=timeout,
        stop_event=stop_event,
    )
    if _is_cancelled(stop_event):
        raise OperationCancelled("operation cancelled after note export")
    if not output.exists():
        raise RuntimeError(
            "Java agent attach finished but did not create note JSON\n"
            f"STDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}"
        )

    payload = json.loads(output.read_text(encoding="utf-8"))
    if payload.get("status") == "error":
        raise RuntimeError(
            f"Java agent exported an error: {payload.get('error')}\n"
            f"{payload.get('stackTrace', '')}"
        )
    return payload, output, completed.stdout, completed.stderr


def read_and_solve_current_note(
    project_root: Path | str | None = None,
    *,
    output_path: Path | str | None = None,
    pid: str | int | None = None,
    build_if_needed: bool = True,
    timeout: float = 20.0,
    stop_event: Any | None = None,
    solve_mode: str = DEFAULT_SOLVER_MODE,
) -> CurrentNoteResult:
    root = _project_root(project_root)
    payload, note_path, stdout, stderr = export_current_note(
        project_root,
        output_path=output_path,
        pid=pid,
        build_if_needed=build_if_needed,
        timeout=timeout,
        stop_event=stop_event,
    )
    note = ResearchNote.from_dict(payload)
    kb = KnowledgeBase.load(root)
    available_aspects = available_aspects_from_note_payload(payload)
    solve_mode = normalize_solver_mode(solve_mode)
    config = _search_config_for_mode(solve_mode, available_aspects)
    solution = solve(note.board, kb, config)
    resource_plan = (
        plan_resource_usage(kb, solution.placements.values(), available_aspects)
        if available_aspects is not None
        else None
    )
    return CurrentNoteResult(
        note=note,
        solution=solution,
        note_json_path=note_path,
        resource_plan=resource_plan,
        solve_mode=solve_mode,
        stdout=stdout,
        stderr=stderr,
    )


def apply_solution_to_current_note(
    solution: Solution,
    project_root: Path | str | None = None,
    *,
    resource_plan: ResourcePlan | None = None,
    plan_path: Path | str | None = None,
    result_path: Path | str | None = None,
    pid: str | int | None = None,
    delay_ms: int = 120,
    verify_delay_ms: int = 600,
    build_if_needed: bool = True,
    timeout: float = 30.0,
    stop_event: Any | None = None,
) -> tuple[dict[str, Any], Path, Path, str, str]:
    """Send solver placements to the open Thaumcraft research table."""

    root = _project_root(project_root)
    operation_id = uuid.uuid4().hex[:12]
    plan = _resolve_runtime_path(project_root, plan_path, f"apply_plan_{operation_id}.json")
    result = _resolve_runtime_path(project_root, result_path, f"apply_result_{operation_id}.json")
    cancel_file = _resolve_runtime_path(project_root, None, f"{result.stem}.cancel")
    plan.parent.mkdir(parents=True, exist_ok=True)
    result.parent.mkdir(parents=True, exist_ok=True)
    if result.exists():
        result.unlink()
    if cancel_file.exists():
        cancel_file.unlink()

    if _is_cancelled(stop_event):
        raise OperationCancelled("operation cancelled before apply started")

    if resource_plan is not None and not resource_plan.is_sufficient:
        raise RuntimeError(f"aspect resources are insufficient: {resource_plan.shortages}")

    plan_payload = solution_to_apply_plan(
        solution,
        resource_plan=resource_plan,
        delay_ms=delay_ms,
        verify_delay_ms=verify_delay_ms,
        cancel_file=cancel_file,
    )
    plan.write_text(json.dumps(plan_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if not solution.placements and not plan_payload.get("combines"):
        payload = {
            "source": "client-nbt",
            "status": "ok",
            "action": "apply-synthesis-and-placements",
            "combinesRequested": 0,
            "combinesSent": 0,
            "combinesSkipped": 0,
            "placementsRequested": 0,
            "placementsSent": 0,
            "placementsSkipped": 0,
            "results": [],
            "message": "solution has no placements",
        }
        result.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return payload, plan, result, "", ""

    completed = _run_attacher(
        root,
        ["apply", str(plan), str(result)],
        pid=pid,
        build_if_needed=build_if_needed,
        timeout=timeout,
        stop_event=stop_event,
        cancel_path=cancel_file,
    )
    if not result.exists():
        raise RuntimeError(
            "Java agent apply finished but did not create result JSON\n"
            f"STDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}"
        )
    payload = json.loads(result.read_text(encoding="utf-8"))
    if payload.get("status") == "error":
        raise RuntimeError(
            f"Java agent apply returned an error: {payload.get('error')}\n"
            f"{payload.get('stackTrace', '')}"
        )
    if payload.get("status") == "cancelled" or _is_cancelled(stop_event):
        raise OperationCancelled(str(payload.get("message") or "operation cancelled"))
    return payload, plan, result, completed.stdout, completed.stderr


def read_solve_and_apply_current_note(
    project_root: Path | str | None = None,
    *,
    note_output_path: Path | str | None = None,
    plan_path: Path | str | None = None,
    result_path: Path | str | None = None,
    pid: str | int | None = None,
    delay_ms: int = 120,
    verify_delay_ms: int = 600,
    build_if_needed: bool = True,
    timeout: float = 40.0,
    stop_event: Any | None = None,
    solve_mode: str = DEFAULT_SOLVER_MODE,
) -> ApplyResult:
    target_pid = _resolve_target_pid(pid)
    with _target_attach_lock(target_pid, timeout=timeout, stop_event=stop_event):
        current = read_and_solve_current_note(
            project_root,
            output_path=note_output_path,
            pid=target_pid,
            build_if_needed=build_if_needed,
            timeout=min(timeout, 20.0),
            stop_event=stop_event,
            solve_mode=solve_mode,
        )
        if _is_cancelled(stop_event):
            raise OperationCancelled("operation cancelled before apply")
        apply_payload, apply_plan, apply_result, stdout, stderr = apply_solution_to_current_note(
            current.solution,
            project_root,
            resource_plan=current.resource_plan,
            plan_path=plan_path,
            result_path=result_path,
            pid=target_pid,
            delay_ms=delay_ms,
            verify_delay_ms=verify_delay_ms,
            build_if_needed=build_if_needed,
            timeout=timeout,
            stop_event=stop_event,
        )
        return ApplyResult(
            current=current,
            apply_plan_path=apply_plan,
            apply_result_path=apply_result,
            apply_payload=apply_payload,
            stdout=stdout,
            stderr=stderr,
        )


def solution_to_apply_plan(
    solution: Solution,
    *,
    resource_plan: ResourcePlan | None = None,
    delay_ms: int = 120,
    verify_delay_ms: int = 600,
    cancel_file: Path | str | None = None,
) -> dict[str, Any]:
    combines = [step.to_dict() for step in resource_plan.synthesis] if resource_plan is not None else []
    payload: dict[str, Any] = {
        "source": "thaum-nexus",
        "action": "apply-synthesis-and-placements" if combines else "apply-placements",
        "delayMs": int(delay_ms),
        "verifyDelayMs": int(verify_delay_ms),
        "combines": combines,
        "placements": [
            {"q": coord.q, "r": coord.r, "aspect": aspect}
            for coord, aspect in sorted(solution.placements.items())
        ],
    }
    if cancel_file is not None:
        payload["cancelFile"] = str(cancel_file)
    return payload


def available_aspects_from_note_payload(payload: dict[str, Any]) -> dict[str, int] | None:
    aspects = payload.get("aspects")
    if not isinstance(aspects, dict):
        return None
    available = aspects.get("available")
    if not isinstance(available, dict):
        return None
    out: dict[str, int] = {}
    for key, value in available.items():
        try:
            amount = int(value)
        except (TypeError, ValueError):
            continue
        if amount > 0:
            out[str(key)] = amount
    return out


def normalize_solver_mode(value: Any) -> str:
    mode = str(value or "").strip().lower()
    return mode if mode in SOLVER_MODES else DEFAULT_SOLVER_MODE


def _search_config_for_mode(
    solve_mode: str,
    available_aspects: dict[str, int] | None,
) -> SearchConfig | None:
    if solve_mode == SOLVER_MODE_OPTIMAL:
        return SearchConfig(
            aspect_inventory=available_aspects,
            minimize_placements=True,
        )
    return SearchConfig(aspect_inventory=available_aspects) if available_aspects is not None else None


def export_inventory_notes(
    project_root: Path | str | None = None,
    *,
    output_path: Path | str | None = None,
    pid: str | int | None = None,
    build_if_needed: bool = True,
    timeout: float = 20.0,
    stop_event: Any | None = None,
) -> tuple[dict[str, Any], Path, str, str]:
    """Export research-note stacks from the open research-table container."""

    root = _project_root(project_root)
    output = _resolve_runtime_path(
        project_root,
        output_path,
        f"inventory_notes_{uuid.uuid4().hex[:12]}.json",
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()
    completed = _run_attacher(
        root,
        ["inventory", str(output)],
        pid=pid,
        build_if_needed=build_if_needed,
        timeout=timeout,
        stop_event=stop_event,
    )
    if _is_cancelled(stop_event):
        raise OperationCancelled("operation cancelled after inventory scan")
    if not output.exists():
        raise RuntimeError(
            "Java agent inventory scan finished but did not create JSON\n"
            f"STDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}"
        )
    payload = json.loads(output.read_text(encoding="utf-8"))
    if payload.get("status") == "error":
        raise RuntimeError(
            f"Java agent inventory scan returned an error: {payload.get('error')}\n"
            f"{payload.get('stackTrace', '')}"
        )
    return payload, output, completed.stdout, completed.stderr


def load_inventory_note_slot(
    slot: int,
    project_root: Path | str | None = None,
    *,
    result_path: Path | str | None = None,
    pid: str | int | None = None,
    build_if_needed: bool = True,
    timeout: float = 20.0,
    stop_event: Any | None = None,
) -> tuple[dict[str, Any], Path, str, str]:
    """Move/swap one container slot into the research-table note slot."""

    root = _project_root(project_root)
    result = _resolve_runtime_path(
        project_root,
        result_path,
        f"load_note_result_{uuid.uuid4().hex[:12]}.json",
    )
    result.parent.mkdir(parents=True, exist_ok=True)
    if result.exists():
        result.unlink()
    completed = _run_attacher(
        root,
        ["load-note", str(int(slot)), str(result)],
        pid=pid,
        build_if_needed=build_if_needed,
        timeout=timeout,
        stop_event=stop_event,
    )
    if _is_cancelled(stop_event):
        raise OperationCancelled("operation cancelled after loading inventory note")
    if not result.exists():
        raise RuntimeError(
            "Java agent load-note finished but did not create JSON\n"
            f"STDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}"
        )
    payload = json.loads(result.read_text(encoding="utf-8"))
    if payload.get("status") == "error":
        raise RuntimeError(
            f"Java agent load-note returned an error: {payload.get('error')}\n"
            f"{payload.get('stackTrace', '')}"
        )
    return payload, result, completed.stdout, completed.stderr


def solve_all_inventory_notes(
    project_root: Path | str | None = None,
    *,
    pid: str | int | None = None,
    apply: bool = False,
    max_notes: int = 36,
    delay_ms: int = 120,
    verify_delay_ms: int = 800,
    build_if_needed: bool = True,
    timeout: float = 60.0,
    stop_event: Any | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
    solve_mode: str = DEFAULT_SOLVER_MODE,
) -> dict[str, Any]:
    target_pid = _resolve_target_pid(pid)
    with _target_attach_lock(target_pid, timeout=timeout, stop_event=stop_event):
        return _solve_all_inventory_notes_locked(
            project_root,
            pid=target_pid,
            apply=apply,
            max_notes=max_notes,
            delay_ms=delay_ms,
            verify_delay_ms=verify_delay_ms,
            build_if_needed=build_if_needed,
            timeout=timeout,
            stop_event=stop_event,
            progress_callback=progress_callback,
            solve_mode=solve_mode,
        )


def _solve_all_inventory_notes_locked(
    project_root: Path | str | None = None,
    *,
    pid: str | int | None = None,
    apply: bool = False,
    max_notes: int = 36,
    delay_ms: int = 120,
    verify_delay_ms: int = 800,
    build_if_needed: bool = True,
    timeout: float = 60.0,
    stop_event: Any | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
    solve_mode: str = DEFAULT_SOLVER_MODE,
) -> dict[str, Any]:
    """Wheelchair mode: solve the table note, then every unsolved inventory note.

    With ``apply=False`` this is a dry-run inventory scan.  With ``apply=True``
    the Java agent will swap notes into the open research table and send
    synthesis/placement packets.
    """

    steps: list[dict[str, Any]] = []
    solved = 0
    _emit_progress(progress_callback, "inventory-scan", "正在扫描研究台和背包里的研究笔记")
    inventory, inventory_path, inv_stdout, inv_stderr = export_inventory_notes(
        project_root,
        pid=pid,
        build_if_needed=build_if_needed,
        timeout=min(timeout, 20.0),
        stop_event=stop_event,
    )
    last_inventory_path = inventory_path
    last_inventory_stdout = inv_stdout
    last_inventory_stderr = inv_stderr
    notes = [note for note in inventory.get("notes", []) if isinstance(note, dict)]
    unsolved = [note for note in notes if not bool(note.get("complete"))]
    pending_notes = _unsolved_inventory_notes(notes)
    table_note = _table_inventory_note(notes)
    current_needs_solve = bool(table_note is not None and not bool(table_note.get("complete")))
    _emit_progress(
        progress_callback,
        "inventory-scan-done",
        f"发现 {len(notes)} 张研究笔记，其中 {len(unsolved)} 张未解",
        notesFound=len(notes),
        unsolvedCount=len(unsolved),
    )
    if not apply:
        return {
            "source": "thaum-nexus",
            "status": "ok",
            "action": "wheelchair-dry-run",
            "inventoryJson": str(inventory_path),
            "unsolvedCount": len(unsolved),
            "notes": unsolved,
            "attacher": {"stdout": inv_stdout, "stderr": inv_stderr},
        }
    if _is_cancelled(stop_event):
        return _cancelled_wheelchair_payload(solved, steps, "stopped before applying any note")
    if not current_needs_solve and not pending_notes:
        return {
            "source": "thaum-nexus",
            "status": "ok",
            "action": "wheelchair-apply",
            "message": "no unsolved inventory notes remain",
            "solvedOrAttempted": solved,
            "steps": steps,
            "lastInventoryJson": str(last_inventory_path),
            "attacher": {"stdout": last_inventory_stdout, "stderr": last_inventory_stderr},
        }

    for iteration in range(max_notes):
        if _is_cancelled(stop_event):
            return _cancelled_wheelchair_payload(solved, steps, "stopped before next note")

        if not current_needs_solve:
            next_note = pending_notes.pop(0) if pending_notes else None
            if next_note is None:
                _emit_progress(
                    progress_callback,
                    "inventory-final-scan",
                    f"第 {iteration + 1} 轮：队列已处理完，最后确认背包未解笔记",
                    iteration=iteration,
                )
                inventory, last_inventory_path, last_inventory_stdout, last_inventory_stderr = export_inventory_notes(
                    project_root,
                    output_path=f"runtime/wheelchair_inventory_final_{iteration:02d}.json",
                    pid=pid,
                    build_if_needed=build_if_needed,
                    timeout=min(timeout, 20.0),
                    stop_event=stop_event,
                )
                notes = [note for note in inventory.get("notes", []) if isinstance(note, dict)]
                pending_notes = _unsolved_inventory_notes(notes)
                table_note = _table_inventory_note(notes)
                current_needs_solve = bool(table_note is not None and not bool(table_note.get("complete")))
                if not current_needs_solve:
                    next_note = pending_notes.pop(0) if pending_notes else None
                    if next_note is None:
                        return {
                            "source": "thaum-nexus",
                            "status": "ok",
                            "action": "wheelchair-apply",
                            "message": "no unsolved inventory notes remain",
                            "solvedOrAttempted": solved,
                            "steps": steps,
                            "lastInventoryJson": str(last_inventory_path),
                            "attacher": {"stdout": last_inventory_stdout, "stderr": last_inventory_stderr},
                        }

            if not current_needs_solve:
                if _is_cancelled(stop_event):
                    return _cancelled_wheelchair_payload(solved, steps, "stopped before loading next note")
                _emit_progress(
                    progress_callback,
                    "load-inventory-note",
                    f"把下一张未解笔记放入研究台：{next_note.get('researchKey', '')}",
                    iteration=iteration,
                    slot=int(next_note["slot"]),
                    researchKey=next_note.get("researchKey", ""),
                )
                load_payload, load_result, load_stdout, load_stderr = load_inventory_note_slot(
                    int(next_note["slot"]),
                    project_root,
                    result_path=f"runtime/wheelchair_load_{iteration:02d}.json",
                    pid=pid,
                    build_if_needed=build_if_needed,
                    timeout=min(timeout, 20.0),
                    stop_event=stop_event,
                )
                steps.append(
                    {
                        "iteration": iteration,
                        "action": "load-inventory-note",
                        "slot": int(next_note["slot"]),
                        "researchKey": next_note.get("researchKey", ""),
                        "resultJson": str(load_result),
                        "result": load_payload,
                        "stdout": load_stdout,
                        "stderr": load_stderr,
                    }
                )
                current_needs_solve = True

        try:
            _emit_progress(
                progress_callback,
                "read-current-note",
                f"第 {iteration + 1} 轮：读取当前研究台笔记",
                iteration=iteration,
            )
            current = read_and_solve_current_note(
                project_root,
                output_path=f"runtime/wheelchair_current_{iteration:02d}.json",
                pid=pid,
                build_if_needed=build_if_needed,
                timeout=min(timeout, 20.0),
                stop_event=stop_event,
                solve_mode=solve_mode,
            )
            if current.note.complete:
                current_needs_solve = False
                steps.append(
                    {
                        "iteration": iteration,
                        "action": "read-current-note",
                        "status": "already-complete",
                        "researchKey": current.note.research_key,
                    }
                )
                continue
            if not current.solution.placements:
                steps.append(
                    {
                        "iteration": iteration,
                        "action": "solve-current-note",
                        "status": "blocked",
                        "researchKey": current.note.research_key,
                        "message": "note is not complete but solver has no placements to send",
                    }
                )
                break
            if _is_cancelled(stop_event):
                return _cancelled_wheelchair_payload(solved, steps, "stopped before applying current note")
            _emit_progress(
                progress_callback,
                "apply-current-note",
                (
                    f"正在解 {current.note.research_key or current.note.board.name}："
                    f"{len(current.solution.placements)} 个放置点"
                ),
                iteration=iteration,
                researchKey=current.note.research_key,
                placements=len(current.solution.placements),
                combines=(
                    len(current.resource_plan.synthesis)
                    if current.resource_plan is not None
                    else 0
                ),
            )
            apply_payload, plan, result, stdout, stderr = apply_solution_to_current_note(
                current.solution,
                project_root,
                resource_plan=current.resource_plan,
                plan_path=f"runtime/wheelchair_apply_plan_{iteration:02d}.json",
                result_path=f"runtime/wheelchair_apply_result_{iteration:02d}.json",
                pid=pid,
                delay_ms=delay_ms,
                verify_delay_ms=verify_delay_ms,
                build_if_needed=build_if_needed,
                timeout=timeout,
                stop_event=stop_event,
            )
            placements_sent = int(apply_payload.get("placementsSent", 0) or 0)
            combines_sent = int(apply_payload.get("combinesSent", 0) or 0)
            solved += 1
            current_needs_solve = False
            steps.append(
                {
                    "iteration": iteration,
                    "action": "solve-current-note",
                    "researchKey": current.note.research_key,
                    "placements": len(current.solution.placements),
                    "placementsSent": placements_sent,
                    "combinesSent": combines_sent,
                    "applyPlanJson": str(plan),
                    "applyResultJson": str(result),
                    "stdout": stdout,
                    "stderr": stderr,
                }
            )
            _emit_progress(
                progress_callback,
                "apply-current-note-done",
                (
                    f"完成 {current.note.research_key or current.note.board.name}："
                    f"合成 {combines_sent} 次，放置 {placements_sent} 个"
                ),
                iteration=iteration,
                researchKey=current.note.research_key,
                placementsSent=placements_sent,
                combinesSent=combines_sent,
            )
            if placements_sent == 0 and combines_sent == 0 and current.solution.placements:
                break
        except OperationCancelled:
            return _cancelled_wheelchair_payload(solved, steps, "stopped during current note")
        except Exception as exc:
            current_needs_solve = False
            steps.append({"iteration": iteration, "action": "read-current-note", "status": "skipped", "error": str(exc)})
            return {
                "source": "thaum-nexus",
                "status": "error",
                "action": "wheelchair-apply",
                "message": f"wheelchair mode stopped after an operation error: {exc}",
                "solvedOrAttempted": solved,
                "steps": steps,
            }

    return {
        "source": "thaum-nexus",
        "status": "incomplete",
        "action": "wheelchair-apply",
        "message": f"stopped after max_notes={max_notes}",
        "solvedOrAttempted": solved,
        "steps": steps,
    }


def _first_unsolved_inventory_note(notes: list[dict[str, Any]]) -> dict[str, Any] | None:
    candidates = _unsolved_inventory_notes(notes)
    return candidates[0] if candidates else None


def _unsolved_inventory_notes(notes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates = [
        note for note in notes
        if not bool(note.get("complete")) and str(note.get("slotKind") or "") != "table-note"
    ]
    return sorted(candidates, key=lambda item: int(item.get("slot", 0)))


def _table_inventory_note(notes: list[dict[str, Any]]) -> dict[str, Any] | None:
    for note in notes:
        if str(note.get("slotKind") or "") == "table-note":
            return note
    return None


def _is_cancelled(stop_event: Any | None) -> bool:
    return bool(stop_event is not None and getattr(stop_event, "is_set")())


def _emit_progress(
    progress_callback: Callable[[dict[str, Any]], None] | None,
    event: str,
    message: str,
    **payload: Any,
) -> None:
    if progress_callback is None:
        return
    progress = {"event": event, "message": message}
    progress.update(payload)
    progress_callback(progress)


def _cancelled_wheelchair_payload(
    solved: int,
    steps: list[dict[str, Any]],
    message: str,
) -> dict[str, Any]:
    return {
        "source": "thaum-nexus",
        "status": "cancelled",
        "action": "wheelchair-apply",
        "message": message,
        "solvedOrAttempted": solved,
        "steps": steps,
    }


def ensure_agent_built(project_root: Path | str | None = None) -> Path:
    root = _project_root(project_root)
    jar = agent_jar_path(root)
    if is_frozen() and jar.exists():
        return jar
    if is_frozen():
        raise RuntimeError(
            "便携包内没有找到 Java Agent。请重新运行 scripts\\build_portable.ps1 打包，"
            f"或确认文件存在：{jar}"
        )

    sources = list((root / "java-agent" / "src" / "main" / "java").rglob("*.java"))
    newest_source = max((source.stat().st_mtime for source in sources), default=0.0)
    if jar.exists() and jar.stat().st_mtime >= newest_source:
        return jar

    build_script = root / "java-agent" / "build_agent.ps1"
    if not build_script.exists():
        if jar.exists():
            return jar
        raise RuntimeError(f"Java agent build script was not found: {build_script}")
    completed = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(build_script),
        ],
        cwd=str(root),
        text=True,
        capture_output=True,
        timeout=60.0,
        **_hidden_subprocess_kwargs(),
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "Failed to build Java agent\n"
            f"STDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}"
        )
    built = _parse_built_agent_path(completed.stdout)
    if built is not None and built.exists():
        return built
    jar = agent_jar_path(root)
    if not jar.exists():
        raise RuntimeError(f"Java agent build did not create {jar}")
    return jar


def agent_jar_path(project_root: Path | str | None = None) -> Path:
    root = _project_root(project_root)
    bundled_candidates = [
        root / "java-agent" / "thaum-nexus-agent.jar",
        app_root() / "java-agent" / "thaum-nexus-agent.jar",
    ]
    for candidate in bundled_candidates:
        if candidate.exists():
            return candidate

    latest = root / "java-agent" / "build" / "latest-agent.path"
    if latest.exists():
        try:
            candidate = Path(latest.read_text(encoding="utf-8-sig").strip())
            if candidate.exists():
                return candidate
        except OSError:
            pass
    source_candidate = root / "java-agent" / "build" / "thaum-nexus-agent.jar"
    if source_candidate.exists():
        return source_candidate
    return bundled_candidates[0] if is_frozen() else source_candidate


def find_java() -> str:
    jdk_home = _find_jdk_home()
    if jdk_home is not None:
        java = jdk_home / "bin" / "java.exe"
        if java.exists():
            return str(java)
        java = jdk_home / "bin" / "java"
        if java.exists():
            return str(java)
    return shutil.which("java") or "java"


def find_tools_jar() -> Path | None:
    candidates = [home / "lib" / "tools.jar" for home in _jdk_home_candidates()]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def java_environment_diagnostics(
    *,
    java: str | None = None,
    tools_jar: Path | None = None,
    agent_jar: Path | None = None,
    target_pid: str | int | None = None,
    runtime: JavaRuntime | None = None,
) -> dict[str, Any]:
    java = java or find_java()
    tools_jar = tools_jar if tools_jar is not None else find_tools_jar()
    selected_jdk = _find_jdk_home()
    candidates = _jdk_home_candidates()
    version_text = _java_version_text(java)
    java_major = _parse_java_major_version(version_text)
    payload: dict[str, Any] = {
        "java": java,
        "selectedJdkHome": str(selected_jdk) if selected_jdk is not None else "",
        "javaHome": os.environ.get("JAVA_HOME", ""),
        "thaumNexusJdk": os.environ.get("THAUM_NEXUS_JDK", ""),
        "pathJava": shutil.which("java") or "",
        "pathJavac": shutil.which("javac") or "",
        "toolsJar": str(tools_jar) if tools_jar is not None else "",
        "agentJar": str(agent_jar) if agent_jar is not None else "",
        "javaVersion": version_text,
        "javaMajor": java_major,
        "jdkCandidates": [str(candidate) for candidate in candidates[:12]],
    }
    if runtime is not None:
        payload["attacherRuntime"] = {
            "java": runtime.java,
            "javaHome": str(runtime.java_home) if runtime.java_home is not None else "",
            "major": runtime.major,
            "toolsJar": str(runtime.tools_jar) if runtime.tools_jar is not None else "",
            "source": runtime.source,
        }
    if target_pid is not None:
        payload["targetPid"] = str(target_pid)
        payload["targetProcess"] = _windows_process_info(target_pid)
    if (java_major is None or java_major <= 8) and tools_jar is None:
        payload["warning"] = (
            "Java 8 目标需要 lib/tools.jar；Java 9+ 目标需要带 jdk.attach 模块的同版本 JDK/运行时。"
        )
    return payload


def list_java_processes(timeout: float = 5.0) -> list[JavaProcess]:
    """List visible local JVMs using jps plus Windows process metadata."""

    by_pid: dict[str, JavaProcess] = {}
    for jps in _jps_candidates():
        try:
            completed = subprocess.run(
                [str(jps), "-lv"],
                text=True,
                capture_output=True,
                timeout=timeout,
                **_hidden_subprocess_kwargs(),
            )
        except Exception:
            continue
        if completed.returncode != 0:
            continue
        for process in _parse_jps_output(completed.stdout):
            by_pid.setdefault(process.pid, process)

    for process in _windows_java_processes():
        current = by_pid.get(process.pid)
        if current is None:
            by_pid[process.pid] = process
        else:
            by_pid[process.pid] = JavaProcess(
                pid=current.pid,
                display_name=current.display_name or process.display_name,
                java_path=process.java_path or current.java_path,
                command_line=process.command_line or current.command_line,
            )

    return sorted(by_pid.values(), key=lambda item: int(item.pid))


def _parse_jps_output(output: str) -> list[JavaProcess]:
    processes: list[JavaProcess] = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split(maxsplit=1)
        pid = parts[0].strip()
        if not pid.isdigit():
            continue
        display_name = parts[1].strip() if len(parts) > 1 else ""
        processes.append(JavaProcess(pid=pid, display_name=display_name))
    return processes


def _jps_candidates() -> list[Path]:
    candidates: list[Path] = []
    seen: set[str] = set()

    def add(path: Path | str | None) -> None:
        if not path:
            return
        candidate = Path(path)
        key = _path_key(candidate)
        if candidate.exists() and key not in seen:
            seen.add(key)
            candidates.append(candidate)

    for home in _jdk_home_candidates():
        add(home / "bin" / ("jps.exe" if os.name == "nt" else "jps"))
    found = shutil.which("jps")
    if found:
        add(found)
    return candidates


def _choose_minecraft_jvm_pid() -> str | None:
    candidates = [process for process in list_java_processes() if _is_minecraft_like_process(process)]
    return candidates[0].pid if candidates else None


def _is_minecraft_like_process(process: JavaProcess) -> bool:
    value = process.search_text
    return (
        "minecraft" in value
        or "launchwrapper" in value
        or "net.minecraft.launchwrapper.launch" in value
        or "org.prismlauncher.entrypoint" in value
        or "org.multimc.entrypoint" in value
        or "forge" in value
        or "gtnh" in value
        or "gradlestart" in value
    )


def _select_attacher_runtime(pid: str | int | None) -> JavaRuntime:
    target_pid = str(pid).strip() if pid is not None else ""
    if target_pid:
        target_runtime = _runtime_from_process(target_pid)
        if target_runtime is not None:
            compatible = _compatible_runtime_for_target(target_runtime)
            if compatible is not None:
                return compatible

    java = find_java()
    home = _java_home_from_executable(Path(java))
    major = _java_major_version(java)
    return JavaRuntime(
        java=java,
        java_home=home,
        major=major,
        tools_jar=find_tools_jar() if major is None or major <= 8 else None,
        source="default",
    )


def _runtime_from_process(pid: str | int) -> JavaRuntime | None:
    info = _windows_process_info(pid)
    executable = info.get("executablePath") if info else ""
    if not executable:
        return None
    home = _java_home_from_executable(Path(executable))
    if home is None:
        return None
    java = _java_executable_for_home(home)
    if java is None:
        return None
    return JavaRuntime(
        java=str(java),
        java_home=home,
        major=_java_major_version(str(java)),
        tools_jar=home / "lib" / "tools.jar" if (home / "lib" / "tools.jar").exists() else None,
        source=f"target-pid:{pid}",
    )


def _compatible_runtime_for_target(target: JavaRuntime) -> JavaRuntime | None:
    major = target.major
    if major is None:
        return target
    if major <= 8:
        runtime = _find_runtime_for_major(8, require_attach=True)
        return runtime or target
    if _java_supports_jdk_attach(target.java):
        return target
    runtime = _find_runtime_for_major(major, require_attach=True)
    return runtime or target


def _find_runtime_for_major(major: int, *, require_attach: bool) -> JavaRuntime | None:
    for home in _jdk_home_candidates():
        java = _java_executable_for_home(home)
        if java is None:
            continue
        runtime_major = _java_major_version(str(java))
        if runtime_major != major:
            continue
        tools_jar = home / "lib" / "tools.jar"
        if major <= 8:
            if require_attach and not tools_jar.exists():
                continue
            return JavaRuntime(
                java=str(java),
                java_home=home,
                major=runtime_major,
                tools_jar=tools_jar if tools_jar.exists() else None,
                source=f"jdk-candidate:{major}",
            )
        if require_attach and not _java_supports_jdk_attach(str(java)):
            continue
        return JavaRuntime(java=str(java), java_home=home, major=runtime_major, source=f"jdk-candidate:{major}")
    return None


def _build_attacher_command(
    runtime: JavaRuntime,
    agent_jar: Path,
    attacher_args: list[str],
    *,
    pid: str | int | None,
) -> list[str]:
    classpath_parts = [str(agent_jar)]
    cmd = [runtime.java, *JAVA_HELPER_MEMORY_FLAGS]
    if runtime.major is not None and runtime.major >= 9:
        cmd += ["--add-modules", "jdk.attach"]
    elif runtime.tools_jar is not None:
        classpath_parts.insert(0, str(runtime.tools_jar))
    cmd += [
        "-cp",
        os.pathsep.join(classpath_parts),
        "thaumnexus.agent.ThaumNexusAttacher",
        str(agent_jar),
        *attacher_args,
    ]
    if pid is not None:
        cmd.append(str(pid))
    return cmd


def _windows_java_processes() -> list[JavaProcess]:
    if os.name != "nt":
        return []
    script = (
        "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; "
        "Get-CimInstance Win32_Process | "
        "Where-Object { $_.Name -match '^javaw?\\.exe$' } | "
        "Select-Object ProcessId,Name,ExecutablePath,CommandLine | "
        "ConvertTo-Json -Compress"
    )
    payload = _run_powershell_json(script)
    if payload is None:
        return []
    rows = payload if isinstance(payload, list) else [payload]
    processes: list[JavaProcess] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        pid = str(row.get("ProcessId") or "").strip()
        if not pid.isdigit():
            continue
        command_line = str(row.get("CommandLine") or "").strip()
        executable = str(row.get("ExecutablePath") or "").strip()
        name = str(row.get("Name") or "").strip()
        display_name = _display_name_from_command_line(command_line) or name
        processes.append(
            JavaProcess(
                pid=pid,
                display_name=display_name,
                java_path=executable,
                command_line=command_line,
            )
        )
    return processes


def _windows_process_info(pid: str | int) -> dict[str, str]:
    if os.name != "nt":
        return {}
    pid_text = str(pid).strip()
    if not pid_text.isdigit():
        return {}
    script = (
        "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; "
        f"Get-CimInstance Win32_Process -Filter \"ProcessId = {pid_text}\" | "
        "Select-Object ProcessId,Name,ExecutablePath,CommandLine | "
        "ConvertTo-Json -Compress"
    )
    payload = _run_powershell_json(script)
    if not isinstance(payload, dict):
        return {}
    return {
        "pid": str(payload.get("ProcessId") or ""),
        "name": str(payload.get("Name") or ""),
        "executablePath": str(payload.get("ExecutablePath") or ""),
        "commandLine": str(payload.get("CommandLine") or ""),
    }


def _run_powershell_json(script: str) -> Any:
    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=8.0,
            **_hidden_subprocess_kwargs(),
        )
    except Exception:
        return None
    if completed.returncode != 0 or not completed.stdout.strip():
        return None
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError:
        return None


def _display_name_from_command_line(command_line: str) -> str:
    if not command_line:
        return ""
    parts = command_line.split()
    for token in parts[1:]:
        value = token.strip('"')
        if value.startswith("-"):
            continue
        if value.endswith(".jar"):
            return value
        if "." in value:
            return value
    return ""


def _resolve_target_pid(pid: str | int | None) -> str:
    value = str(pid).strip() if pid is not None else ""
    value = value or _choose_minecraft_jvm_pid()
    return str(int(value)) if value.isdigit() else value


def _global_attach_lock_root() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "ThaumcraftNexus" / "locks"
    return Path.home() / ".thaumcraft-nexus" / "locks"


def _target_lock_path(target_pid: str) -> Path:
    return _global_attach_lock_root() / f"jvm_{target_pid}.lock"


def _unsafe_marker_path(target_pid: str) -> Path:
    return _global_attach_lock_root() / f"jvm_{target_pid}.unsafe"


@contextmanager
def _target_attach_lock(
    target_pid: str,
    *,
    timeout: float,
    stop_event: Any | None,
):
    """Serialize complete operations for one target JVM across app copies."""

    counts = getattr(_ATTACH_LOCK_STATE, "counts", None)
    if counts is None:
        counts = {}
        _ATTACH_LOCK_STATE.counts = counts
    if counts.get(target_pid, 0) > 0:
        if _unsafe_marker_path(target_pid).exists():
            raise UnsafeAgentStateError(
                "the current JVM transaction entered an unsafe Java Agent state; "
                f"restart JVM {target_pid} before running another operation"
            )
        counts[target_pid] += 1
        try:
            yield
        finally:
            counts[target_pid] -= 1
        return

    lock_path = _target_lock_path(target_pid)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+b")
    if handle.seek(0, os.SEEK_END) == 0:
        handle.write(b"\0")
        handle.flush()

    deadline = time.monotonic() + max(1.0, float(timeout))
    acquired = False
    try:
        while not acquired:
            if _is_cancelled(stop_event):
                raise OperationCancelled("operation cancelled while waiting for the target JVM lock")
            try:
                _lock_file_byte(handle)
                acquired = True
            except OSError:
                if time.monotonic() >= deadline:
                    raise RuntimeError(
                        f"another Thaumcraft Nexus operation is still using JVM {target_pid}"
                    )
                time.sleep(0.05)

        unsafe_marker = _unsafe_marker_path(target_pid)
        if unsafe_marker.exists():
            if _pid_is_running(target_pid):
                raise UnsafeAgentStateError(
                    "a previous Java Agent operation did not confirm shutdown; "
                    f"restart JVM {target_pid} before running another operation"
                )
            unsafe_marker.unlink(missing_ok=True)

        counts[target_pid] = 1
        try:
            yield
        finally:
            counts.pop(target_pid, None)
    finally:
        try:
            if acquired:
                _unlock_file_byte(handle)
        finally:
            handle.close()


def _pid_is_running(pid: str | int) -> bool:
    pid_text = str(pid).strip()
    if not pid_text.isdigit():
        return False
    process_id = int(pid_text)
    if os.name == "nt":
        import ctypes

        process_query_limited_information = 0x1000
        still_active = 259
        handle = ctypes.windll.kernel32.OpenProcess(
            process_query_limited_information,
            False,
            process_id,
        )
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            if not ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return True
            return exit_code.value == still_active
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)

    try:
        os.kill(process_id, 0)
    except OSError:
        return False
    return True


def _lock_file_byte(handle: Any) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        return

    fcntl = importlib.import_module("fcntl")
    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_file_byte(handle: Any) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return

    fcntl = importlib.import_module("fcntl")
    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _run_attacher(
    root: Path,
    attacher_args: list[str],
    *,
    pid: str | int | None,
    build_if_needed: bool,
    timeout: float,
    stop_event: Any | None = None,
    cancel_path: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    if _is_cancelled(stop_event):
        if cancel_path is not None:
            _touch_cancel_file(cancel_path)
        raise OperationCancelled("operation cancelled before Java attach")

    agent_jar = ensure_agent_built(root) if build_if_needed else agent_jar_path(root)
    target_pid = _resolve_target_pid(pid)
    runtime = _select_attacher_runtime(target_pid)
    cmd = _build_attacher_command(runtime, agent_jar, attacher_args, pid=target_pid)
    mutates_target = bool(attacher_args and attacher_args[0] in {"apply", "load-note"})

    cwd = app_root() if is_frozen() else root
    with _target_attach_lock(target_pid, timeout=timeout, stop_event=stop_event):
        completed = _run_cancellable_subprocess(
            cmd,
            cwd=str(cwd),
            timeout=timeout,
            stop_event=stop_event,
            cancel_path=cancel_path,
            unsafe_marker=_unsafe_marker_path(target_pid) if mutates_target else None,
        )
    if _is_cancelled(stop_event):
        raise OperationCancelled(
            "operation cancelled while Java attach was running\n"
            f"STDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}"
        )
    if completed.returncode != 0:
        diagnostics = java_environment_diagnostics(
            java=runtime.java,
            tools_jar=runtime.tools_jar,
            agent_jar=agent_jar,
            target_pid=target_pid,
            runtime=runtime,
        )
        raise RuntimeError(
            "Java agent attach failed with exit code "
            f"{completed.returncode}\n"
            f"DIAGNOSTICS:\n{json.dumps(diagnostics, ensure_ascii=False, indent=2)}\n"
            f"STDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}"
        )
    return completed


def _run_cancellable_subprocess(
    cmd: list[str],
    *,
    cwd: str,
    timeout: float,
    stop_event: Any | None = None,
    cancel_path: Path | None = None,
    unsafe_marker: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    if stop_event is None and cancel_path is None and unsafe_marker is None:
        return subprocess.run(
            cmd,
            cwd=cwd,
            text=True,
            capture_output=True,
            timeout=timeout,
            **_hidden_subprocess_kwargs(),
        )

    process = subprocess.Popen(
        cmd,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        **_hidden_subprocess_kwargs(),
    )
    started = time.monotonic()
    cancel_deadline: float | None = None
    timeout_cancelled = False
    timeout_cancel_deadline: float | None = None
    while True:
        returncode = process.poll()
        if returncode is not None:
            stdout, stderr = process.communicate()
            if timeout_cancelled:
                raise subprocess.TimeoutExpired(
                    cmd,
                    timeout,
                    output=stdout,
                    stderr=stderr,
                )
            return subprocess.CompletedProcess(cmd, returncode, stdout, stderr)

        now = time.monotonic()
        if timeout is not None and now - started >= timeout and not timeout_cancelled:
            if cancel_path is None:
                stdout, stderr = _terminate_process(process)
                if unsafe_marker is not None:
                    _touch_unsafe_marker(
                        unsafe_marker,
                        "attacher timeout expired before the mutating Java Agent completed",
                    )
                    raise UnsafeAgentStateError(
                        "mutating Java Agent did not confirm completion after attacher timeout; "
                        "restart the target JVM before retrying\n"
                        f"STDOUT:\n{stdout}\nSTDERR:\n{stderr}"
                    )
                raise subprocess.TimeoutExpired(
                    cmd,
                    timeout,
                    output=stdout,
                    stderr=stderr,
                )
            _touch_cancel_file(cancel_path)
            timeout_cancelled = True
            timeout_cancel_deadline = now + 5.0

        if timeout_cancelled and timeout_cancel_deadline is not None and now >= timeout_cancel_deadline:
            stdout, stderr = _terminate_process(process)
            if unsafe_marker is not None:
                _touch_unsafe_marker(
                    unsafe_marker,
                    "attacher timeout expired before the Java Agent confirmed cancellation",
                )
            raise UnsafeAgentStateError(
                "Java Agent did not confirm cancellation after timeout; "
                "restart the target JVM before retrying\n"
                f"STDOUT:\n{stdout}\nSTDERR:\n{stderr}"
            )

        if not timeout_cancelled and _is_cancelled(stop_event):
            if cancel_path is not None:
                _touch_cancel_file(cancel_path)
            if cancel_deadline is None:
                cancel_deadline = now + 0.8
            elif now >= cancel_deadline:
                stdout, stderr = _terminate_process(process)
                if unsafe_marker is not None:
                    _touch_unsafe_marker(
                        unsafe_marker,
                        "attacher was terminated before the Java Agent confirmed cancellation",
                    )
                    raise UnsafeAgentStateError(
                        "Java Agent did not confirm cancellation; "
                        "restart the target JVM before retrying\n"
                        f"STDOUT:\n{stdout}\nSTDERR:\n{stderr}"
                    )
                raise OperationCancelled(
                    "operation cancelled while Java attach was running\n"
                    f"STDOUT:\n{stdout}\nSTDERR:\n{stderr}"
                )

        time.sleep(0.05)


def _touch_cancel_file(path: Path) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("cancelled\n", encoding="utf-8")
    except OSError:
        pass


def _touch_unsafe_marker(path: Path, message: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(message.rstrip() + "\n", encoding="utf-8")
    except OSError:
        pass


def _terminate_process(process: subprocess.Popen[str]) -> tuple[str, str]:
    try:
        process.terminate()
        return process.communicate(timeout=0.8)
    except subprocess.TimeoutExpired:
        process.kill()
        return process.communicate()


def _resolve_runtime_path(project_root: Path | str | None, path: Path | str | None, default_name: str) -> Path:
    if path is None:
        return runtime_root(project_root) / default_name
    resolved = Path(path)
    if not resolved.is_absolute():
        resolved = app_root(project_root) / resolved
    return resolved


def _parse_built_agent_path(stdout: str) -> Path | None:
    for line in reversed(stdout.splitlines()):
        text = line.strip()
        if text.endswith(".jar"):
            return Path(text)
    return None


def _hidden_subprocess_kwargs() -> dict[str, Any]:
    """Hide helper console windows spawned by java.exe/powershell.exe on Windows."""

    if os.name != "nt":
        return {}

    kwargs: dict[str, Any] = {}
    create_no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if create_no_window:
        kwargs["creationflags"] = create_no_window

    startupinfo_factory = getattr(subprocess, "STARTUPINFO", None)
    if startupinfo_factory is not None:
        startupinfo = startupinfo_factory()
        startupinfo.dwFlags |= getattr(subprocess, "STARTF_USESHOWWINDOW", 0)
        startupinfo.wShowWindow = getattr(subprocess, "SW_HIDE", 0)
        kwargs["startupinfo"] = startupinfo

    return kwargs


def _find_jdk_home() -> Path | None:
    for home in _jdk_home_candidates():
        if (home / "bin" / "java.exe").exists() or (home / "bin" / "java").exists():
            return home
    return None


def _jdk_home_candidates() -> list[Path]:
    ranked: list[tuple[int, Path]] = []
    seen: set[str] = set()

    def add_home(path: Path | str | None, rank: int) -> None:
        if not path:
            return
        for home in _expand_jdk_home(Path(path).expanduser()):
            key = _path_key(home)
            if key not in seen:
                seen.add(key)
                ranked.append((rank, home))

    add_home(os.environ.get("THAUM_NEXUS_JDK"), 0)
    for bundled in _bundled_jdk_roots():
        add_home(bundled, 1)

    add_home(os.environ.get("JAVA_HOME"), 2)

    javac = shutil.which("javac")
    if javac:
        add_home(Path(javac).resolve().parent.parent, 3)

    java = shutil.which("java")
    if java:
        add_home(Path(java).resolve().parent.parent, 4)

    if os.name == "nt":
        for base in (
            os.environ.get("ProgramFiles"),
            os.environ.get("ProgramFiles(x86)"),
        ):
            if not base:
                continue
            for parent in (
                Path(base) / "Java",
                Path(base) / "Eclipse Adoptium",
                Path(base) / "Microsoft",
                Path(base) / "Zulu",
            ):
                if not parent.exists():
                    continue
                for child in sorted(parent.glob("jdk*"), reverse=True):
                    add_home(child, 5)

    # Within the same source rank, keep Java 8 JDKs near the front for legacy
    # GTNH clients. Target-specific runtime selection overrides this when a
    # game PID is known.
    def sort_key(item: tuple[int, Path]) -> tuple[int, int, int, str]:
        rank, home = item
        tools_jar = home / "lib" / "tools.jar"
        return (
            rank,
            0 if tools_jar.exists() and "1.8" in home.name else 1,
            0 if tools_jar.exists() else 1,
            str(home).lower(),
        )

    return [home for _, home in sorted(ranked, key=sort_key)]


def _bundled_jdk_roots() -> list[Path]:
    """Candidate portable JDK locations shipped next to the application."""

    roots: list[Path] = []
    for base in (app_root(), resource_root()):
        for name in (
            "jdk",
            "jdk8",
            "jdk17",
            "jdk18",
            "jdk19",
            "jdk20",
            "jdk21",
            "jdk22",
            "jdk23",
            "jdk24",
            "jdk25",
            "java",
            "java8",
            "java17",
            "java18",
            "java19",
            "java20",
            "java21",
            "java22",
            "java23",
            "java24",
            "java25",
            "portable-jdk",
        ):
            candidate = base / name
            if _path_key(candidate) not in {_path_key(root) for root in roots}:
                roots.append(candidate)
    return roots


def _expand_jdk_home(path: Path) -> list[Path]:
    """Return ``path`` and one-level children that look like JDK homes."""

    if _has_java_binary(path) or (path / "lib" / "tools.jar").exists():
        return [path]
    if not path.exists() or not path.is_dir():
        return [path]

    homes: list[Path] = []
    for child in sorted(path.iterdir(), key=lambda item: item.name.lower()):
        if child.is_dir() and (_has_java_binary(child) or (child / "lib" / "tools.jar").exists()):
            homes.append(child)
    return homes or [path]


def _has_java_binary(home: Path) -> bool:
    return (home / "bin" / "java.exe").exists() or (home / "bin" / "java").exists()


def _java_executable_for_home(home: Path) -> Path | None:
    for name in ("java.exe", "java"):
        candidate = home / "bin" / name
        if candidate.exists():
            return candidate
    return None


def _java_home_from_executable(java_path: Path) -> Path | None:
    try:
        resolved = java_path.resolve()
    except OSError:
        resolved = java_path.absolute()
    if resolved.parent.name.lower() == "bin":
        return resolved.parent.parent
    return None


def _path_key(path: Path) -> str:
    try:
        resolved = path.resolve()
    except OSError:
        resolved = path.absolute()
    return os.path.normcase(str(resolved))


def _java_version_text(java: str) -> str:
    try:
        completed = subprocess.run(
            [java, *JAVA_HELPER_MEMORY_FLAGS, "-version"],
            text=True,
            capture_output=True,
            timeout=5.0,
            **_hidden_subprocess_kwargs(),
        )
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"
    return (completed.stderr or completed.stdout).strip()


def _java_major_version(java: str) -> int | None:
    text = _java_version_text(java)
    return _parse_java_major_version(text)


def _parse_java_major_version(version_text: str) -> int | None:
    import re

    match = re.search(r'version\s+"([^"]+)"', version_text)
    if not match:
        match = re.search(r"openjdk\s+version\s+([^\s]+)", version_text, flags=re.IGNORECASE)
    if not match:
        return None
    version = match.group(1)
    if version.startswith("1."):
        parts = version.split(".")
        return int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None
    major_match = re.match(r"(\d+)", version)
    return int(major_match.group(1)) if major_match else None


def _java_supports_jdk_attach(java: str) -> bool:
    try:
        completed = subprocess.run(
            [java, *JAVA_HELPER_MEMORY_FLAGS, "--list-modules"],
            text=True,
            capture_output=True,
            timeout=8.0,
            **_hidden_subprocess_kwargs(),
        )
    except Exception:
        return False
    if completed.returncode != 0:
        return False
    return any(line.startswith("jdk.attach") for line in completed.stdout.splitlines())


def _project_root(project_root: Path | str | None = None) -> Path:
    return resource_root(project_root)
