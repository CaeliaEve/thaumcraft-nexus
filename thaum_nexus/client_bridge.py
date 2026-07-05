from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .data_model import Solution
from .knowledge_base import KnowledgeBase
from .note_io import ResearchNote
from .paths import app_root, is_frozen, resource_root, runtime_root
from .resources import ResourcePlan, plan_resource_usage
from .solver import SearchConfig, solve


@dataclass(frozen=True)
class CurrentNoteResult:
    note: ResearchNote
    solution: Any
    note_json_path: Path
    resource_plan: ResourcePlan | None = None
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


def export_current_note(
    project_root: Path | str | None = None,
    *,
    output_path: Path | str | None = None,
    pid: str | int | None = None,
    build_if_needed: bool = True,
    timeout: float = 20.0,
) -> tuple[dict[str, Any], Path, str, str]:
    """Attach to the running Minecraft client and export current research-note JSON."""

    root = _project_root(project_root)
    if output_path is None:
        output = _resolve_runtime_path(project_root, None, "current_note.json")
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
    )
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
) -> CurrentNoteResult:
    root = _project_root(project_root)
    payload, note_path, stdout, stderr = export_current_note(
        project_root,
        output_path=output_path,
        pid=pid,
        build_if_needed=build_if_needed,
        timeout=timeout,
    )
    note = ResearchNote.from_dict(payload)
    kb = KnowledgeBase.load(root)
    available_aspects = available_aspects_from_note_payload(payload)
    config = SearchConfig(aspect_inventory=available_aspects) if available_aspects else None
    solution = solve(note.board, kb, config)
    resource_plan = (
        plan_resource_usage(kb, solution.placements.values(), available_aspects)
        if available_aspects
        else None
    )
    return CurrentNoteResult(
        note=note,
        solution=solution,
        note_json_path=note_path,
        resource_plan=resource_plan,
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
) -> tuple[dict[str, Any], Path, Path, str, str]:
    """Send solver placements to the open Thaumcraft research table."""

    root = _project_root(project_root)
    plan = _resolve_runtime_path(project_root, plan_path, "apply_plan.json")
    result = _resolve_runtime_path(project_root, result_path, "apply_result.json")
    plan.parent.mkdir(parents=True, exist_ok=True)
    result.parent.mkdir(parents=True, exist_ok=True)
    if result.exists():
        result.unlink()

    if resource_plan is not None and not resource_plan.is_sufficient:
        raise RuntimeError(f"aspect resources are insufficient: {resource_plan.shortages}")

    plan_payload = solution_to_apply_plan(
        solution,
        resource_plan=resource_plan,
        delay_ms=delay_ms,
        verify_delay_ms=verify_delay_ms,
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
) -> ApplyResult:
    current = read_and_solve_current_note(
        project_root,
        output_path=note_output_path,
        pid=pid,
        build_if_needed=build_if_needed,
        timeout=min(timeout, 20.0),
    )
    apply_payload, apply_plan, apply_result, stdout, stderr = apply_solution_to_current_note(
        current.solution,
        project_root,
        resource_plan=current.resource_plan,
        plan_path=plan_path,
        result_path=result_path,
        pid=pid,
        delay_ms=delay_ms,
        verify_delay_ms=verify_delay_ms,
        build_if_needed=build_if_needed,
        timeout=timeout,
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
    return payload


def available_aspects_from_note_payload(payload: dict[str, Any]) -> dict[str, int]:
    aspects = payload.get("aspects")
    if not isinstance(aspects, dict):
        return {}
    available = aspects.get("available")
    if not isinstance(available, dict):
        return {}
    out: dict[str, int] = {}
    for key, value in available.items():
        try:
            amount = int(value)
        except (TypeError, ValueError):
            continue
        if amount > 0:
            out[str(key)] = amount
    return out


def export_inventory_notes(
    project_root: Path | str | None = None,
    *,
    output_path: Path | str | None = None,
    pid: str | int | None = None,
    build_if_needed: bool = True,
    timeout: float = 20.0,
) -> tuple[dict[str, Any], Path, str, str]:
    """Export research-note stacks from the open research-table container."""

    root = _project_root(project_root)
    output = _resolve_runtime_path(project_root, output_path, "inventory_notes.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()
    completed = _run_attacher(
        root,
        ["inventory", str(output)],
        pid=pid,
        build_if_needed=build_if_needed,
        timeout=timeout,
    )
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
) -> tuple[dict[str, Any], Path, str, str]:
    """Move/swap one container slot into the research-table note slot."""

    root = _project_root(project_root)
    result = _resolve_runtime_path(project_root, result_path, "load_note_result.json")
    result.parent.mkdir(parents=True, exist_ok=True)
    if result.exists():
        result.unlink()
    completed = _run_attacher(
        root,
        ["load-note", str(int(slot)), str(result)],
        pid=pid,
        build_if_needed=build_if_needed,
        timeout=timeout,
    )
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
    )
    notes = [note for note in inventory.get("notes", []) if isinstance(note, dict)]
    unsolved = [note for note in notes if not bool(note.get("complete"))]
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

    for iteration in range(max_notes):
        if _is_cancelled(stop_event):
            return _cancelled_wheelchair_payload(solved, steps, "stopped before next note")
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
            )
            if not current.note.complete:
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
                )
                placements_sent = int(apply_payload.get("placementsSent", 0) or 0)
                combines_sent = int(apply_payload.get("combinesSent", 0) or 0)
                solved += 1
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
                continue
        except Exception as exc:
            steps.append({"iteration": iteration, "action": "read-current-note", "status": "skipped", "error": str(exc)})

        if _is_cancelled(stop_event):
            return _cancelled_wheelchair_payload(solved, steps, "stopped before scanning inventory")
        _emit_progress(
            progress_callback,
            "inventory-rescan",
            f"第 {iteration + 1} 轮：重新扫描背包未解笔记",
            iteration=iteration,
        )
        inventory, inventory_path, stdout, stderr = export_inventory_notes(
            project_root,
            output_path=f"runtime/wheelchair_inventory_{iteration:02d}.json",
            pid=pid,
            build_if_needed=build_if_needed,
            timeout=min(timeout, 20.0),
        )
        notes = [note for note in inventory.get("notes", []) if isinstance(note, dict)]
        next_note = _first_unsolved_inventory_note(notes)
        if next_note is None:
            return {
                "source": "thaum-nexus",
                "status": "ok",
                "action": "wheelchair-apply",
                "message": "no unsolved inventory notes remain",
                "solvedOrAttempted": solved,
                "steps": steps,
                "lastInventoryJson": str(inventory_path),
                "attacher": {"stdout": stdout, "stderr": stderr},
            }

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

    return {
        "source": "thaum-nexus",
        "status": "incomplete",
        "action": "wheelchair-apply",
        "message": f"stopped after max_notes={max_notes}",
        "solvedOrAttempted": solved,
        "steps": steps,
    }


