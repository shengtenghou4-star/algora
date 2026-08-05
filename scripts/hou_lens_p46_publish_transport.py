#!/usr/bin/env python3
"""Recover and verify one exact encrypted HOU-LENS payload from PR comments."""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import re
import urllib.request
import zlib

RUN_ID = os.environ["EXPECTED_RUN_ID"]
RUN_ATTEMPT = os.environ["EXPECTED_RUN_ATTEMPT"]
REPLICA = os.environ.get("EXPECTED_REPLICA", "A")
B64_BYTES = int(os.environ["EXPECTED_B64_BYTES"])
B64_SHA256 = os.environ["EXPECTED_B64_SHA256"]
CMS_BYTES = int(os.environ["EXPECTED_CMS_BYTES"])
CMS_SHA256 = os.environ["EXPECTED_CMS_SHA256"]
BLOCK_COUNT = int(os.environ.get("EXPECTED_BLOCK_COUNT", "28"))
FRAGMENT_BLOCK = int(os.environ.get("FRAGMENT_REPAIR_BLOCK", "24"))
FRAGMENT_COUNT = int(os.environ.get("FRAGMENT_REPAIR_COUNT", "8"))
FRAGMENT_LENGTH = int(os.environ.get("FRAGMENT_REPAIR_LENGTH", "4160"))
FRAGMENT_CRC32 = os.environ.get("FRAGMENT_REPAIR_CRC32", "d50ce311")
HEADER = re.compile(r"^HOU-LENS-P46-TRANSPORT v1 run=(\d+) attempt=(\d+) replica=([A-Z]) group=(\d+)$")
BLOCK = re.compile(r"^P(\d{3}) crc32=([0-9a-f]{8}) len=(\d+)$")
FRAGMENT = re.compile(r"^F(\d{3})-(\d{2}) crc32=([0-9a-f]{8}) len=(\d+)$")


def fetch_comments(repo: str, issue: str, token: str) -> list[dict]:
    out: list[dict] = []
    page = 1
    while True:
        req = urllib.request.Request(
            f"https://api.github.com/repos/{repo}/issues/{issue}/comments?per_page=100&page={page}",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "hou-lens-p46-transport",
            },
        )
        with urllib.request.urlopen(req, timeout=30) as response:
            batch = json.load(response)
        out.extend(batch)
        if len(batch) < 100:
            return out
        page += 1


