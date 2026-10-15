# Terrain data and reproducible examples

TracerTool reads local elevation rasters; it does not provide a licensed terrain
dataset. Six private reference GeoTIFFs were used during development. Their
pixels, filenames, detailed bounds, inventory and terrain-derived screenshots
are excluded from the public repository. Aggregate validation uses anonymous
tile identifiers. Those private cases cannot be reproduced from this repository.

## Public synthetic example

Run these commands from an installed source checkout:

```sh
python scripts/create_demo.py --output artifacts/demo
python -m tracertool artifacts/demo/demo.tracer.json
```

The generator creates deterministic, entirely synthetic terrain and editable
example lines. It requires no private files or downloads. The README screenshot
shows this generated fixture, not a real landscape. The generated terrain is
for learning and regression checks; it does not validate real-world accuracy.
See [the user guide](USER_GUIDE.md) for tracing and editing instructions.

Public tests generate their own valleys, ridges, levees, slope breaks, pits,
flats, calibrated bands and NoData barriers. Run `python -m pytest -q` to repeat
the checks. [VALIDATION.md](VALIDATION.md) separates those tests from private
visual exercises and measurements.

## Supplying your own data

Use a north-up single-band elevation GeoTIFF. Confirm its horizontal CRS,
resolution, scale/offset and elevation units. The app preserves source Z;
display exaggeration does not perform a vertical datum transformation.
Geographic or missing CRS is viewable but requires a deliberate projected copy
before tracing. Large rasters may use a disclosed working grid.

Keep employer, customer and restricted datasets outside Git. Generated projects
and exports are ignored by default. For bug reports, prefer a small synthetic
reproduction or data with explicit redistribution permission. Review filenames,
paths, coordinates, project JSON, logs and screenshots before attaching them.
