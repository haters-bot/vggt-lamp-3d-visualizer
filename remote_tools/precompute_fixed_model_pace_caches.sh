#!/usr/bin/env bash
set -euo pipefail

# Generate PACE Final caches for all three bundled 50-view buildings.
# Usage: PACE_ROOT=/path/to/PairUAV-PACE bash remote_tools/precompute_fixed_model_pace_caches.sh [setup-root]

setup_root="${1:-$HOME/work/lamp_setup}"
tool_repo="${TOOL_REPO:-$setup_root/vggt-pairuav-main}"
pace_root="${PACE_ROOT:-$setup_root/PairUAV-PACE}"
asset_root="${PACE_ASSET_ROOT:-$pace_root/assets}"
output_root="${PACE_CACHE_OUTPUT_ROOT:-$setup_root/generated_pace_caches}"
python_bin="${PYTHON_BIN:-python3}"

[[ -f "$tool_repo/remote_tools/precompute_pace_pairs.py" ]] || { echo "missing PACE cache wrapper under $tool_repo" >&2; exit 1; }
[[ -f "$pace_root/infer_pairuav_with_progress.py" ]] || { echo "missing PairUAV-PACE repository: $pace_root" >&2; exit 1; }
[[ -d "$asset_root" ]] || { echo "missing PACE assets: $asset_root" >&2; exit 1; }

export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0}"
export PYTHONDONTWRITEBYTECODE=1
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-1}"
export MKL_NUM_THREADS="${MKL_NUM_THREADS:-1}"
export OPENBLAS_NUM_THREADS="${OPENBLAS_NUM_THREADS:-1}"
mkdir -p "$output_root"

run_cache() {
  local building="$1"
  local image_dir="$setup_root/building_${building}_images_01_50"
  local run_dir="$output_root/run_${building}"
  local final_path="$output_root/building_${building}_images_01_50.pace_cache.json"
  [[ -d "$image_dir" ]] || { echo "missing image directory: $image_dir" >&2; exit 1; }
  if [[ -f "$final_path" ]]; then
    echo "skip building_$building: $final_path already exists"
    return
  fi
  [[ ! -e "$run_dir" ]] || { echo "refusing existing run directory: $run_dir" >&2; exit 1; }
  "$python_bin" "$tool_repo/remote_tools/precompute_pace_pairs.py" \
    --image-dir "$image_dir" \
    --pace-root "$pace_root" \
    --asset-root "$asset_root" \
    --expected-images 50 \
    --pairs all \
    --batch-size "${PACE_BATCH_SIZE:-1}" \
    --num-workers "${PACE_NUM_WORKERS:-2}" \
    --output-dir "$run_dir"
  cp "$run_dir/pace_cache.json" "$final_path"
  echo "ready: $final_path"
}

run_cache 1565
run_cache 0839
run_cache 1374

echo "=== all PACE caches completed ==="
sha256sum "$output_root"/*.pace_cache.json
