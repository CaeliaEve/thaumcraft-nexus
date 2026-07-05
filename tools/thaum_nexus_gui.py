#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


if not getattr(sys, "frozen", False):
    PROJECT_ROOT = Path(__file__).resolve().parents[1]
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))

from thaum_nexus.gui_app import main


def self_test() -> int:
    from thaum_nexus.client_bridge import agent_jar_path
    from thaum_nexus.knowledge_base import KnowledgeBase
    from thaum_nexus.paths import resource_root

    root = resource_root()
    kb = KnowledgeBase.load(root)
    if len(kb.aspects) < 1:
        raise RuntimeError("knowledge base is empty")
    icon = root / "image" / "icons8-github-50.png"
    if not icon.exists():
        raise RuntimeError(f"missing GUI icon: {icon}")
    jar = agent_jar_path(root)
    if not jar.exists():
        raise RuntimeError(f"missing Java Agent jar: {jar}")
    return 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(self_test())
    raise SystemExit(main())
