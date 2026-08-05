#!/usr/bin/env python3
"""Patch the P4.5 scientific workflow to recover the original frozen runtime exactly."""
from __future__ import annotations

from pathlib import Path
import sys


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: hou_lens_p45_patch_runtime_recovery.py WORKFLOW")
    path = Path(sys.argv[1])
    text = path.read_text()

    anchor = "      - name: Restore and verify exact public executor source\n"
    recovery = r'''      - name: Restore original frozen base runtime after artifact expiry
        run: |
          set -euo pipefail
          mkdir -p /tmp/result
          test "$(sha256sum /tmp/runtime/requirements.in | cut -d' ' -f1)" = '525c2473112c887e2be57fdb6d7f048b32c30dabf6fe3e118991fa8fe7838ee1'
          rm -f /tmp/runtime/wheels/astropy_iers_data-*.whl /tmp/runtime/wheels/packaging-*.whl
          IMAGE='python@sha256:86adf8dbadc3d6e82ee5dd2c74bec2e1c2467cdad47886280501df722372d2e1'
          docker pull "$IMAGE" >/dev/null
          docker run --rm -v /tmp/runtime/wheels:/w "$IMAGE" sh -lc '
            set -eu
            python -m pip download --disable-pip-version-check --no-deps --only-binary=:all: --dest /w \
              astropy-iers-data==0.2026.7.27.0.56.29 packaging==26.2 >/dev/null
          '
          test "$(sha256sum /tmp/runtime/wheels/astropy_iers_data-0.2026.7.27.0.56.29-py3-none-any.whl | cut -d' ' -f1)" = '8106cce07e38e3e0422f755b8964e6d03ca4d4280bb134934c74d497711f8d2a'
          test "$(sha256sum /tmp/runtime/wheels/packaging-26.2-py3-none-any.whl | cut -d' ' -f1)" = '5fc45236b9446107ff2415ce77c807cee2862cb6fac22b8a73826d0693b0980e'
          cat > /tmp/runtime/requirements.freeze <<'EOF'
          PyYAML==6.0.3
          astropy-iers-data==0.2026.7.27.0.56.29
          astropy==6.0.1
          iniconfig==2.3.0
          numpy==1.26.4
          packaging==26.2
          pluggy==1.6.0
          pyerfa==2.0.1.5
          pytest==8.2.2
          scipy==1.11.4
          EOF
          test "$(sha256sum /tmp/runtime/requirements.freeze | cut -d' ' -f1)" = '7e84039e357df88dcf012fd4cebb8b4817625fb63208758a799dc76e7ef42891'
          (cd /tmp/runtime/wheels && sha256sum * | LC_ALL=C sort -k2 > ../wheel-manifest.sha256)
          test "$(sha256sum /tmp/runtime/wheel-manifest.sha256 | cut -d' ' -f1)" = 'a75bfdb37baaac7209a6e172917a18970dac1a48aad98d947addc6fa17748e4a'
          tar --sort=name --mtime='UTC 1970-01-01' --owner=0 --group=0 --numeric-owner \
            -czf /tmp/runtime/wheels.tar.gz -C /tmp/runtime \
            wheels requirements.in requirements.freeze wheel-manifest.sha256
          test "$(sha256sum /tmp/runtime/wheels.tar.gz | cut -d' ' -f1)" = '2b93e842ba98db65bef6a1073e073a55e694741de7ecd47878a6b949288eb8f1'
          python - <<'PY'
          import json, pathlib
          pathlib.Path('/tmp/result/runtime-recovery.json').write_text(json.dumps({
              'schema_version': 1,
              'stage': 'p4_5_exact_runtime_recovery_after_artifact_expiry',
              'status': 'PASS_RESTORED_ORIGINAL_FROZEN_WHEEL_IDENTITY',
              'source_run_id': 30734422166,
              'expired_original_artifact_id': 8829046472,
              'reupload_artifact_id': 8929087724,
              'reupload_artifact_digest': 'sha256:9535b504f064da03eac7c3a4dca4b793218a12c780f8fa41c381c6b8beec9933',
              'restored_versions': {
                  'astropy-iers-data': '0.2026.7.27.0.56.29',
                  'packaging': '26.2',
              },
              'requirements_freeze_sha256': '7e84039e357df88dcf012fd4cebb8b4817625fb63208758a799dc76e7ef42891',
              'wheel_manifest_sha256': 'a75bfdb37baaac7209a6e172917a18970dac1a48aad98d947addc6fa17748e4a',
              'wheel_bundle_sha256': '2b93e842ba98db65bef6a1073e073a55e694741de7ecd47878a6b949288eb8f1',
              'soda_requests_sent': 0,
              'image_bytes_downloaded': 0,
              'scores_computed': False,
          }, indent=2, sort_keys=True) + '\n')
          PY

'''
    if "Restore original frozen base runtime after artifact expiry" not in text:
        text = replace_once(text, anchor, recovery + anchor, "runtime recovery insertion")

    old_patch_checks = r'''          test "$(sha256sum /tmp/patch-artifact/p4-5-requests-runtime-patch.tar.gz | cut -d' ' -f1)" = 'a8160b489191039c5f2be23be741c12e02323099d7d9f00ca9c62324f94e4f5b'
          test "$(sha256sum /tmp/patch-artifact/p4-5-requests-runtime-patch-receipt.json | cut -d' ' -f1)" = '01169787e45dea3f370a6ca7d789167770cf3b547b0cfd736b9b77ebce9d598a'
          tar -xzf /tmp/patch-artifact/p4-5-requests-runtime-patch.tar.gz -C /tmp/patch
          test "$(sha256sum /tmp/patch/requests-wheel-manifest.sha256 | cut -d' ' -f1)" = '952a86e2842f5f4cfb35de196fa8587af949a6732a57edf8a2c43be96665d3d3'
'''
    new_patch_checks = r'''          PATCH_TAR_SHA="$(sha256sum /tmp/patch-artifact/p4-5-requests-runtime-patch.tar.gz | cut -d' ' -f1)"
          PATCH_RECEIPT_SHA="$(sha256sum /tmp/patch-artifact/p4-5-requests-runtime-patch-receipt.json | cut -d' ' -f1)"
          case "$PATCH_TAR_SHA:$PATCH_RECEIPT_SHA" in
            a8160b489191039c5f2be23be741c12e02323099d7d9f00ca9c62324f94e4f5b:01169787e45dea3f370a6ca7d789167770cf3b547b0cfd736b9b77ebce9d598a) ;;
            b045abf18df056e99fa2aa47219136b18f2b3f115fcd3db9336d1b1ebabda28a:63a1f6ffda021310f8da34b4d7028ec15cd1abc8d75ba6fd753320df54be90a8) ;;
            *) echo "unrecognized Requests patch wrapper identity" >&2; exit 1 ;;
          esac
          tar -xzf /tmp/patch-artifact/p4-5-requests-runtime-patch.tar.gz -C /tmp/patch
          test "$(sha256sum /tmp/patch/requests-wheel-manifest.sha256 | cut -d' ' -f1)" = '952a86e2842f5f4cfb35de196fa8587af949a6732a57edf8a2c43be96665d3d3'
          test "$(sha256sum /tmp/patch/p4_5_requests_runtime_closure.json | cut -d' ' -f1)" = 'a92ef67259db37906756b52b7d098bc7c5093afcfef6904819ed64f44bf2e8aa'
          python - "$PATCH_TAR_SHA" "$PATCH_RECEIPT_SHA" <<'PY'
          import json, pathlib, sys
          pathlib.Path('/tmp/result/requests-patch-wrapper.json').write_text(json.dumps({
              'schema_version': 1,
              'stage': 'p4_5_requests_patch_wrapper_identity',
              'status': 'PASS_ALLOWED_WRAPPER_AND_EXACT_INNER_WHEELS',
              'source_run_id': 30808837306,
              'patch_tar_sha256': sys.argv[1],
              'patch_receipt_sha256': sys.argv[2],
              'inner_wheel_manifest_sha256': '952a86e2842f5f4cfb35de196fa8587af949a6732a57edf8a2c43be96665d3d3',
              'closure_sha256': 'a92ef67259db37906756b52b7d098bc7c5093afcfef6904819ed64f44bf2e8aa',
              'soda_requests_sent': 0,
              'image_bytes_downloaded': 0,
              'scores_computed': False,
          }, indent=2, sort_keys=True) + '\n')
          PY
'''
    if old_patch_checks in text:
        text = replace_once(text, old_patch_checks, new_patch_checks, "Requests wrapper gate")

    old_context = r'''              'base_runtime_artifact_id': 8829046472,
              'base_runtime_artifact_digest': 'sha256:f655443bfece4634b856d66d398efaa6f4d726ae1760726b651a92f885f98d9f',
              'requests_patch_artifact_id': 8853932417,
              'requests_patch_artifact_digest': 'sha256:31630df77b54431460febab4f3eb935490a843eadf8389314fc04f0d211bdb94',
'''
    new_context = r'''              'base_runtime_source_run_id': 30734422166,
              'base_runtime_expired_original_artifact_id': 8829046472,
              'base_runtime_reupload_artifact_id': 8929087724,
              'base_runtime_reupload_artifact_digest': 'sha256:9535b504f064da03eac7c3a4dca4b793218a12c780f8fa41c381c6b8beec9933',
              'base_runtime_restored_wheel_bundle_sha256': '2b93e842ba98db65bef6a1073e073a55e694741de7ecd47878a6b949288eb8f1',
              'requests_patch_source_run_id': 30808837306,
              'requests_patch_original_artifact_id': 8853932417,
              'requests_patch_reupload_artifact_id': 8929113579,
              'requests_patch_reupload_artifact_digest': 'sha256:06b877996532c15c49228c711ab18e717f62f840ce0f3b28e651cd4ab49f613e',
              'requests_patch_inner_manifest_sha256': '952a86e2842f5f4cfb35de196fa8587af949a6732a57edf8a2c43be96665d3d3',
'''
    if old_context in text:
        text = replace_once(text, old_context, new_context, "result provenance")

    old_exit = "          exit_code = int((result / 'executor-exit-code.txt').read_text().strip())\n"
    new_exit = "          exit_path = result / 'executor-exit-code.txt'\n          if not exit_path.is_file():\n              exit_path.write_text('190\\n')\n          exit_code = int(exit_path.read_text().strip())\n"
    if old_exit in text:
        text = replace_once(text, old_exit, new_exit, "partial audit exit code")

    required = [
        "PASS_RESTORED_ORIGINAL_FROZEN_WHEEL_IDENTITY",
        "b045abf18df056e99fa2aa47219136b18f2b3f115fcd3db9336d1b1ebabda28a",
        "base_runtime_restored_wheel_bundle_sha256",
        "exit_path.write_text('190\\n')",
    ]
    missing = [item for item in required if item not in text]
    if missing:
        raise SystemExit(f"patched workflow missing markers: {missing}")
    path.write_text(text)


if __name__ == "__main__":
    main()
