# Ayalon monitor — incident 2026-09-15 and methodology v2

## 1. Incident: TomTom stopped returning data (2026-09-15)

| Fact | Evidence |
|---|---|
| Last successful TomTom response: **2026-09-15 09:42:42 UTC** | production cache `sources/_cache/tt_v4_abs10_flow_*.json` (HTTP `Date` header, tracking-ids `d96995f4…`, `a714db25…`, `1f756059…`) |
| From then on every request: HTTP 400 `INVALID_REQUEST: Point too far from nearest existing segment.` | diagnostics 2026-09-24 from the production server |
| The error is **country-wide, not Ayalon-specific** | 400 for Ayalon (incl. a point lying on the Ayalon North centre line), Route 6 control point `32.261384,34.991083` (OSM way 880991069), Route 2 near Netanya |
| The key and endpoint work | same key, same endpoint, TomTom documentation example point in Amsterdam `52.41072,4.84239` → HTTP 200 |
| TomTom Orbis traffic flow has no Israeli data either | Orbis Vector Flow Tiles (`apiVersion=2`) over Tel Aviv at z10/z12/z14: HTTP 200 with an empty layer named `empty` (11 bytes); Amsterdam tile: 2383 bytes |
| TomTom Routing has no live traffic in Israel | Ayalon route: `liveTrafficIncidentsTravelTimeInSeconds` = `historicTrafficTravelTimeInSeconds` = 645 s; Amsterdam: 820 vs 837 s |
| **Israel was removed from TomTom's Traffic API market coverage** | [Traffic API market coverage](https://docs.tomtom.com/traffic-api/documentation/tomtom-maps/v1/product-information/market-coverage), page "Last edit 2026.09.15": no Israel entry. Wayback Machine snapshots 2026-05-14 and 2026-06-06: `Israel IL/ISR ✔ ✔` (Traffic Incidents, Traffic Flow) |

**Root cause:** TomTom withdrew traffic coverage for Israel on 2026-09-15. It was not a
request-format, key, quota or local-geometry problem. TomTom did not publish a
reason. The project cannot fix this on its side.

