#!/usr/bin/env python3
"""Interactive 3D editor for a GLB building model and a KML LookAt trajectory."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import mimetypes
import sys
from urllib.parse import unquote
import threading
import urllib.error
import urllib.request
import webbrowser
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


EARTH_RADIUS_M = 6_378_137.0
PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_KML = PROJECT_DIR / "examples" / "Tour_1565.kml"
HTML_TEMPLATE = PROJECT_DIR / "three_editor.html"
sys.path.insert(0, str(PROJECT_DIR.parent / "remote_tools"))
from image_order import ordered_images

IMAGE_LIBRARY_DIR = PROJECT_DIR.parent / "reconstruction_inputs"
CACHE_LIBRARY_DIR = PROJECT_DIR.parent / "prediction_caches"
MODEL_LIBRARY_DIR = PROJECT_DIR.parent / "models"
DEFAULT_IMAGE_SET = "building_1565_images_01_50"
UAV_IMAGE_DIR = IMAGE_LIBRARY_DIR / DEFAULT_IMAGE_SET
DEFAULT_MODEL_HASH = "c791c9af4560031835f918342669ae4d04a2314db597cfc8b5c3a184a487c977"

PREDICTION_PROVIDERS = {
    "lamp": {"label": "LaMP", "remote_fallback": True},
    "pace_final": {"label": "PACE Final", "remote_fallback": False},
}

# Bind every verified bundled GLB to its source images and prediction cache.
MODEL_IMAGE_PROFILES = {
    "c791c9af4560031835f918342669ae4d04a2314db597cfc8b5c3a184a487c977": {
        "image_set": DEFAULT_IMAGE_SET,
        "count": 50,
        "label": "building_1565",
        "file": "building_1565_50views.glb",
        "cache": "building_1565_images_01_50.lamp_cache.json",
        "caches": {
            "lamp": "building_1565_images_01_50.lamp_cache.json",
            "pace_final": "building_1565_images_01_50.pace_cache.json",
        },
    },
    "58edb309a106a139690594b562d346d169209c4c920ad1730b45d40f7ad30269": {
        "image_set": "building_0839_images_01_50",
        "count": 50,
        "label": "building_0839",
        "file": "building_0839_50views.glb",
        "cache": "building_0839_images_01_50.lamp_cache.json",
        "caches": {
            "lamp": "building_0839_images_01_50.lamp_cache.json",
            "pace_final": "building_0839_images_01_50.pace_cache.json",
        },
    },
    "463f6de2988c384399a2c379f6d6bd8addb4fa510627b1268eae80ebea3c2614": {
        "image_set": "building_1374_images_01_50",
        "count": 50,
        "label": "building_1374",
        "file": "building_1374_50views.glb",
        "cache": "building_1374_images_01_50.lamp_cache.json",
        "caches": {
            "lamp": "building_1374_images_01_50.lamp_cache.json",
            "pace_final": "building_1374_images_01_50.pace_cache.json",
        },
    },
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


@dataclass
class LookAtSample:
    index: int
    east_m: float
    north_m: float
    up_m: float
    target_east_m: float
    target_north_m: float
    target_up_m: float
    longitude: float
    latitude: float
    altitude_m: float
    heading_deg: float
    tilt_deg: float
    range_m: float
    duration_s: float


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _children_by_name(element: ET.Element) -> dict[str, str]:
    return {
        _local_name(child.tag): (child.text or "").strip()
        for child in element
        if (child.text or "").strip()
    }


def _camera_offset(heading_deg: float, tilt_deg: float, range_m: float) -> tuple[float, float, float]:
    heading = math.radians(heading_deg)
    tilt = math.radians(tilt_deg)
    horizontal = range_m * math.sin(tilt)
    return (
        -horizontal * math.sin(heading),
        -horizontal * math.cos(heading),
        range_m * math.cos(tilt),
    )


def parse_kml_lookat(path: Path) -> tuple[list[LookAtSample], dict]:
    root = ET.parse(path).getroot()
    records: list[tuple[dict[str, str], float]] = []

    for fly_to in (node for node in root.iter() if _local_name(node.tag) == "FlyTo"):
        duration = 0.0
        look_at = None
        for child in fly_to:
            name = _local_name(child.tag)
            if name == "duration" and child.text:
                duration = float(child.text)
            elif name == "LookAt":
                look_at = child
        if look_at is not None:
            records.append((_children_by_name(look_at), duration))

    if not records:
        records = [
            (_children_by_name(node), 0.0)
            for node in root.iter()
            if _local_name(node.tag) == "LookAt"
        ]
    if not records:
        raise ValueError(f"No LookAt elements found in {path}")

    first = records[0][0]
    lon0 = float(first["longitude"])
    lat0 = float(first["latitude"])
    alt0 = float(first.get("altitude", 0.0))
    cos_lat0 = math.cos(math.radians(lat0))
    samples: list[LookAtSample] = []
    headings: list[float] = []

    for index, (values, duration) in enumerate(records):
        longitude = float(values["longitude"])
        latitude = float(values["latitude"])
        altitude = float(values.get("altitude", 0.0))
        heading = float(values.get("heading", 0.0))
        tilt = float(values.get("tilt", 0.0))
        range_m = float(values.get("range", 0.0))
        target_east = math.radians(longitude - lon0) * EARTH_RADIUS_M * cos_lat0
        target_north = math.radians(latitude - lat0) * EARTH_RADIUS_M
        target_up = altitude - alt0
        offset_east, offset_north, offset_up = _camera_offset(heading, tilt, range_m)
        samples.append(
            LookAtSample(
                index=index,
                east_m=target_east + offset_east,
                north_m=target_north + offset_north,
                up_m=target_up + offset_up,
                target_east_m=target_east,
                target_north_m=target_north,
                target_up_m=target_up,
                longitude=longitude,
                latitude=latitude,
                altitude_m=altitude,
                heading_deg=heading,
                tilt_deg=tilt,
                range_m=range_m,
                duration_s=duration,
            )
        )
        headings.append(heading)

    unwrapped = [headings[0]]
    for heading in headings[1:]:
        delta = (heading - unwrapped[-1] + 180.0) % 360.0 - 180.0
        unwrapped.append(unwrapped[-1] + delta)
    ranges = [sample.range_m for sample in samples]
    ups = [sample.up_m for sample in samples]
    summary = {
        "name": path.name,
        "count": len(samples),
        "turns": (unwrapped[-1] - unwrapped[0]) / 360.0 if len(unwrapped) > 1 else 0.0,
        "range_min_m": min(ranges),
        "range_max_m": max(ranges),
        "height_min_m": min(ups),
        "height_max_m": max(ups),
        "origin_longitude": lon0,
        "origin_latitude": lat0,
        "origin_altitude_m": alt0,
    }
    return samples, summary


def write_csv(samples: list[LookAtSample], destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    rows = [asdict(sample) for sample in samples]
    with destination.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def export_preview(samples: list[LookAtSample], destination: Path) -> None:
    import matplotlib.pyplot as plt
    import numpy as np

    points = np.array([[sample.east_m, sample.north_m, sample.up_m] for sample in samples])
    destination.parent.mkdir(parents=True, exist_ok=True)
    figure = plt.figure(figsize=(9, 7), dpi=180)
    axis = figure.add_subplot(111, projection="3d")
    axis.plot(points[:, 0], points[:, 1], points[:, 2], color="#ff4d5a", linewidth=2.2)
    axis.set_xlabel("East (m)")
    axis.set_ylabel("North (m)")
    axis.set_zlabel("Up (m)")
    axis.set_title("KML LookAt 3D trajectory")
    figure.tight_layout()
    figure.savefig(destination, bbox_inches="tight")
    plt.close(figure)


def build_html(
    samples: list[LookAtSample],
    summary: dict,
    image_sets: dict[str, list[Path]],
    default_image_set: str,
) -> str:
    if not HTML_TEMPLATE.is_file():
        raise FileNotFoundError(f"3D editor template not found: {HTML_TEMPLATE}")
    payload = {
        "points": [asdict(sample) for sample in samples],
        "summary": summary,
        "images": [p.name for p in image_sets[default_image_set]],
        "image_sets": {name: [p.name for p in images] for name, images in image_sets.items()},
        "default_image_set": default_image_set,
        "model_image_profiles": MODEL_IMAGE_PROFILES,
        "prediction_providers": PREDICTION_PROVIDERS,
        "models": [{"hash": model_hash, **profile} for model_hash, profile in MODEL_IMAGE_PROFILES.items()],
        "default_model_hash": DEFAULT_MODEL_HASH,
    }
    template = HTML_TEMPLATE.read_text(encoding="utf-8")
    return template.replace(
        "__INITIAL_DATA__",
        json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")).replace("<", "\\u003c"),
    )


def serve(
    html: str,
    host: str,
    port: int,
    open_browser: bool,
    lamp_api_url: str,
    image_sets: dict[str, list[Path]],
    default_image_set: str,
) -> None:
    page = html.encode("utf-8")
    image_paths = {set_name: {p.name: p for p in images} for set_name, images in image_sets.items()}
    cache_names = {
        name
        for profile in MODEL_IMAGE_PROFILES.values()
        for name in profile.get("caches", {"lamp": profile["cache"]}).values()
    }
    model_paths = {profile["file"]: MODEL_LIBRARY_DIR / profile["file"] for profile in MODEL_IMAGE_PROFILES.values()}
    assets = {
        "/orbit_math.js": PROJECT_DIR / "orbit_math.js",
        "/rendering.js": PROJECT_DIR / "rendering.js",
        "/vendor/three.module.js": PROJECT_DIR / "vendor" / "three.module.js",
        "/vendor/GLTFLoader.js": PROJECT_DIR / "vendor" / "GLTFLoader.js",
        "/vendor/BufferGeometryUtils.js": PROJECT_DIR / "vendor" / "BufferGeometryUtils.js",
    }

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            request_path = self.path.split("?", 1)[0]
            if request_path.startswith("/uav-images/"):
                relative = unquote(request_path[len("/uav-images/"):])
                if "/" in relative:
                    set_name, name = relative.split("/", 1)
                else:  # backward-compatible URL for exported/older pages
                    set_name, name = default_image_set, relative
                if set_name not in image_paths or name not in image_paths[set_name]:
                    self.send_error(404, "Image not in configured directory")
                    return
                path = image_paths[set_name][name]
                if not path.is_file():
                    self.send_error(404)
                    return
                content = path.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
                self.send_header("Content-Length", str(len(content)))
                self.send_header("Cache-Control", "public, max-age=3600")
                self.end_headers()
                self.wfile.write(content)
                return
            if request_path.startswith("/lamp-caches/"):
                name = unquote(request_path[len("/lamp-caches/"):])
                if name not in cache_names or "/" in name or "\\" in name:
                    self.send_error(404, "Unknown prediction cache")
                    return
                path = CACHE_LIBRARY_DIR / name
                if not path.is_file():
                    self.send_error(404, "Prediction cache has not been installed")
                    return
                content = path.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(content)))
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                self.wfile.write(content)
                return
            if request_path.startswith("/models/"):
                name = unquote(request_path[len("/models/"):])
                if name not in model_paths or "/" in name or "\\" in name:
                    self.send_error(404, "Unknown bundled model")
                    return
                path = model_paths[name]
                if not path.is_file():
                    self.send_error(404, "Bundled model is missing")
                    return
                content = path.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "model/gltf-binary")
                self.send_header("Content-Length", str(len(content)))
                self.send_header("Cache-Control", "public, max-age=3600")
                self.end_headers()
                self.wfile.write(content)
                return
            if request_path in assets:
                path = assets[request_path]
                if not path.is_file():
                    self.send_error(404, f"Missing 3D dependency: {path.name}")
                    return
                content = path.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/javascript; charset=utf-8")
                self.send_header("Content-Length", str(len(content)))
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                self.wfile.write(content)
                return
            if request_path == "/favicon.ico":
                self.send_response(204)
                self.end_headers()
                return
            if request_path not in {"/", "/index.html"}:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(page)

        def do_POST(self) -> None:  # noqa: N802
            request_path = self.path.split("?", 1)[0]
            if request_path != "/api/lamp-infer":
                self.send_error(404)
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if size <= 0 or size > 4096:
                    raise ValueError("invalid request size")
                payload = self.rfile.read(size)
                request = urllib.request.Request(
                    lamp_api_url.rstrip("/") + "/infer",
                    data=payload,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=180) as response:
                    content = response.read()
                    status = response.status
            except urllib.error.HTTPError as error:
                content = error.read() or json.dumps({"error": str(error)}).encode("utf-8")
                status = error.code
            except Exception as error:
                content = json.dumps(
                    {"error": f"LaMP service unavailable: {error}"}, ensure_ascii=False
                ).encode("utf-8")
                status = 502
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def log_message(self, fmt: str, *args) -> None:
            print(f"[web] {fmt % args}")

    server = ThreadingHTTPServer((host, port), Handler)
    url = f"http://{host}:{port}/"
    print(f"KML 3D editor: {url}")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kml", type=Path, default=DEFAULT_KML, help="Input KML containing LookAt samples")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7872)
    parser.add_argument(
        "--lamp-api-url",
        default="http://127.0.0.1:8765",
        help="Persistent LaMP inference service URL",
    )
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--no-serve", action="store_true", help="Only run requested exports")
    parser.add_argument("--export-csv", type=Path)
    parser.add_argument("--export-preview", type=Path)
    parser.add_argument("--export-html", type=Path)
    args = parser.parse_args()

    if not args.kml.is_file():
        parser.error(f"KML file not found: {args.kml}")
    required_sets = sorted({profile["image_set"] for profile in MODEL_IMAGE_PROFILES.values()})
    image_sets = {
        name: ordered_images(IMAGE_LIBRARY_DIR / name)
        for name in required_sets
    }
    default_image_set = DEFAULT_IMAGE_SET
    for model_hash, profile in MODEL_IMAGE_PROFILES.items():
        model_path = MODEL_LIBRARY_DIR / profile["file"]
        if not model_path.is_file():
            parser.error(f"bundled model not found: {model_path}")
        actual_hash = sha256_file(model_path)
        if actual_hash != model_hash:
            parser.error(
                f"bundled model hash mismatch for {profile['file']}: "
                f"expected {model_hash}, observed {actual_hash}"
            )
        cache_path = CACHE_LIBRARY_DIR / profile["cache"]
        if not cache_path.is_file():
            parser.error(f"bundled prediction cache not found: {cache_path}")
    assert HTML_TEMPLATE.is_file(), f"missing template: {HTML_TEMPLATE}"
    for destination in (args.export_csv, args.export_preview, args.export_html):
        assert destination is None or not destination.exists(), f"refusing to overwrite: {destination}"
    samples, summary = parse_kml_lookat(args.kml)
    html = build_html(samples, summary, image_sets, default_image_set)
    if args.export_csv:
        write_csv(samples, args.export_csv)
        print(f"CSV: {args.export_csv}")
    if args.export_preview:
        export_preview(samples, args.export_preview)
        print(f"3D preview: {args.export_preview}")
    if args.export_html:
        args.export_html.parent.mkdir(parents=True, exist_ok=True)
        args.export_html.write_text(html, encoding="utf-8")
        print(f"HTML: {args.export_html}")
    print(
        f"Loaded {summary['count']} LookAt samples, {summary['turns']:.3f} turns, "
        f"range {summary['range_min_m']:.1f} to {summary['range_max_m']:.1f} m"
    )
    if not args.no_serve:
        serve(
            html,
            args.host,
            args.port,
            not args.no_browser,
            args.lamp_api_url,
            image_sets,
            default_image_set,
        )


if __name__ == "__main__":
    main()
