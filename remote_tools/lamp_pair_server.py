#!/usr/bin/env python3
"""Persistent HTTP service for low-memory LaMP pair inference."""

from __future__ import annotations

import argparse
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np
import torch

from infer_lamp_pair import load_backbone, load_pair, pooled_pair_features
from image_order import ordered_images
from pairuav.geometry import frame_step, grid_from_d_values
from pairuav.head_io import load_range_head, load_sixdof_head
from pairuav.heads import heading_from_rot_torch, make_pair_input
from pairuav.metrics import wrap180
from pairuav.postproc_maphard import map_decode


class LampRuntime:
    def __init__(self, image_dir: Path, weight: Path, bundle: Path, device_name: str) -> None:
        assert image_dir.is_dir(), f"missing image directory: {image_dir}"
        assert weight.is_file(), f"missing VGGT weight: {weight}"
        required = ['checkpoints/S0_rich_noc/head_best_angle.pt',
                    'checkpoints/C_rel_rich/range_head_best_distance.pt',
                    'checkpoints/B_mse_ab/range_head_best_distance.pt',
                    'configs/angle_s0.json', 'configs/range_c_rel_rich.json',
                    'configs/range_b_mse_ab.json', 'decoder/d_values.json',
                    'decoder/p348_map_weights.json']
        assert all((bundle / p).is_file() for p in required), f"missing bundle files: {[p for p in required if not (bundle / p).is_file()]}"
        self.images = ordered_images(image_dir)
        self.image_dir = image_dir.resolve()
        self.bundle = bundle.resolve()
        self.device = torch.device(device_name)
        assert self.device.type != "cuda" or torch.cuda.is_available(), "requested CUDA is unavailable"
        self.dtype = torch.bfloat16 if self.device.type == "cuda" else torch.float32
        self.lock = threading.Lock()
        self.model = load_backbone(weight, self.device, torch.float32)
        self.angle, _, _ = load_sixdof_head(
            self.bundle / "checkpoints/S0_rich_noc/head_best_angle.pt",
            4096,
            self.device,
            config=self.bundle / "configs/angle_s0.json",
        )
        self.close_head, self.close_cfg, _ = load_range_head(
            self.bundle / "checkpoints/C_rel_rich/range_head_best_distance.pt",
            4096,
            self.device,
            config=self.bundle / "configs/range_c_rel_rich.json",
        )
        self.far_head, self.far_cfg, _ = load_range_head(
            self.bundle / "checkpoints/B_mse_ab/range_head_best_distance.pt",
            4096,
            self.device,
            config=self.bundle / "configs/range_b_mse_ab.json",
        )
        self.grid_d, self.grid_heading, self.grid_range = grid_from_d_values(
            self.bundle / "decoder/d_values.json"
        )
        weights = json.loads(
            (self.bundle / "decoder/p348_map_weights.json").read_text(encoding="utf-8")
        )
        self.weight_h = float(weights["w_h"])
        self.weight_r = float(weights["w_r"])

    def image_path(self, frame: int) -> Path:
        if not 1 <= frame <= len(self.images):
            raise ValueError(f"one-based frame must be between 1 and {len(self.images)}: {frame}")
        return self.images[frame - 1]

    def infer(self, frame_a: int, frame_b: int) -> dict:
        path_a, path_b = self.image_path(frame_a), self.image_path(frame_b)
        with self.lock, torch.inference_mode():
            images = load_pair(path_a, path_b, 518).to(device=self.device, dtype=torch.float32)
            features = pooled_pair_features(self.model, images, self.dtype).half().float()
            rotation, translation = self.angle(features)
            heading = float(wrap180(heading_from_rot_torch(rotation).cpu().numpy())[0])
            rotation_np = rotation[0].double().cpu().numpy()
            rotation_angle = float(np.rad2deg(np.arccos(np.clip((np.trace(rotation_np) - 1) / 2, -1, 1))))
            range_close = float(
                self.close_head(make_pair_input(features, str(self.close_cfg["input_mode"]))).item()
            )
            range_far = float(
                self.far_head(make_pair_input(features, str(self.far_cfg["input_mode"]))).item()
            )
            selected_range = range_far if abs(range_close) > 80.0 else range_close
            decoded_d = int(
                map_decode(
                    np.asarray([heading]),
                    np.asarray([selected_range]),
                    self.grid_d,
                    self.grid_heading,
                    self.grid_range,
                    self.weight_h,
                    self.weight_r,
                )[0]
            )
            target_step = frame_step(frame_a) + decoded_d
            candidate_steps = np.asarray([frame_step(i) for i in range(1, 55)])
            predicted_frame = int(np.argmin(np.abs(candidate_steps - target_step)) + 1)
            return {
                "frame_a": frame_a,
                "frame_b": frame_b,
                "continuous": {
                    "heading_deg": heading,
                    "yaw_deg": heading,
                    "rotation_angle_deg": rotation_angle,
                    "range_close_m": range_close,
                    "range_far_m": range_far,
                    "selected_range_m": selected_range,
                    "translation_aux": translation[0].detach().cpu().tolist(),
                },
                "map_hard": {
                    "step_difference": decoded_d,
                    "label_index": int(np.flatnonzero(self.grid_d == decoded_d)[0]),
                    "heading_deg": float(wrap180(4.0 * decoded_d)),
                    "range_m": -0.5 * decoded_d,
                    "predicted_target_frame": predicted_frame,
                },
                "cuda_peak_gib": (
                    torch.cuda.max_memory_allocated(self.device) / 1024**3
                    if self.device.type == "cuda"
                    else None
                ),
            }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image-dir", type=Path, required=True)
    parser.add_argument("--vggt-weight", type=Path, required=True)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--device", default="cuda")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    runtime = LampRuntime(args.image_dir, args.vggt_weight, args.bundle, args.device)

    class Handler(BaseHTTPRequestHandler):
        def send_json(self, status: int, value: dict) -> None:
            payload = json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self) -> None:  # noqa: N802
            if self.path.split("?", 1)[0] == "/health":
                self.send_json(200, {"ok": True, "device": str(runtime.device)})
            else:
                self.send_json(404, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            if self.path.split("?", 1)[0] != "/infer":
                self.send_json(404, {"error": "not found"})
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if size <= 0 or size > 4096:
                    raise ValueError("invalid request size")
                request = json.loads(self.rfile.read(size).decode("utf-8"))
                frame_a, frame_b = int(request["frame_a"]), int(request["frame_b"])
                for key, frame in (("image_a", frame_a), ("image_b", frame_b)):
                    if key in request and request[key] != runtime.image_path(frame).name:
                        raise ValueError(f"image order mismatch: {key}={request[key]}, server={runtime.image_path(frame).name}")
                result = runtime.infer(frame_a, frame_b)
                self.send_json(200, result)
            except Exception as error:  # keep the service alive after a bad request
                self.send_json(400, {"error": str(error)})

        def log_message(self, fmt: str, *args) -> None:
            print(f"[lamp] {fmt % args}", flush=True)

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"LaMP pair service: http://{args.host}:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
