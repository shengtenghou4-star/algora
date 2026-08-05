#!/usr/bin/env python3
"""Publish the exact run 31024654733 encrypted payload, manifest last."""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import urllib.request

RUN_ID = "31024654733"
RUN_ATTEMPT = "1"
HEAD_SHA = "c442ad926a8c22bf786d3a221398c59cfcb81c88"
PAYLOAD_URL = "https://temp.sh/hou-lens-run31024654733-payload.b64"
MANIFEST_URL = "https://temp.sh/hou-lens-run31024654733-manifest.json"
B64_BYTES = 116272
B64_SHA256 = "db258a52ad489c333025d75247551655654419e53572ce271e1e22b53a4844f8"
CMS_BYTES = 87202
CMS_SHA256 = "1d2def1657e89982f3d84b8e4cfe9d037619a4f045d21dae0195d6d95a3b999a"
TAR_BYTES = 86541
TAR_SHA256 = "1183982f4de52de9761bc824200247d5078eae99e88c739af4e532b5c113fc90"
TARGET_BRANCH = "hou-lens-p4-5-scientific-payload"
TARGET_DIR = Path(".github/hou-lens-p4-5-scientific-payload")


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def run(repo: Path, *args: str, capture: bool = False) -> str:
    result = subprocess.run(
        [*args], cwd=repo, check=True, text=True,
        stdout=subprocess.PIPE if capture else None,
    )
    return result.stdout.strip() if capture else ""


def download(url: str, destination: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "hou-lens-p45-publisher"})
    with urllib.request.urlopen(request, timeout=120) as response:
        destination.write_bytes(response.read())


def main() -> None:
    repo = Path(os.environ.get("PAYLOAD_REPO", "payload")).resolve()
    if not (repo / ".git").exists():
        raise SystemExit(f"not a Git checkout: {repo}")

    work = Path("/tmp/hou-lens-run31024654733")
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    payload_path = work / "payload.b64"
    preblob_path = work / "manifest.preblob.json"
    download(PAYLOAD_URL, payload_path)
    download(MANIFEST_URL, preblob_path)

    payload = payload_path.read_bytes()
    if len(payload) != B64_BYTES or sha256(payload) != B64_SHA256:
        raise SystemExit(f"encrypted carrier mismatch: bytes={len(payload)} sha256={sha256(payload)}")
    der = base64.b64decode(payload, validate=True)
    if len(der) != CMS_BYTES or sha256(der) != CMS_SHA256:
        raise SystemExit(f"CMS identity mismatch: bytes={len(der)} sha256={sha256(der)}")

    manifest = json.loads(preblob_path.read_text())
    expected = {
        "run_id": RUN_ID,
        "run_attempt": RUN_ATTEMPT,
        "executor_head_sha": HEAD_SHA,
        "base64_bytes": B64_BYTES,
        "base64_sha256": B64_SHA256,
        "cms_der_bytes": CMS_BYTES,
        "cms_der_sha256": CMS_SHA256,
        "private_tar_bytes": TAR_BYTES,
        "private_tar_sha256": TAR_SHA256,
        "part_count": 8,
    }
    for key, value in expected.items():
        if manifest.get(key) != value:
            raise SystemExit(f"preblob manifest mismatch {key}: {manifest.get(key)!r} != {value!r}")
    expected_names = [f"run31024654733-part-{i:03d}.b64" for i in range(1, 9)]
    if [row["file"] for row in manifest["parts"]] != expected_names:
        raise SystemExit("preblob part name sequence mismatch")
    if any("git_blob" in row for row in manifest["parts"]):
        raise SystemExit("preblob manifest unexpectedly contains git_blob")

    parts_dir = work / "parts"
    parts_dir.mkdir()
    cursor = 0
    for row in manifest["parts"]:
        size = int(row["bytes"])
        part = payload[cursor:cursor + size]
        cursor += size
        if len(part) != size or sha256(part) != row["sha256"]:
            raise SystemExit(f"part identity mismatch {row['file']}")
        (parts_dir / row["file"]).write_bytes(part)
    if cursor != len(payload):
        raise SystemExit(f"unconsumed payload bytes: {len(payload) - cursor}")
    print("PASS_DOWNLOAD_AND_ALL_EIGHT_PART_IDENTITIES")

    target = repo / TARGET_DIR
    target.mkdir(parents=True, exist_ok=True)
    for old in target.glob("run31024654733-part-*.b64"):
        old.unlink()
    for row in manifest["parts"]:
        shutil.copyfile(parts_dir / row["file"], target / row["file"])

    run(repo, "git", "config", "user.name", "hou-lens-payload-publisher")
    run(repo, "git", "config", "user.email", "hou-lens-payload-publisher@users.noreply.github.com")
    run(repo, "git", "add", str(TARGET_DIR / "run31024654733-part-001.b64"),
        str(TARGET_DIR / "run31024654733-part-002.b64"),
        str(TARGET_DIR / "run31024654733-part-003.b64"),
        str(TARGET_DIR / "run31024654733-part-004.b64"),
        str(TARGET_DIR / "run31024654733-part-005.b64"),
        str(TARGET_DIR / "run31024654733-part-006.b64"),
        str(TARGET_DIR / "run31024654733-part-007.b64"),
        str(TARGET_DIR / "run31024654733-part-008.b64"))
    staged = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=repo).returncode
    if staged:
        run(repo, "git", "commit", "-m", "Publish exact run 31024654733 payload parts before manifest")
        run(repo, "git", "push", "origin", f"HEAD:{TARGET_BRANCH}")

    run(repo, "git", "fetch", "origin", TARGET_BRANCH)
    run(repo, "git", "reset", "--hard", f"origin/{TARGET_BRANCH}")
    target = repo / TARGET_DIR
    for row in manifest["parts"]:
        path = target / row["file"]
        raw = path.read_bytes()
        if len(raw) != row["bytes"] or sha256(raw) != row["sha256"]:
            raise SystemExit(f"remote roundtrip part mismatch {row['file']}")
        row["git_blob"] = run(repo, "git", "hash-object", str(path), capture=True)

    manifest_path = target / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    run(repo, "git", "add", str(TARGET_DIR / "manifest.json"))
    run(repo, "git", "commit", "-m", "Release run 31024654733 payload manifest last")
    run(repo, "git", "push", "origin", f"HEAD:{TARGET_BRANCH}")

    run(repo, "git", "fetch", "origin", TARGET_BRANCH)
    run(repo, "git", "reset", "--hard", f"origin/{TARGET_BRANCH}")
    final = json.loads((repo / TARGET_DIR / "manifest.json").read_text())
    for key, value in expected.items():
        if final.get(key) != value:
            raise SystemExit(f"final remote manifest mismatch {key}")
    for row in final["parts"]:
        path = repo / TARGET_DIR / row["file"]
        raw = path.read_bytes()
        if len(raw) != row["bytes"] or sha256(raw) != row["sha256"]:
            raise SystemExit(f"final remote part identity mismatch {row['file']}")
        if run(repo, "git", "hash-object", str(path), capture=True) != row["git_blob"]:
            raise SystemExit(f"final remote blob mismatch {row['file']}")
    print("PASS_FINAL_REMOTE_PAYLOAD_IDENTITY")


if __name__ == "__main__":
    main()
