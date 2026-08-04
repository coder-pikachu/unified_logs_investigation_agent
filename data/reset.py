#!/usr/bin/env python
"""Reset the demo to a clean pre-run state in ONE command (brief §10 trap #7).

Clears every agent-written collection (so the memory contrast between run #1 and
run #2 is real), plus the audit/metrics streams and watcher resume tokens, then
re-seeds the curated kb_docs knowledge base. Search/vector INDEXES are left
untouched — only documents are removed.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "agent"))

from nova_agent.config import settings  # noqa: E402
from nova_agent.db import get_db  # noqa: E402

# agent-written + live streams to wipe (indexes remain)
CLEAR = [
    settings.C_TXN, settings.C_ERR, settings.C_SVC, settings.C_METRICS,
    settings.C_INCIDENTS, settings.C_MEMORY, settings.C_KB, settings.C_FEEDBACK,
    settings.C_STATE, settings.C_CHECKPOINTS, settings.C_CHECKPOINT_WRITES, settings.C_STORE,
    settings.C_CHAT, settings.C_CHAT_IMG,
]


def main() -> None:
    db = get_db()
    print(f"Reset on {settings.mongodb_db}")
    for name in CLEAR:
        n = db[name].delete_many({}).deleted_count
        print(f"  cleared {n:>5} from {name}")

    # re-seed the knowledge base so hybrid recall has kb content on the first run
    sys.path.insert(0, str(REPO_ROOT / "data"))
    from seed import load_kb  # noqa: E402

    n = load_kb(db)
    print(f"  seeded  {n:>5} into {settings.C_KB}")
    print("Reset complete — clean board, memory empty, kb restored.")


if __name__ == "__main__":
    main()
