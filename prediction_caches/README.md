# Model prediction caches

Place generated LaMP cache files in this directory. The browser selects them
automatically from the loaded GLB content hash.

Expected filenames:

- `building_1565_images_01_50.lamp_cache.json`
- `building_0839_images_01_50.lamp_cache.json`
- `building_1374_images_01_50.lamp_cache.json`

The three verified cache files are committed with the fixed-model release.
Regenerate them with `remote_tools/precompute_lamp_pairs.py` or the resumable
HTTP helper, then validate image order, counts, and SHA-256 before replacement.

PACE Final caches are optional and use schema version 2:

- `building_1565_images_01_50.pace_cache.json`
- `building_0839_images_01_50.pace_cache.json`
- `building_1374_images_01_50.pace_cache.json`

Generate them with `remote_tools/precompute_pace_pairs.py`. The application
keeps working with LaMP when a PACE cache is absent; selecting PACE Final then
reports the exact missing filename.
