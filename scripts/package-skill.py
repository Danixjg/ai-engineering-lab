#!/usr/bin/env python3
"""Validate and package exactly one skill with deterministic archive entries."""

from __future__ import annotations

import argparse
import zipfile
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("skill_dir", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    skill_dir = args.skill_dir.resolve()
    output = args.output.resolve()
    if not (skill_dir / "SKILL.md").is_file():
        parser.error(f"{skill_dir} is not a skill directory")
    if output.name != "skill.zip":
        parser.error("output archive must be named skill.zip")
    if output.is_relative_to(skill_dir):
        parser.error("output archive must be outside the skill directory")

    files = sorted(path for path in skill_dir.rglob("*") if path.is_file())
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, path.relative_to(skill_dir).as_posix())

    with zipfile.ZipFile(output) as archive:
        names = archive.namelist()
        if "SKILL.md" not in names or any(name.startswith("../") for name in names):
            raise RuntimeError("package does not contain a safe skill root")
    if output.stat().st_size >= 25 * 1024 * 1024:
        raise RuntimeError("package must remain below 25 MB")
    print(f"packaged {skill_dir.name}: {output} ({output.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
