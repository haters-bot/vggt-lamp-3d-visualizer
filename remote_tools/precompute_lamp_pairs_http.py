#!/usr/bin/env python3
"""Build a resumable LaMP cache through an already-running HTTP service."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from image_order import ordered_images, pair_indices


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image-dir", required=True, type=Path)
    parser.add_argument("--image-set", required=True)
    parser.add_argument("--endpoint", default="http://127.0.0.1:8765/infer")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--limit-images", type=int)
    parser.add_argument("--timeout", type=float, default=600)
    args = parser.parse_args()

    images = ordered_images(args.image_dir)
    if args.limit_images is not None:
        if not 2 <= args.limit_images <= len(images):
            parser.error(f"--limit-images must be between 2 and {len(images)}")
        images = images[: args.limit_images]
    if args.output.exists():
        parser.error(f"refusing to overwrite completed cache: {args.output}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    progress_path = args.output.with_suffix(args.output.suffix + ".progress.jsonl")

    completed: dict[str, dict] = {}
    if progress_path.is_file():
        for number, line in enumerate(progress_path.read_text(encoding="utf-8").splitlines(), 1):
            record = json.loads(line)
            if not isinstance(record, dict) or "key" not in record or "value" not in record:
                raise ValueError(f"invalid progress record on line {number}")
            completed[record["key"]] = record["value"]

    pairs = pair_indices(len(images), ["all"])
    started = time.perf_counter()
    with progress_path.open("a", encoding="utf-8") as progress:
        for number, (a, b) in enumerate(pairs, 1):
            key = f"{a}->{b}"
            if key in completed:
                continue
            payload = json.dumps(
                {
                    "frame_a": a + 1,
                    "frame_b": b + 1,
                    "image_a": images[a].name,
                    "image_b": images[b].name,
                    "image_set": args.image_set,
                }
            ).encode("utf-8")
            request = urllib.request.Request(
                args.endpoint,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            tick = time.perf_counter()
            with urllib.request.urlopen(request, timeout=args.timeout) as response:
                prediction = json.loads(response.read().decode("utf-8"))
            continuous, decoded = prediction["continuous"], prediction["map_hard"]
            value = {
                "heading_deg": continuous["heading_deg"],
                "yaw_deg": continuous.get("yaw_deg", continuous["heading_deg"]),
                "rotation_angle_deg": continuous["rotation_angle_deg"],
                "range_m": continuous["selected_range_m"],
                "decoded": {
                    name: decoded[name]
                    for name in ("heading_deg", "range_m", "label_index", "step_difference")
                },
                "seconds": time.perf_counter() - tick,
            }
            completed[key] = value
            progress.write(json.dumps({"key": key, "value": value}, allow_nan=False) + "\n")
            progress.flush()
            if number == 1 or number % 25 == 0 or number == len(pairs):
                print(
                    f"{len(completed)}/{len(pairs)} elapsed={time.perf_counter()-started:.1f}s",
                    flush=True,
                )

    if len(completed) != len(pairs):
        raise RuntimeError(f"cache incomplete: {len(completed)}/{len(pairs)}")
    result = {
        "schema_version": 1,
        "index_base": 0,
        # Store a portable logical identifier instead of a workstation path.
        "image_dir": args.image_set,
        "image_set": args.image_set,
        "images": [path.name for path in images],
        "image_sha256": [sha256(path) for path in images],
        "created": datetime.now(timezone.utc).isoformat(),
        "selection": ["all"],
        "pairs": completed,
        "inference": {
            "source": args.endpoint,
            "elapsed_seconds": time.perf_counter() - started,
            "resumable_progress": str(progress_path),
        },
    }
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    with temporary.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    os.replace(temporary, args.output)
    progress_path.unlink()
    print(f"completed: {args.output}", flush=True)


if __name__ == "__main__":
    main()
