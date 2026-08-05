#!/usr/bin/env python3
"""Patch P4.5 runtime recovery to immutable exact wheels and original tar scope."""
from __future__ import annotations

from pathlib import Path
import sys

INDEX_BLOCK = r'''          IMAGE='python@sha256:86adf8dbadc3d6e82ee5dd2c74bec2e1c2467cdad47886280501df722372d2e1'
          docker pull "$IMAGE" >/dev/null
          docker run --rm -v /tmp/runtime/wheels:/w "$IMAGE" sh -lc '
            set -eu
            python -m pip download --disable-pip-version-check --no-deps --only-binary=:all: --dest /w \
              astropy-iers-data==0.2026.7.27.0.56.29 packaging==26.2 >/dev/null
          '
'''

CDN_BLOCK = r'''          curl --fail --location --retry 3 \
            --output /tmp/runtime/wheels/astropy_iers_data-0.2026.7.27.0.56.29-py3-none-any.whl \
            'https://files.pythonhosted.org/packages/7b/02/df236615164fbd2fd29b04b5c44ff24949272612ccc84347071a074e0ce0/astropy_iers_data-0.2026.7.27.0.56.29-py3-none-any.whl'
          curl --fail --location --retry 3 \
            --output /tmp/runtime/wheels/packaging-26.2-py3-none-any.whl \
            'https://files.pythonhosted.org/packages/df/b2/87e62e8c3e2f4b32e5fe99e0b86d576da1312593b39f47d8ceef365e95ed/packaging-26.2-py3-none-any.whl'
'''

WRONG_TAR = r'''          tar --sort=name --mtime='UTC 1970-01-01' --owner=0 --group=0 --numeric-owner \
            -czf /tmp/runtime/wheels.tar.gz -C /tmp/runtime \
            wheels requirements.in requirements.freeze wheel-manifest.sha256
'''

ORIGINAL_TAR = r'''          tar --sort=name --mtime='UTC 1970-01-01' --owner=0 --group=0 --numeric-owner \
            -czf /tmp/runtime/wheels.tar.gz -C /tmp/runtime wheels
'''

STATUS_LINE = "              'status': 'PASS_RESTORED_ORIGINAL_FROZEN_WHEEL_IDENTITY',\n"
RECEIPT_FIELDS = (
    "              'recovery_transport': 'immutable_files_pythonhosted_content_address',\n"
    "              'cdn_diagnostic_run_id': 31007161254,\n"
    "              'original_bundle_member_scope': ['wheels/'],\n"
)


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: hou_lens_p45_patch_cdn_recovery.py WORKFLOW")
    path = Path(sys.argv[1])
    text = path.read_text()
    changed = False

    if INDEX_BLOCK in text:
        text = text.replace(INDEX_BLOCK, CDN_BLOCK, 1)
        changed = True
    elif CDN_BLOCK not in text:
        raise SystemExit("neither package-index nor immutable-CDN recovery block found")

    if WRONG_TAR in text:
        text = text.replace(WRONG_TAR, ORIGINAL_TAR, 1)
        changed = True
    elif ORIGINAL_TAR not in text:
        raise SystemExit("neither expanded nor original wheel tar command found")

    if "'original_bundle_member_scope': ['wheels/']" not in text:
        marker = STATUS_LINE
        if marker not in text:
            raise SystemExit("runtime recovery receipt status marker missing")
        insertion = marker
        if "'recovery_transport': 'immutable_files_pythonhosted_content_address'" not in text:
            insertion += RECEIPT_FIELDS
        else:
            insertion += "              'original_bundle_member_scope': ['wheels/'],\n"
        text = text.replace(marker, insertion, 1)
        changed = True

    required = [
        "files.pythonhosted.org/packages/7b/02/df236615164fbd2fd29b04b5c44ff24949272612ccc84347071a074e0ce0",
        "files.pythonhosted.org/packages/df/b2/87e62e8c3e2f4b32e5fe99e0b86d576da1312593b39f47d8ceef365e95ed",
        "8106cce07e38e3e0422f755b8964e6d03ca4d4280bb134934c74d497711f8d2a",
        "5fc45236b9446107ff2415ce77c807cee2862cb6fac22b8a73826d0693b0980e",
        "a75bfdb37baaac7209a6e172917a18970dac1a48aad98d947addc6fa17748e4a",
        "2b93e842ba98db65bef6a1073e073a55e694741de7ecd47878a6b949288eb8f1",
        "cdn_diagnostic_run_id': 31007161254",
        "original_bundle_member_scope': ['wheels/']",
        "-czf /tmp/runtime/wheels.tar.gz -C /tmp/runtime wheels",
    ]
    missing = [item for item in required if item not in text]
    if missing:
        raise SystemExit(f"patched workflow missing exact recovery markers: {missing}")
    path.write_text(text)
    print("PASS_PATCHED_ORIGINAL_WHEEL_BUNDLE_SCOPE" if changed else "PASS_ALREADY_PATCHED_ORIGINAL_WHEEL_BUNDLE_SCOPE")


if __name__ == "__main__":
    main()
