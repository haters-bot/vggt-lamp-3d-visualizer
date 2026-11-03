"""Shared, dependency-free input-order contract (indices are zero based)."""
import re
from pathlib import Path


def ordered_images(directory: Path) -> list[Path]:
    assert directory.is_dir(), f"image directory missing: {directory}"
    images = [p for p in directory.iterdir() if p.suffix.lower() in {'.jpg', '.jpeg', '.png'}]
    assert len(images) >= 2, f"expected >=2 images, observed {len(images)} in {directory}"
    keys = {}
    for path in images:
        digits = re.findall(r'\d+', path.stem)
        assert digits, f"image filename has no numeric order: {path.name}"
        key = tuple(map(int, digits))
        assert key not in keys, f"ambiguous numeric order {key}: {keys.get(key)}, {path.name}"
        keys[key] = path
    return [keys[key] for key in sorted(keys)]


def pair_indices(count: int, selection: list[str]) -> list[tuple[int, int]]:
    assert count >= 2, f"expected >=2 images, observed {count}"
    if selection == ['all']:
        return [(a, b) for a in range(count) for b in range(count) if a != b]
    if selection == ['ring0']:
        return [(0, b) for b in range(1, count)]
    assert len(selection) == 2 and selection[0] == 'stride', f"expected all|ring0|stride N: {selection}"
    stride = int(selection[1])
    assert 0 < stride < count, f"expected 0 < stride < {count}, observed {stride}"
    return [(a, a + stride) for a in range(count - stride)]
