# MuseEcho chord model data card

Status: one small public dataset is approved for local formal training; the pop-music candidates
remain blocked by license or competition-scope review.

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
| RWC Popular Music | Research recordings with controlled identities | `needs-review` | The 2026 Zenodo re-release is CC-BY-NC-4.0; confirm that the competition, cloud processing and intended model distribution remain non-commercial, then audit the separate annotations repository |
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
  The record contains audio only and points to a separate annotations repository. It remains
  `needs-review` until the competition's non-commercial status and annotation terms are fixed.
- Isophonics exposes individual Beatles and Queen chord annotation files and identifies the
  Beatles transcription collection as version 1.2, but the reviewed pages did not state an
  explicit reuse license and do not provide the commercial recordings. It remains `needs-review`.
- The previously recorded McGill Billboard URL is no longer valid. No substitute mirror will be
  trusted until an official current source and terms are identified.

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

Before G1 can pass, this document must be updated with:

- approved work, track, artist, and cover-group counts;
- total annotated duration and duration by dataset;
- duration and independent-work count for every launch quality;
- `N`, `X`, malformed, clipped, overlapping, and discarded interval counts;
- near-duplicate and cross-dataset collision counts;
- the final manifest hash and split-policy hash.

The planning target is at least 500 independent works and 80 hours of usable annotations, with
every published non-`N/X` quality represented by at least 20 independent works. If lawful data
cannot meet that target, the vocabulary or training strategy must be revised in writing rather
than padded with duplicated or synthetic examples.