def main() -> None:
    recovered: dict[int, str] = {}
    provenance: dict[int, object] = {}
    fragments: dict[int, dict[int, str]] = {}
    fragment_provenance: dict[int, dict[int, object]] = {}
    for comment in fetch_comments(
        os.environ["GITHUB_REPOSITORY"],
        os.environ.get("P46_TRANSPORT_ISSUE", "11"),
        os.environ["GH_TOKEN"],
    ):
        lines = (comment.get("body") or "").splitlines()
        if not lines:
            continue
        header = HEADER.fullmatch(lines[0].strip())
        if (
            not header
            or header.group(1) != RUN_ID
            or header.group(2) != RUN_ATTEMPT
            or header.group(3) != REPLICA
        ):
            continue
        cursor = 1
        while cursor + 1 < len(lines):
            meta_line = lines[cursor].strip()
            text = lines[cursor + 1].strip()
            raw = text.encode("ascii")
            meta = BLOCK.fullmatch(meta_line)
            if meta:
                index = int(meta.group(1))
                valid = len(raw) == int(meta.group(3)) and f"{zlib.crc32(raw) & 0xffffffff:08x}" == meta.group(2)
                if valid:
                    if index in recovered and recovered[index] != text:
                        raise SystemExit(f"conflicting valid transport block {index}")
                    recovered[index] = text
                    provenance[index] = int(comment["id"])
                cursor += 2
                continue
            fragment = FRAGMENT.fullmatch(meta_line)
            if fragment:
                block_index = int(fragment.group(1))
                fragment_index = int(fragment.group(2))
                valid = len(raw) == int(fragment.group(4)) and f"{zlib.crc32(raw) & 0xffffffff:08x}" == fragment.group(3)
                if valid:
                    bucket = fragments.setdefault(block_index, {})
                    if fragment_index in bucket and bucket[fragment_index] != text:
                        raise SystemExit(f"conflicting valid fragment F{block_index:03d}-{fragment_index:02d}")
                    bucket[fragment_index] = text
                    fragment_provenance.setdefault(block_index, {})[fragment_index] = int(comment["id"])
                cursor += 2
                continue
            cursor += 1

    if FRAGMENT_BLOCK >= 0 and FRAGMENT_BLOCK not in recovered:
        bucket = fragments.get(FRAGMENT_BLOCK, {})
        expected_indices = list(range(FRAGMENT_COUNT))
        missing_fragments = [i for i in expected_indices if i not in bucket]
        frozen_fragment = Path("control/.github/hou-lens-p46-transport-fragments/F024-02.txt")
        if missing_fragments == [2] and frozen_fragment.is_file():
            text = frozen_fragment.read_text().strip()
            raw = text.encode("ascii")
            if len(raw) != 520 or f"{zlib.crc32(raw) & 0xffffffff:08x}" != "1c889a24":
                raise SystemExit("frozen F024-02 fragment identity mismatch")
            bucket[2] = text
            fragment_provenance.setdefault(FRAGMENT_BLOCK, {})[2] = "main:.github/hou-lens-p46-transport-fragments/F024-02.txt"
            missing_fragments = [i for i in expected_indices if i not in bucket]
        if missing_fragments:
            raise SystemExit(f"missing fragment repair pieces for block {FRAGMENT_BLOCK}: {missing_fragments}")
        repaired = "".join(bucket[i] for i in expected_indices)
        repaired_raw = repaired.encode("ascii")
        repaired_crc = f"{zlib.crc32(repaired_raw) & 0xffffffff:08x}"
        if len(repaired_raw) != FRAGMENT_LENGTH or repaired_crc != FRAGMENT_CRC32:
            raise SystemExit(
                f"fragment repair identity mismatch for block {FRAGMENT_BLOCK}: "
                f"len={len(repaired_raw)} crc32={repaired_crc}"
            )
        recovered[FRAGMENT_BLOCK] = repaired
        provenance[FRAGMENT_BLOCK] = [fragment_provenance[FRAGMENT_BLOCK][i] for i in expected_indices]

    missing = [i for i in range(BLOCK_COUNT) if i not in recovered]
    if missing:
        raise SystemExit(f"missing or corrupt transport blocks: {missing}")
    assembled = "".join(recovered[i] for i in range(BLOCK_COUNT)).encode("ascii")
    if len(assembled) != B64_BYTES or hashlib.sha256(assembled).hexdigest() != B64_SHA256:
        raise SystemExit("global Base64 identity mismatch")
    der = base64.b64decode(assembled, validate=True)
    if len(der) != CMS_BYTES or hashlib.sha256(der).hexdigest() != CMS_SHA256:
        raise SystemExit("CMS DER identity mismatch")
    Path("/tmp/payload.b64").write_bytes(assembled)
    Path("/tmp/p46-transport-audit.json").write_text(json.dumps({
        "schema_version": 5,
        "status": "PASS_EXACT_COMMENT_TRANSPORT",
        "run_id": RUN_ID,
        "run_attempt": RUN_ATTEMPT,
        "replica": REPLICA,
        "block_count": BLOCK_COUNT,
        "fragment_repair_block": FRAGMENT_BLOCK if FRAGMENT_BLOCK >= 0 else None,
        "base64_bytes": len(assembled),
        "base64_sha256": hashlib.sha256(assembled).hexdigest(),
        "cms_der_bytes": len(der),
        "cms_der_sha256": hashlib.sha256(der).hexdigest(),
        "source_comment_ids": provenance,
    }, indent=2, sort_keys=True) + "\n")
    print("PASS_EXACT_COMMENT_TRANSPORT")


if __name__ == "__main__":
    main()
