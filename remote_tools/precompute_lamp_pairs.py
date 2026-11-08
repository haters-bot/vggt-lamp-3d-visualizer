#!/usr/bin/env python3
"""Compute ordered-pair LaMP predictions with one persistent model load.

Output is a NEW run directory containing lamp_cache.json. Existing directories
are rejected. Numeric predictions are deterministic; timestamps/timings vary.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from image_order import ordered_images, pair_indices


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image-dir', required=True, type=Path)
    parser.add_argument('--vggt-weight', required=True, type=Path)
    parser.add_argument('--bundle', required=True, type=Path)
    parser.add_argument('--output-dir', required=True, type=Path)
    parser.add_argument('--pairs', nargs='+', default=['all'], metavar='all|ring0|stride N')
    parser.add_argument('--expected-images', type=int)
    parser.add_argument('--max-memory-gb', type=float, help='Total GPU budget; defaults to detected VRAM minus 1 GB')
    args = parser.parse_args()
    assert not args.output_dir.exists(), f"refusing existing output directory: {args.output_dir}"
    assert args.vggt_weight.is_file(), f"missing weight: {args.vggt_weight}"
    assert args.bundle.is_dir(), f"missing bundle: {args.bundle}"
    os.environ.setdefault('CUBLAS_WORKSPACE_CONFIG', ':4096:8')
    images = ordered_images(args.image_dir)
    assert args.expected_images is None or len(images) == args.expected_images, f"expected {args.expected_images} images, observed {len(images)}"
    pairs = pair_indices(len(images), args.pairs)

    # Heavy imports follow path/order assertions; never write to dependency trees.
    import numpy as np
    import torch
    from PIL import Image
    from lamp_pair_server import LampRuntime

    for path in images:
        with Image.open(path) as image:
            assert image.width > 0 and image.height > 0, f"invalid image dimensions: {path}, {image.size}"
            image.verify()
    assert torch.cuda.is_available(), 'CUDA unavailable'
    torch.set_num_threads(1)
    torch.manual_seed(2026)
    np.random.seed(2026)
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True
    torch.use_deterministic_algorithms(True)
    torch.set_float32_matmul_precision('high')
    total = torch.cuda.get_device_properties(0).total_memory
    total_gb = total / 1e9
    memory_budget_gb = args.max_memory_gb or max(2.0, total_gb - 1.0)
    assert 1.0 < memory_budget_gb <= total_gb, (
        f'memory budget must be between 1 GB and detected VRAM {total_gb:.2f} GB: {memory_budget_gb}'
    )
    # Keep 0.75 GB outside the PyTorch allocator for the CUDA context/libraries.
    allocator_fraction = min(1.0, (memory_budget_gb - 0.75) * 1e9 / total)
    torch.cuda.set_per_process_memory_fraction(allocator_fraction, 0)
    args.output_dir.mkdir(parents=True, exist_ok=False)
    result = {
        'schema_version': 1, 'index_base': 0,
        'image_dir': str(args.image_dir.resolve()), 'images': [p.name for p in images],
        'image_sha256': [sha256(p) for p in images],
        'bundle': str(args.bundle.resolve()), 'vggt_weight_sha256': sha256(args.vggt_weight),
        'created': datetime.now(timezone.utc).isoformat(),
        'selection': args.pairs, 'pairs': {},
        'inference': {'seed': 2026, 'torch': torch.__version__, 'image_size': 518,
                      'model_dtype': 'float32', 'autocast': 'bfloat16',
                      'pooled_features': 'float16 then float32 (paper cache convention)',
                      'rotation_angle': 'degrees(acos(clip((trace(R)-1)/2,-1,1)))',
                      'yaw': 'degrees(atan2(R[1,0],R[0,0])); same as heading',
                      'decoded_label_index': 'zero-based index into decoder d_values grid',
                      'max_memory_gb': memory_budget_gb},
    }
    print(f"loading model once; images={len(images)}, ordered pairs={len(pairs)}", flush=True)
    runtime = LampRuntime(args.image_dir, args.vggt_weight, args.bundle, 'cuda')
    started = time.perf_counter()
    with (args.output_dir / 'progress.jsonl').open('x', encoding='utf-8') as progress:
        for number, (a, b) in enumerate(pairs, 1):
            torch.cuda.synchronize()
            tick = time.perf_counter()
            prediction = runtime.infer(a + 1, b + 1)
            torch.cuda.synchronize()
            continuous, decoded = prediction['continuous'], prediction['map_hard']
            value = {
                'heading_deg': continuous['heading_deg'], 'yaw_deg': continuous['yaw_deg'],
                'rotation_angle_deg': continuous['rotation_angle_deg'],
                'range_m': continuous['selected_range_m'],
                'decoded': {k: decoded[k] for k in ('heading_deg', 'range_m', 'label_index', 'step_difference')},
                'seconds': time.perf_counter() - tick,
            }
            key = f'{a}->{b}'
            result['pairs'][key] = value
            progress.write(json.dumps({'key': key, 'value': value}, allow_nan=False) + '\n')
            progress.flush()
            if number == 1 or number % 25 == 0 or number == len(pairs):
                print(f"{number}/{len(pairs)} elapsed={time.perf_counter()-started:.1f}s "
                      f"peak_reserved_GB={torch.cuda.max_memory_reserved()/1e9:.3f}", flush=True)
    assert len(result['pairs']) == len(pairs), f"unexpected pair count: {len(result['pairs'])}, {len(pairs)}"
    result['inference']['elapsed_seconds'] = time.perf_counter() - started
    result['inference']['peak_allocated_gb'] = torch.cuda.max_memory_allocated() / 1e9
    result['inference']['peak_reserved_gb'] = torch.cuda.max_memory_reserved() / 1e9
    with (args.output_dir / 'lamp_cache.json').open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')
    print(f"completed: {args.output_dir / 'lamp_cache.json'}", flush=True)


if __name__ == '__main__':
    main()
