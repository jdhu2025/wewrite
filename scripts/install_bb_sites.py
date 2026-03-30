#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPO_ROOT / "bb-sites"
DEFAULT_TARGET = Path("/config/.bb-browser/bb-sites")


def iter_site_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in sorted(root.rglob("*.js")):
        relative = path.relative_to(root)
        if any(part.startswith("_") for part in relative.parts):
            continue
        files.append(path)
    return files


def sync_sites(source_root: Path, target_root: Path, dry_run: bool = False) -> list[tuple[Path, Path]]:
    copied: list[tuple[Path, Path]] = []
    for source in iter_site_files(source_root):
        relative = source.relative_to(source_root)
        target = target_root / relative
        copied.append((source, target))
        if dry_run:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    return copied


def main() -> int:
    parser = argparse.ArgumentParser(description="Install repo-local bb-sites into the runtime bb-browser directory.")
    parser.add_argument("--target", type=Path, default=DEFAULT_TARGET, help=f"Target directory (default: {DEFAULT_TARGET})")
    parser.add_argument("--dry-run", action="store_true", help="Show which files would be copied without writing")
    args = parser.parse_args()

    if not SOURCE_ROOT.exists():
        raise SystemExit(f"Source directory not found: {SOURCE_ROOT}")

    copied = sync_sites(SOURCE_ROOT, args.target, dry_run=args.dry_run)
    action = "Would copy" if args.dry_run else "Copied"
    print(f"{action} {len(copied)} adapter(s) into {args.target}")
    for source, target in copied:
        print(f"- {source.relative_to(SOURCE_ROOT)} -> {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
