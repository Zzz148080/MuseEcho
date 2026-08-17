# MuseEcho chord model data card

Status: `G1 NOT READY`. Winterreise is approved and inventoried; RWC-P is approved for the
confirmed non-commercial local/private-cloud training scope and is being acquired. Weight
distribution remains a separate review.

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

## G1 decision

`G1 NOT READY`: the approved corpus contains 24 independent works and 2.214 hours of annotated
audio, far below the planning target of 500 works and 80 hours. Six launch qualities also fail the
20-independent-work minimum. The project may use this corpus for adapter, feature, overfit, and
training-chain smoke tests, but it must not present a model trained only on this corpus as the
competition accuracy candidate. More lawful data or a written vocabulary/scope revision is
required before G1 can pass.

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
