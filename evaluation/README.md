# Frozen paired-data evaluation

## Bounded cycle-1 revision

The original result below is preserved. The later core revision resolved
outlet-connected flats, treated only tiny complete depressions on a separate
analysis surface and enlarged the native domain cap from 500,000 to 2,000,000
cells. **It still returned zero complete geometries out of 21 attempts.** The
four original memory refusals now reached analysis but refused retained basins.
All failures remain in the denominator; paired geometric gain is undefined.
The numeric, source-hash-bound report is `results/cycle1-summary.json`.
That historical report names its exact module hashes, including the then-current
evaluation harness. The subsequent final replay after harness safety fixes and
full-domain termination repair is `results/release-candidate-summary.json`; it
again records zero Auto geometries out of 21. Initial and cycle-1 records are not
silently relabeled as the final source snapshot.
Peak CLI child RSS was about 433 MiB; individual attempts took 0.18–30.32 s.
These results fail usefulness, default promotion and subsecond performance
targets; they must not be advertised as a successful stream-path overhaul.

## Measured outcome

The actual replayed public pilots do **not** support Auto promotion or a claim of
real-channel improvement. Both use exactly two declared reference endpoints,
without interior reference geometry entering either solver. No per-reach tuning.

| Pilot | Reaches | Legacy candidates | Legacy median reach p95 discrepancy | Auto geometry returned | Auto exception reasons |
|---|---:|---:|---:|---:|---|
| Minnesota | 3 | 3 | 22.1045 m | 0 | 2 native-sink rejections; 1 memory-budget rejection |
| Massachusetts | 18 | 18 | 18.6278 m | 0 | 15 native-sink rejections; 3 memory-budget rejections |

Legacy maximum reach p95 discrepancy was 319.0705 m (MN) and 140.9021 m
(MA). Returning a candidate is not an accuracy/branch-correctness certificate.
Auto's conservative rejection is not scored as zero error: all 21 attempts stay
in the denominator; there are zero paired geometric comparisons and gain is
undefined. These exceptions count as `failure`; only structured `unresolved`
results count as `abstention`. Error strings never determine outcome status.

The default CLI threshold requires full candidate coverage, with **no accuracy
limit unless `--max-p95` is supplied**. Thus legacy exited 0 and Auto exited 2;
legacy's threshold success does not mean promotion or adequate accuracy.

The machine-readable public result is `results/public-pilot-summary.json`.
It includes per-reach distances, counts, times, paired comparisons, module/data/
manifest hashes and dependency versions. Full local reports (including geometry
and source paths) are intentionally ignored under
`artifacts/stream-overhaul/final-evaluation/`. The public summary excludes those
fields. Source hashes were checked against the actual modules after execution.

## Reproduce

From the repository with application dependencies installed and `PYTHONPATH=src`:

```sh
python scripts/fetch_stream_pilot.py --pilot minnesota --output-dir artifacts/stream-overhaul/mn-replay
python scripts/fetch_stream_pilot.py --pilot massachusetts --output-dir artifacts/stream-overhaul/ma-replay
python scripts/fetch_stream_pilot.py --pilot massachusetts --output-dir artifacts/stream-overhaul/ma-replay --verify-only

python scripts/evaluate_streams.py --manifest evaluation/minnesota-pilot-v1.json --data-dir artifacts/stream-overhaul/mn-replay --method legacy --output artifacts/stream-overhaul/mn-legacy.json
python scripts/evaluate_streams.py --manifest evaluation/minnesota-pilot-v1.json --data-dir artifacts/stream-overhaul/mn-replay --method auto --output artifacts/stream-overhaul/mn-auto.json
python scripts/evaluate_streams.py --manifest evaluation/massachusetts-pilot-v1.json --data-dir artifacts/stream-overhaul/ma-replay --method legacy --output artifacts/stream-overhaul/ma-legacy.json
python scripts/evaluate_streams.py --manifest evaluation/massachusetts-pilot-v1.json --data-dir artifacts/stream-overhaul/ma-replay --method auto --output artifacts/stream-overhaul/ma-auto.json
```

Defaults used in the recorded run: scoring spacing 1 projected metre; maximum
working dimension 2500. Auto analysis remains source-native. Use
`tracertool.evaluation.compare_reports` for paired JSON reports; it rejects
mismatched reach IDs, manifest identity, working-grid limit or scoring spacing.
Exit 1 is an input/engine import error; exit 2 is a completed failed threshold.
Individual reach failures do not terminate other attempts.

Both network replays were exercised and reproduced the frozen raster and vector
SHA256 values exactly. The MN raw response is retained separately and serialized
with the original indent=2 convention. MA retains the original USGS tile and
reference response, creates the fixed native raster window, and adds only a
lowercase objectid alias to the ESRI attributes. No reference burning occurs.

Downloads require HTTPS allowlisted hosts, validate redirects, have 90-second
socket timeouts and per-response byte caps, and refuse existing data. MN is
bounded to at most 180 MB; MA to 1.02 GB per fetch, comfortably below the 10 GiB
execution budget. There is no unbounded retry loop or archive extraction.
Pre-existing partial files are preserved. Changed services fail frozen hash
checks rather than silently replacing evaluation data.

## Metrics and limitations

- Sample each source polyline at equal arc-length interval midpoints. Each sample
  is measured against **continuous target segments**, never nearest vertices.
- Score both directions. Report directed mean, median, p95 and maximum;
  symmetric p95 is the larger directed p95. Reach distributions weight reaches
  equally rather than long/densely digitized lines dominating the result.
- Each directed quantile/mean/maximum has a quantitative error bound of half its
  actual sample interval (at most 0.5 m here). Thresholds use the p95 **upper
  bound**, not optimistic sampled p95. Report a Hausdorff upper bound too.
- p95 can still miss discrepancies on less than 5% of a reach. Branch/outlet
  correctness and operator time/clicks are explicitly unreviewed, not invented.
- Minnesota is permanently **development**: cross-vintage terrain-derived labels
  already exposed during exploration. Massachusetts is the pre-existing
  **exposed validation** allocation with unreviewed mixed-lineage cartographic
  labels, not surveyed bed thalwegs and not blind acceptance. Neither pilot may
  be relabeled as independent acceptance after observing these outputs.
- MA's frozen exploratory crop omitted the source's metre band-unit tag. Replay
  explicitly reproduces that historical omission to preserve frozen bytes;
  source samples and identity scale/offset are unchanged. Generic new crops
  preserve band units and calibration. Do not infer a vertical datum.
- Provenance/license source URLs are recorded in the manifests. No raw geodata
  is distributed. License pointers do not substitute for independent label
  review or a blanket redistribution clearance.
- No acquisition-matched Sonoma evaluation was completed. Existing partial
  acquisition artifacts remain untouched; they are not counted as evidence.

Final focused evaluation/core/grid/persistence verification: **267 passed**.
The two original persistence review findings were independently reproduced,
fixed by the persistence lane, and rechecked successfully; see
`PERSISTENCE_REVIEW.md`. No commits or remote writes were made by this lane.
