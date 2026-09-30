"""Presentation of the existing resource simulation without reading the game."""
from collections import Counter
from dataclasses import dataclass

from .knowledge_base import KnowledgeBase


@dataclass(frozen=True)
class ResourceRow:
    key: str
    name: str
    required: int
    available: int
    synthesis: int
    shortage: int


@dataclass(frozen=True)
class ResourcePreview:
    summary: tuple[str, ...]
    rows: tuple[ResourceRow, ...]
    details: str


def describe_resources(kb: KnowledgeBase, payload: dict) -> ResourcePreview:
    plan = payload.get("resources")
    if not isinstance(plan, dict):
        return ResourcePreview(("资源库存未读取", "重新读取笔记可生成资源计划"), (), "尚无库存快照，无法判断资源是否充足。")
    required, available = plan.get("required", {}), plan.get("available", {})
    shortages = plan.get("shortages", {})
    steps = plan.get("synthesis", [])
    outputs = Counter(step["output"] for step in steps)
    keys = set(required) | set(shortages) | set(outputs)
    for step in steps:
        keys.update((step["left"], step["right"]))
    rows = tuple(ResourceRow(key, kb.aspects[key].name if key in kb.aspects else key,
                             required.get(key, 0), available.get(key, 0), outputs[key], shortages.get(key, 0))
                 for key in sorted(keys))
    timing = "执行前资源计划" if "apply" in payload else "资源预估"
    summary = (f"{timing} · 放置 {sum(required.values())} · 合成 {len(steps)} 次",
               f"有 {len(shortages)} 类阻塞缺口" if shortages else "库存可满足计划")
    details = ["库存为读取时的快照，不代表执行后的实时余量。", "需求仅指棋盘放置；合成列包含中间要素。"]
    if shortages:
        details.append("缺口为当前合成路径已识别的阻塞资源；补充后请重新读取，可能仍有其他缺口。")
    if "apply" in payload:
        result = payload["apply"]
        details.append(f"实际执行回执：合成 {result.get('combinesSent', 0)} 次，放置 {result.get('placementsSent', 0)} 个，跳过 {result.get('placementsSkipped', 0)} 个。")
    if steps:
        details.append("\n预计合成顺序：")
        for index, step in enumerate(steps, 1):
            def name(key):
                return kb.aspects[key].name if key in kb.aspects else key
            details.append(f"{index}. {name(step['left'])} + {name(step['right'])} → {name(step['output'])}")
    warnings = payload.get("solution", {}).get("warnings", ())
    if warnings:
        details.append("\n求解说明：\n" + "\n".join(map(str, warnings)))
    return ResourcePreview(summary, rows, "\n".join(details))
