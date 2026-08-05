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
B64_BYTES = int(os.environ["EXPECTED_B64_BYTES"])
B64_SHA256 = os.environ["EXPECTED_B64_SHA256"]
CMS_BYTES = int(os.environ["EXPECTED_CMS_BYTES"])
CMS_SHA256 = os.environ["EXPECTED_CMS_SHA256"]
BLOCK_COUNT = int(os.environ.get("EXPECTED_BLOCK_COUNT", "28"))
HEADER = re.compile(r"^HOU-LENS-P46-TRANSPORT v1 run=(\d+) attempt=(\d+) replica=A group=(\d+)$")
BLOCK = re.compile(r"^P(\d{3}) crc32=([0-9a-f]{8}) len=(\d+)$")


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
    provenance: dict[int, int] = {}
    for comment in fetch_comments(
        os.environ["GITHUB_REPOSITORY"],
        os.environ.get("P46_TRANSPORT_ISSUE", "11"),
        os.environ["GH_TOKEN"],
    ):
        lines = (comment.get("body") or "").splitlines()
        if not lines:
            continue
        header = HEADER.fullmatch(lines[0].strip())
        if not header or header.group(1) != RUN_ID or header.group(2) != RUN_ATTEMPT:
            continue
        cursor = 1
        while cursor + 1 < len(lines):
            meta = BLOCK.fullmatch(lines[cursor].strip())
            if not meta:
                cursor += 1
                continue
            index = int(meta.group(1))
            text = lines[cursor + 1].strip()
            raw = text.encode("ascii")
            valid = len(raw) == int(meta.group(3)) and f"{zlib.crc32(raw) & 0xffffffff:08x}" == meta.group(2)
            if valid:
                if index in recovered and recovered[index] != text:
                    raise SystemExit(f"conflicting valid transport block {index}")
                recovered[index] = text
                provenance[index] = int(comment["id"])
            cursor += 2

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
        "schema_version": 2,
        "status": "PASS_EXACT_COMMENT_TRANSPORT",
        "run_id": RUN_ID,
        "run_attempt": RUN_ATTEMPT,
        "block_count": BLOCK_COUNT,
        "base64_bytes": len(assembled),
        "base64_sha256": hashlib.sha256(assembled).hexdigest(),
        "cms_der_bytes": len(der),
        "cms_der_sha256": hashlib.sha256(der).hexdigest(),
        "source_comment_ids": provenance,
    }, indent=2, sort_keys=True) + "\n")
    print("PASS_EXACT_COMMENT_TRANSPORT")


if __name__ == "__main__":
    main()
