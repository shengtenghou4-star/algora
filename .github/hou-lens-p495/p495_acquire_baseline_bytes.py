#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import pathlib
import re
import sys
import time
from collections import defaultdict

import numpy as np
import requests
from astropy.io import fits
from astropy.wcs import WCS

TAP = "https://archive.eso.org/tap_obs/sync"
SODA = "https://dataportal.eso.org/dataPortal/soda/sync"
BANDS = ("u", "g", "r", "i1", "i2")
FILTER_MAP = {"u": "u_SDSS", "g": "g_SDSS", "r": "r_SDSS", "i1": "i_SDSS", "i2": "i_SDSS"}
UA = "HOU-LENS-P4.9.5-baseline-byte-executor/1"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value)[:180]


def tap_json(session: requests.Session, query: str, timeout: int = 180):
    qb = query.encode("utf-8")
    started = time.monotonic()
    r = session.post(
        TAP,
        data={"REQUEST": "doQuery", "LANG": "ADQL", "FORMAT": "json", "QUERY": query},
        timeout=timeout,
    )
    body = r.content
    receipt = {
        "endpoint": TAP,
        "http_status": r.status_code,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "query_sha256": sha(qb),
        "response_sha256": sha(body),
        "response_bytes": len(body),
    }
    r.raise_for_status()
    payload = json.loads(body.decode("utf-8-sig"))
    if isinstance(payload, list):
        rows = payload if not payload or isinstance(payload[0], dict) else []
    elif isinstance(payload, dict):
        data = payload.get("data") or payload.get("rows") or payload.get("results") or []
        meta = payload.get("metadata") or payload.get("columns") or []
        if data and isinstance(data[0], dict):
            rows = data
        elif data and isinstance(data[0], list):
            names = [(x.get("name") or x.get("column_name") or x.get("label")) if isinstance(x, dict) else str(x) for x in meta]
            rows = [dict(zip(names, row)) for row in data] if names and all(names) else []
        else:
            rows = []
    else:
        rows = []
    return rows, receipt


def resolve_tile_products(session: requests.Session, tile_id: str):
    safe = tile_id.replace("'", "''")
    query = f"""SELECT obs_publisher_did, obs_id, target_name, filter, s_ra, s_dec, s_resolution, abmaglim, dataproduct_type, calib_level, publication_date FROM ivoa.ObsCore WHERE obs_collection='KIDS' AND dataproduct_type='image' AND target_name='{safe}' AND (filter='u_SDSS' OR filter='g_SDSS' OR filter='r_SDSS' OR filter='i_SDSS')"""
    rows, receipt = tap_json(session, query)
    by_filter = defaultdict(list)
    for row in rows:
        by_filter[str(row.get("filter", ""))].append(row)
    for key in by_filter:
        by_filter[key].sort(key=lambda x: (str(x.get("publication_date", "")), str(x.get("obs_publisher_did", "")), str(x.get("obs_id", ""))))
    counts = {key: len(by_filter.get(key, [])) for key in ("u_SDSS", "g_SDSS", "r_SDSS", "i_SDSS")}
    if counts != {"u_SDSS": 1, "g_SDSS": 1, "r_SDSS": 1, "i_SDSS": 2}:
        raise RuntimeError(f"tile {tile_id} science product multiplicity mismatch: {counts}")
    selected = {
        "u": by_filter["u_SDSS"][0],
        "g": by_filter["g_SDSS"][0],
        "r": by_filter["r_SDSS"][0],
        "i1": by_filter["i_SDSS"][0],
        "i2": by_filter["i_SDSS"][1],
    }
    for band, row in selected.items():
        did = str(row.get("obs_publisher_did", ""))
        if not did.startswith("ivo://eso.org/ID?ADP."):
            raise RuntimeError(f"tile {tile_id} band {band} lacks canonical ESO publisher DID: {did}")
    return selected, {"tile_id": tile_id, "query": query, "receipt": receipt, "counts": counts, "selected": selected}


