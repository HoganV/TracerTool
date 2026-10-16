#!/usr/bin/env python3
"""Fetch/hash-verify frozen official MN/MA pilots; never execute downloaded data."""
import argparse
import json
from pathlib import Path
import urllib.parse
import urllib.request

from tracertool.evaluation import sha256_file

HOSTS = {'enterprise.gisdata.mn.gov', 'services1.arcgis.com', 'prd-tnm.s3.amazonaws.com'}
VECTOR = 'https://enterprise.gisdata.mn.gov/aghost/rest/services/us_mn_state_dnr/water_dnr_hydrography_from_lidar/FeatureServer/1'
RASTER = 'https://enterprise.gisdata.mn.gov/agsimg/rest/services/MnTopo/2nd_Generation_Seamless_Lidar_DEM/ImageServer'
LICENSE = 'https://www.dnr.state.mn.us/sitetools/data_software_license.html'


def validate_url(url):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != 'https' or parsed.hostname not in HOSTS or parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError('Only HTTPS allowlisted public pilot service URLs are allowed')
    return url


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def copy_bounded(stream, destination, budget):
    destination = Path(destination)
    temporary = destination.with_name(destination.name + '.partial')
    count = 0
    created = False
    try:
        with temporary.open('xb') as output:
            created = True
            while block := stream.read(min(1024 * 1024, budget - count + 1)):
                count += len(block)
                if count > budget:
                    raise ValueError('Download exceeds byte budget')
                output.write(block)
        temporary.replace(destination)
    finally:
        if created:
            temporary.unlink(missing_ok=True)
    return count


def download(url, destination, budget):
    validate_url(url)
    opener = urllib.request.build_opener(SafeRedirect())
    with opener.open(urllib.request.Request(url, headers={'User-Agent': 'TracerTool-public-evaluation/1'}), timeout=90) as response:
        validate_url(response.geturl())
        return copy_bounded(response, destination, budget)


def request_json(base, params, destination):
    url = base + '?' + urllib.parse.urlencode(params)
    download(url, destination, 20_000_000)
    result = json.loads(destination.read_text())
    if result.get('error') or result.get('exceededTransferLimit'):
        raise ValueError('Official API error or incomplete feature response')
    return url, result


def verify(directory):
    import numpy as np
    import rasterio
    vector_path = directory / 'watercourses.esri.json'
    raster_path = directory / 'terrain-1m.tif'
    vector = json.loads(vector_path.read_text())
    if vector.get('error') or vector.get('exceededTransferLimit'):
        raise ValueError('Incomplete reference response')
    vertices = np.asarray([xy[:2] for f in vector['features'] for line in f['geometry']['paths'] for xy in line])
    if len(vertices) == 0 or not np.isfinite(vertices).all():
        raise ValueError('Missing/nonfinite vector geometry')
    with rasterio.open(raster_path) as ds:
        if ds.width * ds.height > 10_000_000:
            raise ValueError('Raster exceeds pilot cell budget')
        expected = rasterio.crs.CRS.from_epsg(vector['spatialReference']['wkid'])
        if ds.crs != expected or not ds.crs.is_projected:
            raise ValueError('Raster/reference CRS mismatch')
        left, bottom, right, top = ds.bounds
        covered = ((vertices[:, 0] >= left) & (vertices[:, 0] < right) &
                   (vertices[:, 1] > bottom) & (vertices[:, 1] <= top)).all()
        if not covered:
            raise ValueError('Full returned vector is not raster-covered')
        data = ds.read(1, masked=True)
        valid = (~np.ma.getmaskarray(data)) & np.isfinite(data.data)
        result = dict(features=len(vector['features']), feature_ids=[f['attributes']['objectid'] for f in vector['features']],
                      vector_bounds=[*vertices.min(axis=0).tolist(), *vertices.max(axis=0).tolist()],
                      crs=str(ds.crs), width=ds.width, height=ds.height, resolution=list(ds.res),
                      bounds=list(ds.bounds), valid_cells=int(valid.sum()), units=list(ds.units),
                      scales=list(ds.scales), offsets=list(ds.offsets), all_vertices_covered=bool(covered),
                      decoded_z_min=float((data.data[valid] * ds.scales[0] + ds.offsets[0]).min()),
                      decoded_z_max=float((data.data[valid] * ds.scales[0] + ds.offsets[0]).max()))
    result['assets'] = {key: dict(file=path.name, sha256=sha256_file(path), bytes=path.stat().st_size)
                        for key, path in [('raster', raster_path), ('reference', vector_path)]}
    result['limitations'] = ['2011 terrain-derived labels versus 2021-2023 DEM; not acquisition-matched',
                            'No independent label review; unknown band vertical units; no blind holdout']
    return result


