"""Copy legacy persona/wiki/pages content into persona/wiki/wiki.

The initial wiki prototype stored pages under persona/wiki/pages. The canonical
layout now stores crystallized pages under persona/wiki/wiki and keeps raw
sources/state/schema separate. This script copies legacy pages and sidecars
without deleting the originals.
"""

from __future__ import annotations

import shutil
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    wiki_root = root / "persona" / "wiki"
    legacy = wiki_root / "pages"
    current = wiki_root / "wiki"
    if not legacy.exists():
        print("No legacy persona/wiki/pages directory found.")
        return
    copied = 0
    skipped = 0
    for source in legacy.rglob("*"):
        if not source.is_file():
            continue
        rel = source.relative_to(legacy)
        target = current / rel
        if target.exists():
            skipped += 1
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        copied += 1
    print(f"Copied {copied} legacy wiki file(s); skipped {skipped} existing file(s).")


if __name__ == "__main__":
    main()