def download_one(session: requests.Session, did: str, ra: float, dec: float, band: str, *, radius: float = 0.01, attempts: int = 3, timeout: int = 180):
    history = []
    last = None
    params = {"ID": did, "POS": f"CIRCLE {ra:.10f} {dec:.10f} {radius:.10f}"}
    for attempt in range(1, attempts + 1):
        started = time.monotonic()
        try:
            r = session.get(SODA, params=params, timeout=timeout, allow_redirects=True)
            body = r.content
            event = {
                "attempt": attempt,
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "status_code": r.status_code,
                "content_type": r.headers.get("content-type"),
                "byte_size": len(body),
                "request_url": r.url,
            }
            history.append(event)
            if r.status_code == 200 and body.startswith(b"SIMPLE  ="):
                return body, history
            last = f"HTTP {r.status_code}, bytes={len(body)}, type={r.headers.get('content-type')}"
        except requests.RequestException as exc:
            last = f"{type(exc).__name__}: {exc}"
            history.append({"attempt": attempt, "elapsed_seconds": round(time.monotonic() - started, 3), "error": last})
        if attempt < attempts:
            time.sleep(min(8, 2 ** (attempt - 1)))
    raise RuntimeError(f"SODA failed for {band} after {attempts} attempts: {last}")


def inspect_fits(body: bytes, ra: float, dec: float, band: str):
    with fits.open(io.BytesIO(body), memmap=False, checksum=True) as hdul:
        hdu = hdul[0]
        if hdu.data is None or hdu.data.ndim != 2:
            raise RuntimeError("expected 2-D primary science image")
        image = np.asarray(hdu.data)
        wcs = WCS(hdu.header)
        x, y = wcs.world_to_pixel_values(ra, dec)
        if not (0 <= x < image.shape[1] and 0 <= y < image.shape[0]):
            raise RuntimeError(f"target outside cutout: {(x, y)} shape={image.shape}")
        centre = float(math.hypot(x - (image.shape[1] - 1) / 2.0, y - (image.shape[0] - 1) / 2.0))
        if centre > 2.0:
            raise RuntimeError(f"target not centred: {centre}")
        matrix = wcs.pixel_scale_matrix
        scales = [float(math.hypot(matrix[0, 0], matrix[1, 0]) * 3600.0), float(math.hypot(matrix[0, 1], matrix[1, 1]) * 3600.0)]
        if max(abs(v - 0.2) for v in scales) > 1e-5:
            raise RuntimeError(f"unexpected pixel scale: {scales}")
        filt = str(hdu.header.get("FILTER", ""))
        if not filt.lower().startswith(band[0]):
            raise RuntimeError(f"filter mismatch: expected {band}, got {filt}")
        psf = float(hdu.header.get("PSF_FWHM", np.nan))
        if not np.isfinite(psf) or psf <= 0:
            raise RuntimeError("missing positive PSF_FWHM")
        finite = float(np.isfinite(image).mean())
        if finite <= 0.99:
            raise RuntimeError(f"finite fraction too low: {finite}")
        return {
            "shape": list(image.shape),
            "dtype": str(image.dtype),
            "filter": filt,
            "psf_fwhm_arcsec": psf,
            "pixel_scale_arcsec": scales,
            "target_pixel": {"x": float(x), "y": float(y)},
            "target_centre_distance_pixels": centre,
            "finite_fraction": finite,
        }


def load_targets(path: pathlib.Path):
    with path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    required = {"object_key", "group_id", "role", "source_id", "tile_id", "ra_deg", "dec_deg"}
    if not rows or not required.issubset(rows[0]):
        raise RuntimeError("target manifest schema mismatch")
    if len(rows) != 38 or len({r["object_key"] for r in rows}) != 38:
        raise RuntimeError("target manifest must contain exactly 38 unique objects")
    out = []
    for row in rows:
        role = row["role"]
        if role not in {"positive", "control"}:
            raise RuntimeError(f"invalid role {role}")
        ra, dec = float(row["ra_deg"]), float(row["dec_deg"])
        if not 0 <= ra < 360 or not -90 <= dec <= 90:
            raise RuntimeError("invalid coordinates")
        z = dict(row); z["ra_deg"] = ra; z["dec_deg"] = dec; out.append(z)
    if sum(r["role"] == "positive" for r in out) != 5 or sum(r["role"] == "control" for r in out) != 33:
        raise RuntimeError("expected 5 positive and 33 control objects")
    if len({r["tile_id"] for r in out}) != 11:
        raise RuntimeError("expected exactly 11 frozen tiles")
    return out


