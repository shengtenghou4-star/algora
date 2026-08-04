#!/usr/bin/env python3
"""Recover the exact P4.6 attempt-4 CMS payload from authenticated PR comments.

This script handles encrypted transport bytes only. It verifies per-block CRC32 and
full Base64/CMS hashes before writing /tmp/payload.b64. It never decrypts the
scientific payload and never accesses the validation set.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import re
import urllib.request
import zlib

EXPECTED_RUN_ID = "30832075911"
EXPECTED_RUN_ATTEMPT = "4"
EXPECTED_B64_BYTES = 115_156
EXPECTED_B64_SHA256 = "2c4339345d9349267521a5cb0e2292d2aa2437950366b1fd7f8256f0dd87dd70"
EXPECTED_CMS_BYTES = 86_366
EXPECTED_CMS_SHA256 = "a63ee5cc0c0bab7280c077726516f876f933c1c81c31ee440bc5b26430332d7f"
EXPECTED_BLOCK_COUNT = 28
HEADER = re.compile(
    r"^HOU-LENS-P46-TRANSPORT v1 run=(\d+) attempt=(\d+) replica=A group=(\d+)$"
)
BLOCK = re.compile(r"^P(\d{3}) crc32=([0-9a-f]{8}) len=(\d+)$")


def fetch_comments(repo: str, issue: str, token: str) -> list[dict]:
    comments: list[dict] = []
    page = 1
    while True:
        url = (
            f"https://api.github.com/repos/{repo}/issues/{issue}/comments"
            f"?per_page=100&page={page}"
        )
        request = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "hou-lens-p46-transport",
            },
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            batch = json.load(response)
        comments.extend(batch)
        if len(batch) < 100:
            return comments
        page += 1


def main() -> None:
    repo = os.environ["GITHUB_REPOSITORY"]
    token = os.environ["GH_TOKEN"]
    issue = os.environ.get("P46_TRANSPORT_ISSUE", "11")
    recovered: dict[int, str] = {}
    provenance: dict[int, int] = {}

    for comment in fetch_comments(repo, issue, token):
        lines = (comment.get("body") or "").splitlines()
        if not lines:
            continue
        header = HEADER.fullmatch(lines[0].strip())
        if not header:
            continue
        if header.group(1) != EXPECTED_RUN_ID or header.group(2) != EXPECTED_RUN_ATTEMPT:
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
            crc = f"{zlib.crc32(raw) & 0xFFFFFFFF:08x}"
            if len(raw) == int(meta.group(3)) and crc == meta.group(2):
                previous = recovered.get(index)
                if previous is not None and previous != text:
                    raise SystemExit(f"conflicting valid transport block {index}")
                recovered[index] = text
                provenance[index] = int(comment["id"])
            cursor += 2

    missing = [index for index in range(EXPECTED_BLOCK_COUNT) if index not in recovered]
    if missing:
        raise SystemExit(f"missing or corrupt transport blocks: {missing}")

    assembled = "".join(recovered[index] for index in range(EXPECTED_BLOCK_COUNT)).encode("ascii")
    if len(assembled) != EXPECTED_B64_BYTES:
        raise SystemExit("global Base64 byte-count mismatch")
    if hashlib.sha256(assembled).hexdigest() != EXPECTED_B64_SHA256:
        raise SystemExit("global Base64 SHA-256 mismatch")
    der = base64.b64decode(assembled, validate=True)
    if len(der) != EXPECTED_CMS_BYTES:
        raise SystemExit("CMS DER byte-count mismatch")
    if hashlib.sha256(der).hexdigest() != EXPECTED_CMS_SHA256:
        raise SystemExit("CMS DER SHA-256 mismatch")

    Path("/tmp/payload.b64").write_bytes(assembled)
    Path("/tmp/p46-transport-audit.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "status": "PASS_EXACT_28_BLOCK_COMMENT_TRANSPORT",
                "run_id": EXPECTED_RUN_ID,
                "run_attempt": EXPECTED_RUN_ATTEMPT,
                "block_count": EXPECTED_BLOCK_COUNT,
                "base64_bytes": len(assembled),
                "base64_sha256": hashlib.sha256(assembled).hexdigest(),
                "cms_der_bytes": len(der),
                "cms_der_sha256": hashlib.sha256(der).hexdigest(),
                "source_comment_ids": provenance,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print("PASS_EXACT_28_BLOCK_COMMENT_TRANSPORT")


if __name__ == "__main__":
    main()
