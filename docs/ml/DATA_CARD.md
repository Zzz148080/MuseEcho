# MuseEcho chord model data card

Status: `G1 NOT READY`. Winterreise and RWC-P are approved and inventoried. GuitarSet is approved
as additional real-gold data and is being acquired. IDMT/Jazznet are approved only as separately
reported synthetic supervision; BabySlakh is approved for weak-label pipeline validation. Weight
distribution for the combined final model remains a separate review.

## Purpose

This card records the provenance, license decision, transformation, split, and aggregate
statistics for every dataset considered for the MuseEcho chord model. A dataset can enter a
formal training manifest only after `DatasetRegistry.require_training_approval()` succeeds.

## Non-negotiable boundaries

- Public chord annotations do not imply that the corresponding commercial recordings are
  downloadable or licensed for model training.
- No adapter downloads audio, bypasses authentication, accepts a streaming URL, or copies audio
  into the repository.
- User-uploaded MuseEcho audio is excluded from training.
- Raw audio, local paths, feature caches, checkpoints, and run logs are excluded from Git and
  release artifacts.
- Model-weight distribution is reviewed separately from permission to perform local research
  training.

## Candidate inventory

| Dataset | Intended contribution | Current decision | Blocking evidence |
| --- | --- | --- | --- |
| Isophonics | Pop/rock chord annotations and common evaluation repertoire | `needs-review` | Confirm annotation terms, lawful audio source, training and weight-distribution rights |
| McGill Billboard | Broader popular-music chord annotations | `needs-review` | Confirm current access, annotation terms, lawful audio source and derived-weight rights |
| GuitarSet 1.1.0 | Real acoustic-guitar domain and verified performed chords | `approved` | 360 recordings must remain grouped by 30 lead-sheet identities |
| IDMT-SMT-Chord-Sequences 1.0.0 | Multi-instrument synthetic supervised pretraining | `approved` for synthetic train only | Measure duration; group official triplets and underlying chord sequences; never enter real evaluation |
| Jazznet v1 small/chords | Synthetic piano auxiliary pretraining | `approved` for synthetic train only | Sum real audio headers; group by source progression/template; do not trust advertised aggregate hours |
| BabySlakh | Validate MIDI-to-chord weak-label conversion | `approved` for pipeline validation | Weak labels are not real-gold and do not enter the frozen test set |
| RWC Popular Music | Research recordings with controlled identities | `approved` for non-commercial training | The 2026 Zenodo audio and official curated annotations are CC-BY-NC-4.0; the user confirmed non-commercial competition use and private-cloud training on 2026-08-18; weight distribution remains undecided |
| Schubert Winterreise 2.1 | Classical-domain diversity and aligned annotations | `approved` for local training | Zenodo record 10839767 declares CC-BY-3.0 and includes two performances plus audio chord annotations; model-weight distribution remains a separate review |

The URLs, evidence and unresolved fields are stored in `dataset-registry.example.json`.
`needs-review` entries are leads rather than claims of permission or availability.

### 2026-08-18 evidence snapshot

- Schubert Winterreise Dataset v2.1 is exposed by Zenodo record `10839767` as a 517,380,038-byte
  archive with MD5 `591c377c6d3db522fd159b8b70180978` and license `CC-BY-3.0`. Its record states
  that only two of nine performances are included due to copyright and that the SC06 performance
  must not be redistributed in modified form. Local model training is approved; distributing
  audio-derived features or model weights is not inferred from this decision.
- RWC was re-released online on 2026-02-16 in Zenodo record `18656623` under `CC-BY-NC-4.0`.
  `RWC-P.zip` is 4,071,840,278 bytes with MD5 `960a11a2d7fb603ad0dae8428f53d4f0`.
  The record contains audio only and points to the official `rwc-music/rwc-annotations`
  repository. That repository's LICENSE and README both declare `CC-BY-NC-4.0`, and its inventory
  includes 100 curated RWC-P chord annotation files. The user confirmed that the competition and
  private-cloud training are non-commercial, so RWC-P is approved for that bounded training use.
  Publishing derived weights remains a separate unresolved decision.
- Isophonics exposes individual Beatles and Queen chord annotation files and identifies the
  Beatles transcription collection as version 1.2, but the reviewed pages did not state an
  explicit reuse license and do not provide the commercial recordings. It remains `needs-review`.
- The previously recorded McGill Billboard URL is no longer valid. No substitute mirror will be
  trusted until an official current source and terms are identified.

### 2026-08-18 expansion snapshot