def _first_unsolved_inventory_note(notes: list[dict[str, Any]]) -> dict[str, Any] | None:
    candidates = [
        note for note in notes
        if not bool(note.get("complete")) and str(note.get("slotKind") or "") != "table-note"
    ]
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: int(item.get("slot", 0)))[0]


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
    if os.environ.get("JAVA_HOME"):
        candidate = Path(os.environ["JAVA_HOME"]) / "bin" / "java.exe"
        if candidate.exists():
            return str(candidate)
    return shutil.which("java") or "java"


def find_tools_jar() -> Path | None:
    candidates: list[Path] = []
    if os.environ.get("JAVA_HOME"):
        candidates.append(Path(os.environ["JAVA_HOME"]) / "lib" / "tools.jar")
    javac = shutil.which("javac")
    if javac:
        java_home = Path(javac).resolve().parent.parent
        candidates.append(java_home / "lib" / "tools.jar")
    java = shutil.which("java")
    if java:
        java_home = Path(java).resolve().parent.parent
        candidates.append(java_home / "lib" / "tools.jar")
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _run_attacher(
    root: Path,
    attacher_args: list[str],
    *,
    pid: str | int | None,
    build_if_needed: bool,
    timeout: float,
) -> subprocess.CompletedProcess[str]:
    agent_jar = ensure_agent_built(root) if build_if_needed else agent_jar_path(root)
    tools_jar = find_tools_jar()
    java = find_java()
    classpath_parts = [str(agent_jar)]
    if tools_jar is not None:
        classpath_parts.insert(0, str(tools_jar))

    cmd = [
        java,
        "-cp",
        os.pathsep.join(classpath_parts),
        "thaumnexus.agent.ThaumNexusAttacher",
        str(agent_jar),
        *attacher_args,
    ]
    if pid is not None:
        cmd.append(str(pid))

    cwd = app_root() if is_frozen() else root
    completed = subprocess.run(cmd, cwd=str(cwd), text=True, capture_output=True, timeout=timeout)
    if completed.returncode != 0:
        raise RuntimeError(
            "Java agent attach failed with exit code "
            f"{completed.returncode}\nSTDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}"
        )
    return completed


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


def _project_root(project_root: Path | str | None = None) -> Path:
    return resource_root(project_root)