def prepare_massachusetts(directory, bounds, *, historical_v1=False):
    """Crop native samples. historical_v1 reproduces the frozen metadata omission.

    The original pilot crop omitted band units; replay must not silently change
    its bytes. The source's metre unit is disclosed in verification, not inferred
    into frozen inputs. New crops preserve calibration and unit metadata.
    """
    import rasterio
    from rasterio.windows import from_bounds
    directory = Path(directory)
    vector = json.loads((directory / 'reference-original.esri.json').read_text())
    if vector.get('error') or vector.get('exceededTransferLimit'):
        raise ValueError('Incomplete reference response')
    for feature in vector['features']:
        feature['attributes']['objectid'] = feature['attributes']['OBJECTID']
    vector['objectIdFieldName'] = 'objectid'
    (directory / 'reference.esri.json').write_text(json.dumps(vector))
    with rasterio.open(directory / 'usgs-original.tif') as source:
        window = from_bounds(*bounds, source.transform).round_offsets().round_lengths()
        if window.width * window.height > 10_000_000 or min(window.width, window.height) < 1:
            raise ValueError('Raster crop exceeds pilot cell budget')
        if (window.col_off < 0 or window.row_off < 0 or
                window.col_off + window.width > source.width or window.row_off + window.height > source.height):
            raise ValueError('Requested crop is outside source coverage')
        profile = source.profile.copy()
        profile.update(width=int(window.width), height=int(window.height), transform=source.window_transform(window))
        # A raw read does not carry explicit GDAL validity masks. Keep the
        # mask inside the TIFF so the frozen asset hash covers its validity.
        from rasterio.enums import MaskFlags
        explicit_mask = any(MaskFlags.per_dataset in flags for flags in source.mask_flag_enums)
        with rasterio.Env(GDAL_TIFF_INTERNAL_MASK=True), rasterio.open(directory / 'terrain-crop.tif', 'w', **profile) as output:
            output.write(source.read(window=window))
            if explicit_mask:
                output.write_mask(source.dataset_mask(window=window))
            if historical_v1 and (source.scales != (1.0,) or source.offsets != (0.0,)):
                raise ValueError('Frozen crop requires identity source calibration')
            if not historical_v1:
                output.scales, output.offsets = source.scales, source.offsets
                for band, unit in enumerate(source.units, 1):
                    if unit:
                        output.set_band_unit(band, unit)


def massachusetts(directory, manifest_path, manifest, verify_only):
    """One tile (<1 GiB) plus a bounded query; no archive extraction or retry loop."""
    from tracertool.evaluation import load_pair
    lineage = manifest['lineage']
    if not verify_only:
        for name in ('usgs-original.tif', 'reference-original.esri.json', 'reference.esri.json', 'terrain-crop.tif'):
            if (directory / name).exists():
                raise ValueError('Refusing to replace existing public data; use --verify-only or a new directory')
        download(lineage['vector_native'], directory / 'reference-original.esri.json', 20_000_000)
        download(lineage['raster'], directory / 'usgs-original.tif', 1_000_000_000)
        if sha256_file(directory / 'usgs-original.tif') != lineage['raster_sha256']:
            raise ValueError('Official raster changed; do not silently update frozen manifest')
        prepare_massachusetts(directory, lineage['crop_bounds'], historical_v1=True)
    _, assets, cases = load_pair(manifest_path, directory)
    result = dict(manifest_sha256=sha256_file(manifest_path), cases=len(cases),
                  assets={k: dict(file=p.name, sha256=sha256_file(p), bytes=p.stat().st_size)
                          for k, p in assets.items()},
                  requests=dict(vector=lineage['vector_native'], raster=lineage['raster']),
                  full_case_geometry_covered=True, license_urls=manifest['license_urls'],
                  limitations=['Unreviewed cartographic labels; no blind acceptance or surveyed thalweg',
                               'Frozen v1 crop omitted the original metre band-unit tag; identity calibration and native samples preserved'])
    (directory / 'harness-verification.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=Path('artifacts/stream-overhaul/public-pilot'))
    parser.add_argument('--pilot', choices=('minnesota', 'massachusetts'), default='minnesota')
    parser.add_argument('--verify-only', action='store_true')
    args = parser.parse_args(argv)
    directory = args.output_dir.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    manifest_path = Path(__file__).resolve().parents[1] / 'evaluation' / (args.pilot + '-pilot-v1.json')
    manifest = json.loads(manifest_path.read_text())
    if args.pilot == 'massachusetts':
        return massachusetts(directory, manifest_path, manifest, args.verify_only)
    requests = {}
    if not args.verify_only:
        for name in ('watercourses.esri.json', 'watercourses-original.esri.json', 'terrain-1m.tif'):
            if (directory / name).exists():
                raise ValueError('Refusing to replace existing public data; use --verify-only or a new directory')
        requests['vector_query'], vector = request_json(VECTOR + '/query', dict(f='json', where='1=1',
            geometry='-91.260,47.424,-91.254,47.429', geometryType='esriGeometryEnvelope', inSR=4326,
            spatialRel='esriSpatialRelIntersects', outFields='*', returnGeometry='true', outSR=26915,
            resultRecordCount=2000), directory / 'watercourses-original.esri.json')
        # Frozen exploratory pilot serialized the parsed response with indent=2.
        # Retain the original response too; never alter geometry or attributes.
        (directory / 'watercourses.esri.json').write_text(json.dumps(vector, indent=2))
        requests['raster_export_request'], export = request_json(RASTER + '/exportImage', dict(f='json',
            bbox='631000,5252000,633000,5254500', bboxSR=26915, imageSR=26915, size='2000,2500',
            format='tiff', pixelType='F32', noData=-9999, interpolation='RSP_NearestNeighbor',
            renderingRule=json.dumps({'rasterFunction': 'None'})), directory / 'raster-export.json')
        requests['raster_download'] = export['href']
        download(export['href'], directory / 'terrain-1m.tif', 100_000_000)
        for name, url in [('vector-service', VECTOR), ('raster-service', RASTER)]:
            request_json(url, {'f': 'pjson'}, directory / (name + '.json'))
    result = verify(directory)
    from tracertool.evaluation import load_pair
    load_pair(manifest_path, directory)  # changed service data cannot replace the frozen pilot
    output = directory / 'harness-verification.json'
    if args.verify_only and output.exists():
        requests = json.loads(output.read_text()).get('requests', {})
    result.update(requests=requests, license_url=LICENSE)
    output.write_text(json.dumps(result, indent=2, allow_nan=False) + '\n')
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