def main():
    if len(sys.argv) != 4:
        raise SystemExit("usage: executor.py TARGETS.csv LOCK.json OUTPUT_DIR")
    targets_path = pathlib.Path(sys.argv[1]); lock_path = pathlib.Path(sys.argv[2]); out = pathlib.Path(sys.argv[3])
    out.mkdir(parents=True, exist_ok=True); (out / "fits").mkdir(exist_ok=True)
    targets = load_targets(targets_path)
    lock = json.loads(lock_path.read_text())
    required_lock = {
        "protocol": "HOU-LENS-P4.9.5-BASELINE-BYTE-CAMPAIGN",
        "object_count": 38,
        "logical_request_count": 190,
        "scores_available": False,
        "future_validation_touched": False,
        "unknown_dr5_only_targets_queried": False,
        "blind_search": False,
    }
    for key, value in required_lock.items():
        if lock.get(key) != value:
            raise RuntimeError(f"lock mismatch {key}: {lock.get(key)!r} != {value!r}")

    session = requests.Session(); session.headers.update({"User-Agent": UA})
    tile_records = []
    tile_products = {}
    for tile in sorted({r["tile_id"] for r in targets}):
        selected, rec = resolve_tile_products(session, tile)
        tile_products[tile] = {band: row["obs_publisher_did"] for band, row in selected.items()}
        tile_records.append(rec)
    (out / "tile_product_resolution.json").write_text(json.dumps(tile_records, indent=2, sort_keys=True) + "\n")

    receipts = []
    failures = []
    for idx, target in enumerate(targets, 1):
        objdir = out / "fits" / f"{idx:02d}_{safe_name(target['object_key'])}"
        objdir.mkdir(parents=True, exist_ok=True)
        for band in BANDS:
            did = tile_products[target["tile_id"]][band]
            key = f"{target['object_key']}::{band}"
            try:
                body, history = download_one(session, did, target["ra_deg"], target["dec_deg"], band)
                meta = inspect_fits(body, target["ra_deg"], target["dec_deg"], band)
                path = objdir / f"{band}.fits"; path.write_bytes(body)
                receipts.append({
                    "request_key": key, "status": "success", "object_key": target["object_key"], "group_id": target["group_id"],
                    "role": target["role"], "source_id": target["source_id"], "tile_id": target["tile_id"], "band": band,
                    "dataset_id": did, "file": str(path.relative_to(out)), "bytes": len(body), "sha256": sha(body), "history": history, "fits": meta,
                })
            except Exception as exc:
                failures.append({"request_key": key, "object_key": target["object_key"], "band": band, "error": f"{type(exc).__name__}: {exc}"})
                receipts.append({
                    "request_key": key, "status": "failure", "object_key": target["object_key"], "group_id": target["group_id"],
                    "role": target["role"], "source_id": target["source_id"], "tile_id": target["tile_id"], "band": band,
                    "dataset_id": did, "error": f"{type(exc).__name__}: {exc}",
                })
    with (out / "request_receipts.jsonl").open("w", encoding="utf-8") as f:
        for row in receipts: f.write(json.dumps(row, sort_keys=True) + "\n")
    summary = {
        "schema_version": 1,
        "protocol": "HOU-LENS-P4.9.5-BASELINE-BYTE-CAMPAIGN",
        "status": "PASS_190_OF_190" if not failures and len(receipts) == 190 else "TERMINAL_WITH_TECHNICAL_FAILURES",
        "objects": len(targets), "tiles": len(tile_products), "logical_requests": len(receipts),
        "successes": sum(r["status"] == "success" for r in receipts), "failures": len(failures),
        "failure_records": failures,
        "scores_available": False, "scores_computed": False,
        "future_validation_touched": False, "unknown_dr5_only_targets_queried": False, "blind_search": False,
        "claim_boundary": "Baseline raw-byte/provenance acquisition only for frozen exposed-development identities. No score, successor fitting, future validation, unknown DR5-only target access, or blind search.",
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps(summary, sort_keys=True))
    return 0 if summary["status"] == "PASS_190_OF_190" else 2


if __name__ == "__main__":
    raise SystemExit(main())
