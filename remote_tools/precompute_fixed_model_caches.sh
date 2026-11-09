#!/usr/bin/env bash
set -euo pipefail

# Generate every cache used by the fixed GLB library on the remote GPU host.
# Usage: bash remote_tools/precompute_fixed_model_caches.sh [setup-root]

setup_root="${1:-$HOME/work/lamp_setup}"
repo_dir="$setup_root/vggt-pairuav-main"
weight="${VGGT_WEIGHT:-$HOME/models/vggt/model.pt}"
bundle="${LAMP_BUNDLE:-$setup_root/lamp_challenge_entry_822841_v1}"
output_root="${CACHE_OUTPUT_ROOT:-$setup_root/generated_prediction_caches}"
python_bin="${PYTHON_BIN:-python3}"

[[ -f "$repo_dir/remote_tools/precompute_lamp_pairs.py" ]] || { echo "missing precompute script under $repo_dir" >&2; exit 1; }
[[ -f "$weight" ]] || { echo "missing VGGT weight: $weight" >&2; exit 1; }
[[ -d "$bundle" ]] || { echo "missing LaMP bundle: $bundle" >&2; exit 1; }

export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0}"
export PYTHONDONTWRITEBYTECODE=1
export CUBLAS_WORKSPACE_CONFIG=:4096:8
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1

mkdir -p "$output_root"

images_1565="$setup_root/building_1565_images_01_50"
images_0839="$setup_root/building_0839_images_01_50"
images_1374="$setup_root/building_1374_images_01_50"

for image_dir in "$images_1565" "$images_0839" "$images_1374"; do
  [[ -d "$image_dir" ]] || { echo "missing image directory: $image_dir" >&2; exit 1; }
  count=$(find "$image_dir" -maxdepth 1 -type f \( -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.png' \) | wc -l)
  [[ "$count" -eq 50 ]] || { echo "expected 50 images in $image_dir, observed $count" >&2; exit 1; }
done

run_cache() {
  local label="$1" image_dir="$2" expected="$3" final_name="$4"
  local final_path="$output_root/$final_name"
  local run_dir="$output_root/run_$label"
  if [[ -f "$final_path" ]]; then
    echo "skip $label: $final_path already exists"
    return
  fi
  if [[ -e "$run_dir" ]]; then
    echo "unfinished output exists: $run_dir" >&2
    echo "move it aside after inspecting progress.jsonl, then restart this script" >&2
    exit 1
  fi
  echo "=== generating $label ==="
  "$python_bin" "$repo_dir/remote_tools/precompute_lamp_pairs.py" \
    --image-dir "$image_dir" \
    --expected-images "$expected" \
    --vggt-weight "$weight" \
    --bundle "$bundle" \
    --pairs all \
    --output-dir "$run_dir"
  cp "$run_dir/lamp_cache.json" "$final_path"
  echo "ready: $final_path"
}

run_cache "1565_50" "$images_1565" 50 "building_1565_images_01_50.lamp_cache.json"
run_cache "0839_50" "$images_0839" 50 "building_0839_images_01_50.lamp_cache.json"
run_cache "1374_50" "$images_1374" 50 "building_1374_images_01_50.lamp_cache.json"

echo "=== all fixed-model caches completed ==="
sha256sum "$output_root"/*.lamp_cache.json