**Replacement:** HERE Traffic API v7 lists Israel with Flow and Incidents coverage
([HERE traffic coverage](https://docs.here.com/traffic-api/docs/traffic-here-traffic-api-v7-coverage-information)).
The v2 collector supports HERE; it needs a HERE API key (owner's account).

### Collector behaviour during the incident (v1 code)
* `collector.py::_fetch_traffic` fell back to a cached aggregate up to 24 h old and
  wrote it as a new run: **281 runs** re-recorded the 09:42:42 response until
  2026-09-16 09:39:39 UTC. After that the cache expired and every cycle failed.
* The same mechanism had already produced cache re-use during earlier outages
  (2026-05-08/09, 2026-05-25/26, 2026-06-20). Near-TTL cache hits during normal
  operation added more. In total **4,283 of 47,776 v1 runs (8.96 %)** re-use an
  earlier TomTom response.

## 2. Defects of methodology v1 (`methodology.py`, "1.0-freeze")

1. **Length/time mismatch.** It compared `currentTravelTime` of the whole TomTom
   segment (9–18 km) with the free-flow time of a 17-vertex window (0.4–1.1 km).
   On the free-flow response of 2026-01-10 (`currentSpeed == freeFlowSpeed`) v1
   reports **858 vehicle-hours**. Every stored run lies at 434–884 h, so the
   series measures the artefact, not congestion.
2. **Vehicle counts not measured:** vehicles = speed × 25 veh/km.
3. **Wrong places.**
   * Probe `la_guardia` (32.038, 34.782) sits 120 m from Route 44 and 2.8 km from
     Ayalon. TomTom returned an 18 km FRC2 segment of Route 44.
   * Probe `ha_shalom` is 93 m off Ayalon North, next to ramps.
   * `ha_shalom` and `arlozorov` received the identical TomTom polyline, so they
     are one measurement counted twice.
   * The southbound carriageway was never measured.
4. **Snapshot summation.** The UI summed 5-minute snapshots of a rate, so totals
   scaled with the number of API calls. "All time" meant only the last 5,000 rows.
5. **Cache re-use** was recorded as observations (see §1).

The raw per-segment inputs of v1 were not stored, so v1 values **cannot be
recomputed**. They are kept unchanged and flagged
(`runs.quality_flags`, `data_quality_periods`), and are shown only in the archive.

## 3. Methodology v2

**Sections** (`reference/ayalon_segments_v2.json`, built reproducibly by
`tools/build_segments_v2.py` from the committed OSM snapshot):

| segment_id | direction | from → to | length |
|---|---|---|---|
| ayalon_n_holon_laguardia | northbound | Holon (11) → La Guardia (13) | 2604 m |
| ayalon_n_laguardia_arlozorov | northbound | La Guardia → Arlozorov | 2002 m |
| ayalon_n_arlozorov_rokach | northbound | Arlozorov → Rokach (17) | 1799 m |
| ayalon_s_rokach_arlozorov | southbound | Rokach → Arlozorov | 1776 m |
| ayalon_s_arlozorov_laguardia | southbound | Arlozorov → La Guardia | 2009 m |
| ayalon_s_laguardia_holon | southbound | La Guardia → Holon | 2614 m |

Boundaries are OSM `motorway_junction` nodes projected onto each carriageway.
Sections are contiguous and do not overlap, so per-direction sums are physical.

**Real-time only.** HERE `confidence > 0.7` means real-time speeds (0.5–0.7 is a
historical profile, ≤ 0.5 the speed limit; HERE docs "Flow"). Anything else is
dropped, never substituted.

**Geographic matching** (`sources/segment_matcher.py`). Each section is split
into 10 m bins. A bin takes the speed of a provider piece only if that piece
passes within 20 m and runs in the same direction (±35°). Opposite carriageway,
parallel roads and crossing ramps are rejected. Tested on the real 2026-09-15
responses: the Route 44 answer matches nothing, and the Ayalon North answer
matches the two northbound sections it covers with a mean offset of 2–5 m.

**Formulas** (per section *s*, measurement time *t*):

* `T_obs = Σ_bins len/v`, `T_ff = Σ_bins len/v_ff` over the **same** covered
  bins. These are extrapolated to the full section only if coverage ≥ 80 %;
  otherwise status is `insufficient_coverage` and no value is produced.
* `d = max(0, T_obs − T_ff)` [s/veh]. At free flow `d = 0` (test-enforced).
* Corridor per direction = sum over its 3 sections, only when all 3 were measured
  in the same provider snapshot.
* Time aggregation uses a step-hold integral. Each observation is valid until the
  next one, at most 10 min. Gaps are reported as missing coverage and never
  interpolated. Results do not depend on the polling rate (test-enforced).

**Economic indicators** (vehicle-hours, fuel, CO₂, ₪) need traffic volumes
q [veh/h]. No connected source measures them. They are computed only when a
documented `reference/volume_profile.json` exists (source + citation + hourly
profile):

* `VH = Σ_s ∫ d/3600 · q dt`
* `fuel = VH · 0.8 L/h · 1.5`
* `CO₂ = fuel · 2.31`
* `₪ = fuel · P_fuel`

Otherwise the UI says they are unavailable. The official Ayalon traffic counts on
data.gov.il (`ayalontrafficcounts`, 2019/2021, 15-min, per direction) are the
candidate source. Their files currently redirect to a Google sign-in and could
not be retrieved automatically.

## 4. Data model (schema version 2)

* `runs` — v1, unchanged values. It gained `methodology_version`,
  `quality_flags` (`v1_method_defect`, `cache_reuse`, `stale_source`) and
  `quality_note`.
* `collection_cycles` — one row per collector run. Status `ok` means all
  sections were measured, `partial` some, `failed` none. It also stores the
  provider status, error and diagnostics.
* `segment_observations` — one row per section and provider snapshot.
  * Key: `UNIQUE(segment_id, segment_version, provider, provider_snapshot)`, so
    the same provider data can never be stored twice.
  * Separate columns: `observed_at_utc` (time the data refers to),
    `source_updated_utc` (provider timestamp), `fetched_at_utc`,
    `processed_at_utc`, `recorded_at_utc`.
* `raw_responses` — gzip of provider bodies (retained 30 days) for audit and
  recomputation.
* `data_quality_periods` — known defect periods shown in the UI.

The migration takes a verified SQLite backup first
(`data/backups/monitor.pre_v2.<stamp>.sqlite3`) and is idempotent.
