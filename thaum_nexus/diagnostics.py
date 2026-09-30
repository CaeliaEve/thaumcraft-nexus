"""Translate recognized failures without discarding their technical evidence."""
from __future__ import annotations

import errno
import subprocess
import traceback
from dataclasses import dataclass

from .client_bridge import OperationCancelled, UnsafeAgentStateError
from .solver import NoSolutionError


@dataclass(frozen=True)
class Diagnostic:
    code: str
    title: str
    advice: str
    details: str


def diagnose_error(exc: BaseException) -> Diagnostic:
    details = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)).rstrip()
    if isinstance(exc, subprocess.TimeoutExpired):
        for name, value in (("STDOUT", exc.output), ("STDERR", exc.stderr)):
            if value:
                rendered = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value)
                details += f"\n{name}:\n{rendered}"

    def result(code: str, title: str, advice: str) -> Diagnostic:
        return Diagnostic(code, title, advice, details)

    if isinstance(exc, UnsafeAgentStateError):
        return result("unsafe_agent_state", "游戏内操作尚未确认停止", "不要继续摆放或重复执行。请先重启目标游戏客户端，确认研究笔记状态后再操作。")
    if isinstance(exc, OperationCancelled):
        return result("cancelled", "操作已取消", "本次操作已停止；查看游戏内笔记确认已完成的步骤。")
    if isinstance(exc, (subprocess.TimeoutExpired, TimeoutError)):
        return result("timeout", "等待操作超时", "检查游戏是否响应及当前研究台状态，查看技术详情确认执行阶段后再决定下一步。")
    if isinstance(exc, NoSolutionError):
        return result("solver_no_solution", "当前搜索未找到方案", "重新读取笔记并核对要素和禁用格；可调整求解策略。搜索达到限制不代表一定无解。")
    if isinstance(exc, PermissionError):
        return result("permission_denied", "无法访问文件或目录", "检查技术详情中的路径、写入权限以及文件是否被其他程序占用。")
    if isinstance(exc, FileNotFoundError):
        executable = str(exc.filename or "").replace("\\", "/").rsplit("/", 1)[-1].lower()
        if executable in {"java", "java.exe", "javaw", "javaw.exe"}:
            return result("java_missing", "未找到 Java 运行程序", "安装或恢复兼容游戏的 JDK，并检查 Java 路径配置。")
        return result("file_missing", "所需文件不存在", "检查技术详情中的文件路径并恢复缺失文件；若为运行程序，请核对其安装路径。")
    if isinstance(exc, OSError):
        if exc.errno == errno.ENOSPC:
            return result("disk_full", "磁盘空间不足", "释放目标磁盘空间，并检查相关文件后重新保存。")
        return result("filesystem_error", "系统读写失败", "检查目标目录、磁盘状态与技术详情；恢复可访问状态后再操作。")

    message = str(exc).lower()
    rules = (
        (("aspect resources are insufficient",), "insufficient_aspects", "可用要素不足", "补充详情中缺少的要素，再读取研究台并重新规划。"),
        (("open the gtnh client first",), "client_missing", "未找到游戏客户端", "启动 GTNH 客户端并打开神秘研究台，再检查目标 JVM 选择。"),
        (("currentscreen is null", "does not expose tileresearchtable"), "research_table_closed", "尚未打开研究台界面", "在游戏内打开神秘研究台并放入研究笔记，保持界面打开后重新读取。"),
        (("unable to read current thaumcraft research note", "does not contain a thaumcraft research note"), "research_note_missing", "未读取到研究笔记", "确认研究台或所选物品栏格中放有未完成的研究笔记，再重新读取。"),
        (("another thaumcraft nexus operation is still using jvm",), "target_busy", "目标游戏正在处理其他操作", "等待其他窗口的操作完成后再继续，避免同时操控同一游戏。"),
        (("java agent build script was not found", "java agent build did not create", "便携包内没有找到 java agent"), "agent_missing", "Java Agent 文件缺失", "恢复完整便携包；从源码运行时检查构建脚本与生成的 Agent 文件。"),
        (("failed to build java agent",), "agent_build_failed", "Java Agent 构建失败", "查看技术详情中的编译输出，检查 JDK 与构建脚本后重新构建。"),
        (("did not create note json", "did not create result json", "finished but did not create json"), "agent_result_missing", "未收到游戏操作结果", "检查游戏中的实际状态与技术详情；写入操作可能已部分完成，请先重新读取笔记再决定下一步。"),
        (("java agent attach failed with exit code",), "attach_failed", "无法连接目标游戏 JVM", "确认游戏仍在运行、目标 PID 正确，并检查技术详情中的 Java 环境和权限信息。"),
    )
    for fragments, code, title, advice in rules:
        if any(fragment in message for fragment in fragments):
            return result(code, title, advice)
    return result("unknown", "操作失败，原因待确认", "查看并保留技术详情，核对游戏状态后再处理；原始错误信息已保留。")