- GuitarSet 1.1.0 is Zenodo record `3371780`, CC-BY-4.0. The selected official files are
  `annotation.zip` (39,132,574 bytes, MD5 `b39b78e63d3446f2e54ddb7a54df9b10`) and
  `audio_mono-mic.zip` (656,927,981 bytes, MD5 `275966d6610ac34999b58426beb119c3`).
  All 360 JAMS files are present. The adapter selects exactly the manually verified performed
  chord annotation, not the instructed lead sheet, and groups players plus comp/solo versions by
  30 lead-sheet identities. Annotation-only preflight reports 4,320 intervals and 10,968.438
  seconds (3.0468 hours), with no gaps or overlaps. `X` accounts for 1,628 intervals (37.6852%)
  and 35.5490% of annotated duration, so GuitarSet is useful domain coverage but not treated as
  three fully clean label-hours. Its `sus2` labels span nine independent lead sheets; after formal
  audio pairing this is expected to lift the combined real-gold `sus2` work count above 20.
- IDMT-SMT-Chord-Sequences 1.0.0 is Zenodo record `7544225`, CC-BY-4.0. Its official archive is
  13,543,282,031 bytes with MD5 `998f79d81d3bbb8d396d495d9c6c0232`. The release describes 15,000
  rendered sequences with WAV, MIDI, JSON and official split CSV. Any hour estimate remains
  provisional until all WAV headers are summed. A read-only preflight over 2,695 complete WAV
  entries in the still-downloading archive found 4.0040--32.0029 seconds per file and projects
  approximately 54.97 hours for all 15,000 files; this projection is evidence for planning only,
  not the final route decision. On 1,008 already complete WAV/JSON pairs, symbolic duration and
  WAV duration differed by at most 4.354 ms, supporting the JSON-derived interval adapter.
- Jazznet v1 is Zenodo record `7192653`, CC-BY-4.0. The bounded acquisition uses
  `progressions-small.tar.gz` (1,898,014,414 bytes, MD5
  `01a550cb55f3f4abb634c0481506f9c6`) and `chords.tar.gz` (388,949,707 bytes, MD5
  `8039eb8440e4a2a9e18cb72e5f09436d`) plus the verified metadata and MIDI archives. Its advertised
  aggregate duration is not accepted as evidence; actual audio headers and grouping metadata must
  be audited. All 5,876 small-subset progression names matched an aligned MIDI file. MIDI-header
  preflight totals 45,662 seconds (12.6839 hours) and 22,831 chord intervals; 992 intervals
  (4.3450%) map to `X`. The remaining supported intervals strongly emphasize `7`, `maj7`, `min7`
  and `hdim7`, complementing IDMT's major/minor sequences. Grouping by progression mode plus
  voicing/template index yields 1,674 groups; the published row-level split will not be reused
  because it can place transposed/octave variants of one template in different splits.
- BabySlakh is Zenodo record `4603870`, CC-BY-4.0. The 16 kHz archive is 882,818,115 bytes with
  MD5 `311096dc2bde7d61c97e930edbfc7f78`. Its 20 aligned multitracks are reserved for weak-label
  conversion validation.
- WaivOps Lo-Fi Chords failed label inspection. All 8,000 JSON files contain only instrument,
  tempo and time signature, with no chord symbols or temporal boundaries. Its advertised 54 hours
  are excluded and the 28.2 GB audio is not being acquired.

The acquisition gate defaults to plan A. If IDMT plus Jazznet contain at least 60.0 hours of
verified, grouped and usable synthetic supervision, plan B is used: synthetic pretraining,
real-gold fine-tuning, real-only calibration/selection, and one frozen real test. This decision
does not count synthetic hours toward G1.

## Approved-data inventory

The official Schubert Winterreise 2.1 archive was downloaded locally, verified against the
published MD5, and processed read-only. The archive and extracted audio remain under ignored
`ml/data/`; they are not Git or release artifacts.

- Archive size: `517380038` bytes.
- Expected and observed MD5: `591c377c6d3db522fd159b8b70180978`.
- Packaged usable recordings: 48 (24 works, HU33 and SC06 performances).
- Artist/performance identities: 2; cover groups: 24.
- Total audio: 8123.506939 seconds (2.2565 hours).
- Source-annotated duration after six recorded tail clips within the strict 50 ms tolerance:
  7970.476735 seconds
  (2.2140 hours).
- Unannotated leading/trailing duration: 153.030204 seconds. It has not been silently relabeled
  as `N`; the frame-label policy must decide this before feature extraction.
- Intervals: 4328 total; 500 mapped to `X` (11.5527% of intervals and 11.6317% of
  annotated duration); 0 explicit `N`; 0 malformed, overlapping, or discarded.
- Formal local manifest SHA-256:
  `0bf74b8b4ea25e1322fa75db106747dccff942580119b7a4b3f0db2f11a4af17`.
- Reproducible aggregate report:
  `docs/ml/winterreise-inventory-v2.1.json`.

