"""Read-only structural comparison of two extracted badge trees.

Usage: python tools/inspect_badge_dumps.py BEFORE AFTER
Inputs must be copies under this repository's ignored sandbox directory.
"""
import argparse
import hashlib
import json
from itertools import zip_longest
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.badges import Badges


def ranges(before, after):
    if before == after:
        return []
    out = []
    for n, (a, b) in enumerate(zip_longest(before, after)):
        if a == b:
            continue
        if out and n == out[-1][1] + 1:
            out[-1][1] = n
        else:
            out.append([n, n])
    return [{"offset": hex(a), "size": b - a + 1} for a, b in out]


def read_tree(root):
    root = root.resolve()
    if not root.is_relative_to((ROOT / "sandbox").resolve()):
        raise ValueError("Use extracted copies under sandbox; do not inspect the real card with this tool.")
    data = (root / "user" / "BadgeData.dat").read_bytes()
    mng = (root / "user" / "BadgeMngFile.dat").read_bytes()
    result = {"data_size": len(data), "management_size": len(mng),
              "data_sha256": hashlib.sha256(data).hexdigest(),
              "management_sha256": hashlib.sha256(mng).hexdigest()}
    try:
        parsed = Badges(data, mng)
        result.update(unique_badges=len(parsed.catalog), placements=parsed.layout,
                      counts={n: {"quantity": b["quantity"], "placed": b["placed"], "sub": hex(b["sub"])}
                              for n, b in parsed.catalog.items()})
    except ValueError as exc:
        result["parser_error"] = str(exc)
    return data, mng, result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path)
    args = parser.parse_args()
    try:
        ad, am, a = read_tree(args.before)
        bd, bm, b = read_tree(args.after)
        print(json.dumps({"before": a, "after": b, "data_changes": ranges(ad, bd),
                          "management_changes": ranges(am, bm)}, indent=2))
    except (OSError, ValueError) as exc:
        parser.exit(1, str(exc) + "\n")


if __name__ == "__main__":
    main()
