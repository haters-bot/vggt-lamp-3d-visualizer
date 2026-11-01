#!/usr/bin/env python3
"""Low-memory LaMP inference for one ordered UAV image pair."""

from __future__ import annotations

import argparse
import gc
import json
import re
from pathlib import Path

import numpy as np
import torch
from PIL import Image

from pairuav.data import build_image_transform
from pairuav.geometry import frame_step, grid_from_d_values
from pairuav.head_io import load_range_head, load_sixdof_head
from pairuav.heads import heading_from_rot_torch, make_pair_input
from pairuav.metrics import wrap180
from pairuav.postproc_maphard import map_decode


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image-a", type=Path, required=True)
    parser.add_argument("--image-b", type=Path, required=True)
    parser.add_argument("--vggt-weight", type=Path, required=True)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--image-size", type=int, default=518)
    return parser.parse_args()


def load_pair(path_a: Path, path_b: Path, image_size: int) -> torch.Tensor:
    transform = build_image_transform(image_size)
    tensors = []
    for path in (path_a, path_b):
        with Image.open(path) as image:
            tensors.append(transform(image.convert("RGB")))
    return torch.stack(tensors, dim=0).unsqueeze(0)


def load_backbone(weight: Path, device: torch.device, dtype: torch.dtype):
    from vggt.models.vggt import VGGT

    model = VGGT()
    try:
        state = torch.load(weight, map_location="cpu", weights_only=True, mmap=True)
    except TypeError:
        state = torch.load(weight, map_location="cpu")
    try:
        model.load_state_dict(state, strict=True, assign=True)
    except TypeError:
        model.load_state_dict(state, strict=True)
    model.camera_head = None
    model.point_head = None
    model.depth_head = None
    model.track_head = None
    del state
    gc.collect()
    return model.to(device=device, dtype=dtype).eval()


def pooled_pair_features(model, images: torch.Tensor, dtype: torch.dtype) -> torch.Tensor:
    with torch.inference_mode(), torch.amp.autocast("cuda", dtype=dtype, enabled=images.is_cuda):
        token_layers, patch_start = model.aggregator(images)
        patches = token_layers[-1][:, :, patch_start:, :]
        return torch.cat((patches.mean(dim=2), patches.max(dim=2).values), dim=-1).float()


def frame_number(path: Path) -> int | None:
    match = re.search(r"(\d+)", path.stem)
    return int(match.group(1)) if match else None


def main() -> None:
    args = parse_args()
    device = torch.device(args.device if torch.cuda.is_available() else "cpu")
    dtype = torch.bfloat16 if device.type == "cuda" else torch.float32
    bundle = args.bundle.resolve()

    model = load_backbone(args.vggt_weight, device, dtype)
    images = load_pair(args.image_a, args.image_b, args.image_size).to(device=device, dtype=dtype)
    features = pooled_pair_features(model, images, dtype)
    del model, images
    if device.type == "cuda":
        torch.cuda.empty_cache()

    angle, _, _ = load_sixdof_head(
        bundle / "checkpoints/S0_rich_noc/head_best_angle.pt",
        4096,
        device,
        config=bundle / "configs/angle_s0.json",
    )
    close_head, close_cfg, _ = load_range_head(
        bundle / "checkpoints/C_rel_rich/range_head_best_distance.pt",
        4096,
        device,
        config=bundle / "configs/range_c_rel_rich.json",
    )
    far_head, far_cfg, _ = load_range_head(
        bundle / "checkpoints/B_mse_ab/range_head_best_distance.pt",
        4096,
        device,
        config=bundle / "configs/range_b_mse_ab.json",
    )

    with torch.inference_mode():
        rotation, translation = angle(features)
        heading = float(wrap180(heading_from_rot_torch(rotation).cpu().numpy())[0])
        range_close = float(close_head(make_pair_input(features, str(close_cfg["input_mode"]))).item())
        range_far = float(far_head(make_pair_input(features, str(far_cfg["input_mode"]))).item())
    selected_range = range_far if abs(range_close) > 80.0 else range_close

    grid_d, grid_heading, grid_range = grid_from_d_values(bundle / "decoder/d_values.json")
    weights = json.loads((bundle / "decoder/p348_map_weights.json").read_text(encoding="utf-8"))
    decoded_d = int(map_decode(
        np.asarray([heading]),
        np.asarray([selected_range]),
        grid_d,
        grid_heading,
        grid_range,
        float(weights["w_h"]),
        float(weights["w_r"]),
    )[0])

    source_frame = frame_number(args.image_a)
    predicted_frame = None
    if source_frame is not None:
        target_step = frame_step(source_frame) + decoded_d
        candidates = np.asarray([frame_step(i) for i in range(1, 55)])
        predicted_frame = int(np.argmin(np.abs(candidates - target_step)) + 1)

    result = {
        "image_a": str(args.image_a.resolve()),
        "image_b": str(args.image_b.resolve()),
        "continuous": {
            "heading_deg": heading,
            "range_close_m": range_close,
            "range_far_m": range_far,
            "selected_range_m": selected_range,
            "translation_aux": translation[0].detach().cpu().tolist(),
        },
        "map_hard": {
            "step_difference": decoded_d,
            "heading_deg": float(wrap180(4.0 * decoded_d)),
            "range_m": -0.5 * decoded_d,
            "predicted_target_frame": predicted_frame,
        },
        "cuda_peak_gib": (
            torch.cuda.max_memory_allocated(device) / 1024**3 if device.type == "cuda" else None
        ),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
