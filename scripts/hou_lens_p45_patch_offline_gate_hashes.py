#!/usr/bin/env python3
"""Patch only the two stale Requests metadata identities in the P4.5 workflow."""
from pathlib import Path
import sys

REPLACEMENTS = {
    "63a1f6ffda021310f8da34b4d7028ec15cd1abc8d75ba6fd753320df54be90a8":
        "63a464ae49d4b7b760de5eb2465a35c2e0e952b1bbdaf1baf2543fc1abb44c91",
    "a92ef67259db37906756b52b7d098bc7c5093afcfef6904819ed64f44bf2e8aa":
        "a92efee14a834137f3d78abdc2dcfc163e60ba3a4b4a91910d165393e8b3c497",
}


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: hou_lens_p45_patch_offline_gate_hashes.py WORKFLOW")
    path = Path(sys.argv[1])
    text = path.read_text()
    for old, new in REPLACEMENTS.items():
        old_count = text.count(old)
        new_count = text.count(new)
        if old_count:
            text = text.replace(old, new)
        elif not new_count:
            raise SystemExit(f"neither stale nor corrected identity found: {old}")
    for old, new in REPLACEMENTS.items():
        if old in text:
            raise SystemExit(f"stale identity remains: {old}")
        if new not in text:
            raise SystemExit(f"corrected identity missing: {new}")
    path.write_text(text)
    print("PASS_PATCHED_EXACT_OFFLINE_GATE_METADATA_IDENTITIES")


if __name__ == "__main__":
    main()
