#!/usr/bin/env python3
"""Generate a browser-ready PACE Final cache for one ordered image set.

PACE Final is an official three-predictor pipeline. This wrapper creates the
PairUAV JSON records, runs PAAER, MDHR and MARB sequentially, then applies the
released range fusion and task-aware snapping. Sequential execution keeps the
peak memory suitable for an 8 GB GPU when --batch-size 1 is used.
"""
from __future__ import annotations

import argparse
import bisect
import csv
import hashlib
import json
import math
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from image_order import ordered_images, pair_indices


RUNS = {
    "paaer": {
        "output_mode": "pairuav_phase104e_paaer_hard_heading_range",
        "checkpoint": "phase104j_paaer_hr_final/checkpoint-final.pth",
        "sha256": "7454c0f2b31921cd917c21c3726a7cc1860bef03163c474ed689c19e7af4d01e",
    },
    "mdhr": {
        "output_mode": "pairuav_range_h0_heading_mid_late_heading_range",
        "checkpoint": "phase89_h8_midlate_final/checkpoint-final.pth",
        "sha256": "cc985ac7671e7d6dc22928df7eb443ac4f95ad4e295333017e019f6da34216c8",
    },
    "marb": {
        "output_mode": "pairuav_heading_range",
        "checkpoint": "phase45_epoch2_resume_final/checkpoint-final.pth",
        "sha256": "5681ab612d44dc64c98c82ef5b8b4e36c2bb4b38f6748a469f9c8d78c3894e04",
    },
}
RANGE_WEIGHTS = {"paaer": 0.511, "mdhr": 0.189, "marb": 0.300}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_rows(path: Path, expected: int) -> list[tuple[float, float]]:
    rows: list[tuple[float, float]] = []
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            columns = line.split()
            if len(columns) != 2:
                raise ValueError(f"{path}:{line_number} expected heading and range")
            heading, range_m = map(float, columns)
            if not math.isfinite(heading) or not math.isfinite(range_m):
                raise ValueError(f"{path}:{line_number} contains a non-finite prediction")
            rows.append((heading, range_m))
    if len(rows) != expected:
        raise ValueError(f"{path} expected {expected} rows, observed {len(rows)}")
    return rows


def load_distance_support(path: Path) -> list[float]:
    values: set[float] = set()
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if "gt_distance" not in (reader.fieldnames or []):
            raise ValueError(f"support manifest lacks gt_distance: {path}")
        for row in reader:
            values.add(float(row["gt_distance"]))
    if not values:
        raise ValueError(f"support manifest has no distances: {path}")
    return sorted(values)


def nearest(values: list[float], value: float) -> float:
    position = bisect.bisect_left(values, value)
    if position <= 0:
        return values[0]
    if position >= len(values):
        return values[-1]
    left, right = values[position - 1], values[position]
    return right if abs(right - value) < abs(value - left) else left


def snap_heading(value: float) -> float:
    snapped = round(value / 2.0) * 2.0
    while snapped < -180.0:
        snapped += 360.0
    while snapped >= 180.0:
        snapped -= 360.0
    return 0.0 if abs(snapped) < 0.5e-6 else snapped


