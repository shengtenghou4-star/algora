#!/usr/bin/env python3
"""Replace the failed package-index recovery with immutable exact-wheel CDN recovery."""
from __future__ import annotations

from pathlib import Path
import sys

OLD = r'''          IMAGE='python@sha256:86adf8dbadc3d6e82ee5dd2c74bec2e1c2467cdad47886280501df722372d2e1'
          docker pull "$IMAGE" >/dev/null
          docker run --rm -v /tmp/runtime/wheels:/w "$IMAGE" sh -lc '
            set -eu
            python -m pip download --disable-pip-version-check --no-deps --only-binary=:all: --dest /w \
              astropy-iers-data==0.2026.7.27.0.56.29 packaging==26.2 >/dev/null
          '
'''

NEW = r'''          curl --fail --location --retry 3 \
            --output /tmp/runtime/wheels/astropy_iers_data-0.2026.7.27.0.56.29-py3-none-any.whl \
            'https://files.pythonhosted.org/packages/7b/02/df236615164fbd2fd29b04b5c44ff24949272612ccc84347071a074e0ce0/astropy_iers_data-0.2026.7.27.0.56.29-py3-none-any.whl'
          curl --fail --location --retry 3 \
            --output /tmp/runtime/wheels/packaging-26.2-py3-none-any.whl \
            'https://files.pythonhosted.org/packages/df/b2/87e62e8c3e2f4b32e5fe99e0b86d576da1312593b39f47d8ceef365e95ed/packaging-26.2-py3-none-any.whl'
'''

OLD_RECEIPT = "              'status': 'PASS_RESTORED_ORIGINAL_FROZEN_WHEEL_IDENTITY',\n"
NEW_RECEIPT = (
    "              'status': 'PASS_RESTORED_ORIGINAL_FROZEN_WHEEL_IDENTITY',\n"
    "              'recovery_transport': 'immutable_files_pythonhosted_content_address',\n"
    "              'cdn_diagnostic_run_id': 31007161254,\n"
)


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: hou_lens_p45_patch_cdn_recovery.py WORKFLOW")
    path = Path(sys.argv[1])
    text = path.read_text()
    if NEW in text:
        print("PASS_ALREADY_PATCHED_IMMUTABLE_CDN_RECOVERY")
        return
    count = text.count(OLD)
    if count != 1:
        raise SystemExit(f"expected one package-index recovery block, found {count}")
    text = text.replace(OLD, NEW, 1)
    receipt_count = text.count(OLD_RECEIPT)
    if receipt_count != 1:
        raise SystemExit(f"expected one recovery receipt status, found {receipt_count}")
    text = text.replace(OLD_RECEIPT, NEW_RECEIPT, 1)
    required = [
        "files.pythonhosted.org/packages/7b/02/df236615164fbd2fd29b04b5c44ff24949272612ccc84347071a074e0ce0",
        "files.pythonhosted.org/packages/df/b2/87e62e8c3e2f4b32e5fe99e0b86d576da1312593b39f47d8ceef365e95ed",
        "8106cce07e38e3e0422f755b8964e6d03ca4d4280bb134934c74d497711f8d2a",
        "5fc45236b9446107ff2415ce77c807cee2862cb6fac22b8a73826d0693b0980e",
        "a75bfdb37baaac7209a6e172917a18970dac1a48aad98d947addc6fa17748e4a",
        "2b93e842ba98db65bef6a1073e073a55e694741de7ecd47878a6b949288eb8f1",
        "cdn_diagnostic_run_id': 31007161254",
    ]
    missing = [item for item in required if item not in text]
    if missing:
        raise SystemExit(f"patched workflow missing exact CDN recovery markers: {missing}")
    path.write_text(text)
    print("PASS_PATCHED_IMMUTABLE_CDN_RECOVERY")


if __name__ == "__main__":
    main()