| Quality | Works | Intervals | Duration (seconds) | Launch coverage result |
| --- | ---: | ---: | ---: | --- |
| `maj` | 24 | 1520 | 2796.946531 | passes the 20-work per-quality minimum |
| `min` | 24 | 1228 | 2561.590204 | passes |
| `7` | 24 | 888 | 1384.06 | passes |
| `maj7` | 1 | 4 | 2.98 | fails |
| `min7` | 9 | 44 | 50.6 | fails |
| `dim` | 6 | 28 | 24.64 | fails |
| `hdim7` | 14 | 114 | 218.7 | fails |
| `sus2` | 0 | 0 | 0 | fails |
| `sus4` | 1 | 2 | 3.86 | fails |
| `N` | 0 | 0 | 0 | no explicit source intervals |
| `X` | 23 | 500 | 927.1 | retained internally, not a published known chord |

Near-duplicate audio and cross-dataset collision counts remain pending Task 4 fingerprinting. The
two performances of each song already share one explicit work/cover group and therefore cannot be
split across train and evaluation sets.

### RWC-P 2026 re-release

The official RWC-P archive and curated annotation repository were acquired after the user
confirmed non-commercial competition use and private-cloud training. Both sources remain under
ignored `ml/data/` paths.

- Archive size: `4071840278` bytes.
- Expected and observed MD5: `960a11a2d7fb603ad0dae8428f53d4f0`.
- Annotation repository commit:
  `0a1a6c31dbe73a7f5d44f7caef8cd0999402a4c2`.
- Recordings/works: 100; artists: 34; cover groups: 100.
- Total audio and normalized annotated duration: 24216.414898 seconds (6.7268 hours).
- Intervals: 13467 total; 1111 mapped to `X`; 263 explicit `N`; 0 malformed,
  overlapping, or discarded.
- All 100 final source intervals extended beyond the released WAV. Seven were within 50 ms; the
  remainder formed a systematic approximately 1.03–2.23 second annotation-grid tail. The RWC-only
  adapter clips only the final interval, caps the permitted overrun at 2.25 seconds, records every
  clip, and rejects larger or interior overruns. The observed maximum was 2.230438 seconds.
- Formal local manifest SHA-256:
  `65c808e8f2e9d88304b8b7e8fcfac7214917558e20410c4faf722bd92776296d`.
- Reproducible aggregate report:
  `docs/ml/rwc-popular-inventory-v2026-02-16.json`.

### Combined approved corpus

| Quality | Independent works | Intervals | Duration (seconds) | 20-work result |
| --- | ---: | ---: | ---: | --- |
| `maj` | 121 | 7571 | 13603.50 | passes |
| `min` | 121 | 3108 | 6080.40 | passes |
| `7` | 104 | 1753 | 3059.28 | passes |
| `maj7` | 75 | 829 | 1790.79 | passes |
| `min7` | 101 | 2035 | 3394.71 | passes |
| `dim` | 43 | 172 | 222.43 | passes |
| `hdim7` | 28 | 162 | 313.39 | passes |
| `sus2` | 15 | 90 | 135.42 | **fails** |
| `sus4` | 49 | 201 | 348.76 | passes |
| `N` | 100 | 263 | 424.21 | internal state |
| `X` | 108 | 1611 | 2813.99 | internal state |

Combined totals are 148 recordings, 124 independent works, 32339.921837 seconds of audio, and
32186.891633 seconds (8.9408 hours) of annotated audio. The corpus contains 17795 intervals; 1611
(9.0531%) map to `X`. There are 106 explicitly recorded final-interval clips and 153.030204
unannotated seconds, all from Winterreise leading/trailing gaps.

## G1 decision

`G1 NOT READY`: the approved corpus contains 124 independent works and 8.9408 hours of annotated
audio, far below the planning target of 500 works and 80 hours. `sus2` also remains below the
20-independent-work minimum. The project may use this corpus for adapter, feature, overfit, and
training-chain smoke tests, but it must not present a model trained only on this corpus as the
final competition accuracy candidate. More lawful data or a written data/vocabulary/scope
revision is required before G1 can pass.

## Approval procedure

For each dataset:

1. Open the official source and archive the exact terms or license URL.
2. Record the version and download date.
3. Decide separately whether annotations and audio may be used for training.
4. Decide whether a model trained on the data may be redistributed.
5. Record the required citation and review date.
6. Set the registry status to `approved` only when `training_allowed` is true and review evidence
   is non-empty.
7. Keep a private local path mapping outside Git; run the read-only adapter to produce hashes and
   normalized interval statistics.

## Required aggregate report

Before G1 can pass, this document still needs:

- near-duplicate and cross-dataset collision counts;
- the final multi-dataset manifest hash and split-policy hash.

The planning target is at least 500 independent works and 80 hours of usable annotations, with
every published non-`N/X` quality represented by at least 20 independent works. If lawful data
cannot meet that target, the vocabulary or training strategy must be revised in writing rather
than padded with duplicated or synthetic examples.