def write_pair_records(root: Path, images: list[Path], pairs: list[tuple[int, int]]) -> None:
    root.mkdir(parents=True, exist_ok=False)
    scene_id = images[0].parent.name
    for sequence, (a, b) in enumerate(pairs):
        record = {
            "group_id": scene_id,
            "scene_id": scene_id,
            "json_id": f"{sequence:06d}",
            "image_a": images[a].name,
            "image_b": images[b].name,
        }
        destination = root / f"{sequence:06d}_{a:02d}_{b:02d}.json"
        destination.write_text(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image-dir", required=True, type=Path)
    parser.add_argument("--pace-root", required=True, type=Path, help="PairUAV-PACE repository")
    parser.add_argument("--asset-root", type=Path, help="Defaults to PACE_ROOT/assets")
    parser.add_argument("--support-manifest", type=Path, help="Defaults to PACE_ROOT/manifests/devsplit_v1_official_metric_manifest.csv")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--pairs", nargs="+", default=["all"], metavar="all|ring0|stride N")
    parser.add_argument("--expected-images", type=int, default=50)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--num-workers", type=int, default=2)
    args = parser.parse_args()

    assert not args.output_dir.exists(), f"refusing existing output directory: {args.output_dir}"
    infer_script = args.pace_root / "infer_pairuav_with_progress.py"
    assert infer_script.is_file(), f"missing PACE inference script: {infer_script}"
    asset_root = args.asset_root or args.pace_root / "assets"
    support_manifest = args.support_manifest or args.pace_root / "manifests" / "devsplit_v1_official_metric_manifest.csv"
    assert support_manifest.is_file(), f"missing PACE support manifest: {support_manifest}"
    assert args.batch_size > 0 and args.num_workers >= 0

    images = ordered_images(args.image_dir)
    assert len(images) == args.expected_images, f"expected {args.expected_images} images, observed {len(images)}"
    pairs = pair_indices(len(images), args.pairs)
    checkpoints: dict[str, Path] = {}
    for name, spec in RUNS.items():
        checkpoint = asset_root / spec["checkpoint"]
        assert checkpoint.is_file(), f"missing {name} checkpoint: {checkpoint}"
        actual = sha256(checkpoint)
        assert actual == spec["sha256"], f"{name} checkpoint hash mismatch: {actual}"
        checkpoints[name] = checkpoint

    args.output_dir.mkdir(parents=True, exist_ok=False)
    work_dir = args.output_dir / "work"
    json_root = work_dir / "pair_json"
    write_pair_records(json_root, images, pairs)
    prediction_rows: dict[str, list[tuple[float, float]]] = {}
    run_seconds: dict[str, float] = {}
    total_started = time.perf_counter()

    for name, spec in RUNS.items():
        run_dir = work_dir / name
        model = f"Reloc3rRelpose(img_size=512, output_mode='{spec['output_mode']}')"
        command = [
            sys.executable, str(infer_script),
            "--model", model,
            "--json-root", str(json_root),
            "--image-root", str(args.image_dir),
            "--checkpoint", str(checkpoints[name]),
            "--output-dir", str(run_dir),
            "--split", "test",
            "--resolution", "(512,384)",
            "--seed", "777",
            "--batch-size", str(args.batch_size),
            "--num-workers", str(args.num_workers),
            "--amp", "1",
        ]
        print(f"running PACE {name}: {len(pairs)} ordered pairs", flush=True)
        started = time.perf_counter()
        subprocess.run(command, cwd=args.pace_root, check=True)
        run_seconds[name] = time.perf_counter() - started
        prediction_rows[name] = load_rows(run_dir / "result.txt", len(pairs))

    distance_support = load_distance_support(support_manifest)
    elapsed = time.perf_counter() - total_started
    cache = {
        "schema_version": 2,
        "index_base": 0,
        "image_dir": str(args.image_dir.resolve()),
        "image_set": args.image_dir.name,
        "images": [path.name for path in images],
        "image_sha256": [sha256(path) for path in images],
        "created": datetime.now(timezone.utc).isoformat(),
        "selection": args.pairs,
        "model": {
            "id": "pace_final",
            "display_name": "PACE Final",
            "components": ["PAAER", "MDHR", "MARB"],
            "range_weights": RANGE_WEIGHTS,
            "heading_source": "PAAER",
            "heading_lattice_deg": 2.0,
            "distance_calibration": "nearest train/dev support distance",
        },
        "inference": {
            "resolution": [512, 384],
            "seed": 777,
            "amp": True,
            "batch_size": args.batch_size,
            "num_workers": args.num_workers,
            "checkpoint_sha256": {name: RUNS[name]["sha256"] for name in RUNS},
            "support_manifest_sha256": sha256(support_manifest),
            "component_seconds": run_seconds,
            "elapsed_seconds": elapsed,
        },
        "pairs": {},
    }
    average_seconds = elapsed / max(1, len(pairs))
    for row_index, (a, b) in enumerate(pairs):
        paaer_heading, paaer_range = prediction_rows["paaer"][row_index]
        mdhr_heading, mdhr_range = prediction_rows["mdhr"][row_index]
        marb_heading, marb_range = prediction_rows["marb"][row_index]
        fused_range = sum(RANGE_WEIGHTS[name] * prediction_rows[name][row_index][1] for name in RUNS)
        cache["pairs"][f"{a}->{b}"] = {
            "heading_deg": snap_heading(paaer_heading),
            "range_m": nearest(distance_support, fused_range),
            "seconds": average_seconds,
            "raw": {
                "paaer": {"heading_deg": paaer_heading, "range_m": paaer_range},
                "mdhr": {"heading_deg": mdhr_heading, "range_m": mdhr_range},
                "marb": {"heading_deg": marb_heading, "range_m": marb_range},
                "fused_range_m": fused_range,
            },
        }

    destination = args.output_dir / "pace_cache.json"
    with destination.open("x", encoding="utf-8") as stream:
        json.dump(cache, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(f"completed: {destination}", flush=True)


if __name__ == "__main__":
    main()
