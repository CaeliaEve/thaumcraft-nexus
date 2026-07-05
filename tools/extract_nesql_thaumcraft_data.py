#!/usr/bin/env python3
"""Extract Thaumcraft aspect data from a local NESQL export.

This script is intentionally read-only for the NESQL source tree. It writes
normalized data files into this project only.
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ITEM_ID_RE = re.compile(r"^i~thaumcraftneiplugin~Aspect~(?P<meta>\d+)~(?P<hash>.+)$")
NBT_KEY_RE = re.compile(r'key:"([^"]+)"')
ICON_RE = re.compile(r"^Aspect~(?P<meta>\d+)~(?P<hash>.+)\.png$")
COMBO_HANDLER_ID = "rt~thaumcraft~ru_timeconqueror_tcneiadditions_nei_aspectcombinationhandler"

NESQL_ENV_VAR = "THAUM_NEXUS_NESQL"


def read_json_gz(path: Path) -> Any:
    with gzip.open(path, "rt", encoding="utf-8", errors="replace") as fh:
        return json.load(fh)


def iter_jsonl_gz(path: Path):
    with gzip.open(path, "rt", encoding="utf-8", errors="replace") as fh:
        for line_no, line in enumerate(fh, 1):
            if line.strip():
                yield line_no, json.loads(line)


def aspect_hash_from_item_id(item_id: str) -> str | None:
    match = ITEM_ID_RE.match(item_id)
    return match.group("hash") if match else None


def icon_hashes(image_dir: Path) -> dict[str, str]:
    icons: dict[str, str] = {}
    for path in sorted(image_dir.glob("Aspect~*.png")):
        match = ICON_RE.match(path.name)
        if match:
            icons[match.group("hash")] = path.name
    return icons


def extract_aspects(items_path: Path, image_dir: Path) -> tuple[dict[str, dict[str, Any]], dict[str, str], list[dict[str, Any]]]:
    """Return canonical aspects keyed by aspect key, hash->key, and ignored duplicate rows."""
    items = read_json_gz(items_path)
    icons_by_hash = icon_hashes(image_dir)
    if not icons_by_hash:
        raise RuntimeError(f"No Aspect PNG icons found in {image_dir}")

    aspects: dict[str, dict[str, Any]] = {}
    hash_to_key: dict[str, str] = {}
    ignored: list[dict[str, Any]] = []

    for item in items:
        item_id = item.get("itemId", "")
        match = ITEM_ID_RE.match(item_id)
        if not match:
            continue

        aspect_hash = match.group("hash")
        meta = int(match.group("meta"))
        key_match = NBT_KEY_RE.search(item.get("nbt", ""))
        key = key_match.group(1) if key_match else None
        if not key:
            ignored.append({"itemId": item_id, "reason": "missing NBT aspect key"})
            continue

        localized = item.get("localizedName", "")
        english_name = localized.split(":", 1)[-1].strip() if ":" in localized else localized.strip()
        tooltip_text = item.get("tooltip", "")
        tooltip_lines = tooltip_text.splitlines()
        description = tooltip_lines[1] if len(tooltip_lines) > 1 else ""

        # The project image folder is the canonical icon set. This deliberately
        # drops the duplicate Aer hash that can exist in the NESQL export.
        if aspect_hash not in icons_by_hash:
            ignored.append({
                "itemId": item_id,
                "key": key,
                "name": english_name,
                "hash": aspect_hash,
                "reason": "hash not present in project image/ canonical icon set",
            })
            hash_to_key[aspect_hash] = key
            continue

        hash_to_key[aspect_hash] = key
        existing = aspects.get(key)
        candidate = {
            "key": key,
            "name": english_name,
            "localizedName": localized,
            "description": description,
            "hash": aspect_hash,
            "icon": f"image/{icons_by_hash[aspect_hash]}",
            "itemId": item_id,
            "meta": meta,
            "primal": False,
            "components": [],
        }

        # Prefer meta 0, because current icon files are Aspect~0~*.png.
        if existing is None or (existing.get("meta") != 0 and meta == 0):
            aspects[key] = candidate

    missing_icons = [h for h in icons_by_hash if h not in hash_to_key]
    if missing_icons:
        raise RuntimeError(f"Icon hashes missing item metadata: {missing_icons}")

    return dict(sorted(aspects.items())), hash_to_key, ignored


def item_id_to_key(item_id: str, hash_to_key: dict[str, str]) -> str:
    aspect_hash = aspect_hash_from_item_id(item_id)
    if not aspect_hash or aspect_hash not in hash_to_key:
        raise KeyError(f"Unknown aspect item id: {item_id}")
    return hash_to_key[aspect_hash]


def extract_combinations(payloads_path: Path, hash_to_key: dict[str, str]) -> tuple[list[dict[str, Any]], list[str]]:
    combos: list[dict[str, Any]] = []
    primal: list[str] = []

    for line_no, obj in iter_jsonl_gz(payloads_path):
        if obj.get("machineId") != COMBO_HANDLER_ID:
            continue
        refs = obj.get("primaryRefs") or {}
        input_ids = refs.get("itemInputIds") or []
        output_ids = refs.get("itemOutputIds") or []
        if len(output_ids) != 1:
            raise RuntimeError(f"Unexpected output count at payload line {line_no}: {output_ids}")

        output = item_id_to_key(output_ids[0], hash_to_key)
        components = [item_id_to_key(item_id, hash_to_key) for item_id in input_ids]

        if len(components) == 0:
            primal.append(output)
            continue
        if len(components) != 2:
            raise RuntimeError(f"Unexpected component count at payload line {line_no}: {components}")

        combos.append({
            "output": output,
            "components": components,
            "sortedPair": "+".join(sorted(components)),
            "payloadLine": line_no,
            "recipeId": obj.get("recipeId"),
        })

    return sorted(combos, key=lambda row: row["output"]), sorted(set(primal))


def build_adjacency(aspects: dict[str, dict[str, Any]], combos: list[dict[str, Any]]) -> tuple[list[list[str]], dict[str, list[str]]]:
    edges: set[tuple[str, str]] = set()
    for combo in combos:
        output = combo["output"]
        for component in combo["components"]:
            if output == component:
                continue
            edges.add(tuple(sorted((output, component))))

    neighbors: dict[str, set[str]] = {key: set() for key in aspects}
    for a, b in edges:
        neighbors[a].add(b)
        neighbors[b].add(a)

    return [list(edge) for edge in sorted(edges)], {k: sorted(v) for k, v in sorted(neighbors.items())}


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract normalized Thaumcraft aspect data from NESQL.")
    parser.add_argument(
        "--nesql",
        type=Path,
        default=Path(os.environ[NESQL_ENV_VAR]) if os.environ.get(NESQL_ENV_VAR) else None,
        required=not bool(os.environ.get(NESQL_ENV_VAR)),
        help=f"Path to nesql/elysiumfresh export root. Can also be provided by {NESQL_ENV_VAR}.",
    )
    parser.add_argument("--project", type=Path, default=Path(__file__).resolve().parents[1], help="Project root")
    args = parser.parse_args()

    project = args.project.resolve()
    nesql = args.nesql.resolve()
    image_dir = project / "image"
    data_dir = project / "data"
    items_path = nesql / "items" / "thaumcraftneiplugin" / "items.json.gz"
    payloads_path = nesql / "raw-export" / "special" / "thaumcraft" / "payloads.jsonl.gz"

    if not items_path.exists():
        raise FileNotFoundError(items_path)
    if not payloads_path.exists():
        raise FileNotFoundError(payloads_path)

    generated_at = datetime.now(timezone.utc).isoformat()
    source = {
        "nesqlRoot": "local NESQL export, supplied by --nesql or THAUM_NEXUS_NESQL",
        "items": "items/thaumcraftneiplugin/items.json.gz",
        "payloads": "raw-export/special/thaumcraft/payloads.jsonl.gz",
        "projectImageDir": "image",
        "generatedAtUtc": generated_at,
        "note": "NESQL source files are read-only inputs; generated files live under this project data/ directory.",
    }

    aspects, hash_to_key, ignored = extract_aspects(items_path, image_dir)
    combos, primal = extract_combinations(payloads_path, hash_to_key)

    by_output = {row["output"]: row["components"] for row in combos}
    by_pair = {row["sortedPair"]: row["output"] for row in combos}
    for key in primal:
        if key in aspects:
            aspects[key]["primal"] = True
    for output, components in by_output.items():
        if output in aspects:
            aspects[output]["components"] = components

    edges, neighbors = build_adjacency(aspects, combos)

    write_json(data_dir / "aspects.json", {
        "schema": "thaumcraft-nexus/aspects/v1",
        "source": source,
        "count": len(aspects),
        "aspects": aspects,
        "hashToKey": dict(sorted(hash_to_key.items())),
        "ignoredRows": ignored,
    })

    write_json(data_dir / "combinations.json", {
        "schema": "thaumcraft-nexus/combinations/v1",
        "source": source,
        "primal": primal,
        "combinationCount": len(combos),
        "combinations": combos,
        "byOutput": dict(sorted(by_output.items())),
        "bySortedPair": dict(sorted(by_pair.items())),
    })

    write_json(data_dir / "adjacency.json", {
        "schema": "thaumcraft-nexus/adjacency/v1",
        "source": source,
        "rule": "A and B may be adjacent in a research note when A is a direct component of B or B is a direct component of A.",
        "edgeCount": len(edges),
        "edges": edges,
        "neighbors": neighbors,
    })

    write_json(data_dir / "manifest.json", {
        "schema": "thaumcraft-nexus/data-manifest/v1",
        "source": source,
        "files": {
            "aspects": "data/aspects.json",
            "combinations": "data/combinations.json",
            "adjacency": "data/adjacency.json",
        },
        "counts": {
            "aspects": len(aspects),
            "canonicalIcons": len(icon_hashes(image_dir)),
            "primal": len(primal),
            "combinations": len(combos),
            "adjacencyEdges": len(edges),
            "ignoredRows": len(ignored),
        },
    })

    print(json.dumps({
        "dataDir": str(data_dir),
        "aspects": len(aspects),
        "primal": len(primal),
        "combinations": len(combos),
        "adjacencyEdges": len(edges),
        "ignoredRows": len(ignored),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
