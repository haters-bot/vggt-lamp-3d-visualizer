# Model prediction caches

Place generated LaMP cache files in this directory. The browser selects them
automatically from the loaded GLB content hash.

Expected filenames:

- `building_1565_images_01_08.lamp_cache.json`
- `building_1565_images_01_50.lamp_cache.json`
- `building_0839_images_01_50.lamp_cache.json`
- `building_1374_images_01_50.lamp_cache.json`

The four verified cache files are committed with the fixed-model release.
Regenerate them with `remote_tools/precompute_lamp_pairs.py` or the resumable
HTTP helper, then validate image order, counts, and SHA-256 before replacement.
