# MuseEcho ML

This project owns the offline data preparation, training, evaluation, calibration, and model
export pipeline for MuseEcho chord recognition. It is deliberately isolated from the product
runtime in `src/museecho`.

## Boundary

- Training code may use PyTorch and local licensed datasets.
- Product code must not import `museecho_ml` or PyTorch.
- Raw audio, feature caches, checkpoints, run logs, and ONNX files are ignored by Git.
- A release model is identified by a validated manifest and SHA-256 checksums.
- Dataset acquisition must follow `docs/ml/DATA_CARD.md`; no downloader may bypass access or
  license requirements.

## Commands

```powershell
uv lock --project ml
uv sync --project ml --extra dev
uv run --project ml pytest -q
```

Install the `train` or `export` extras only on machines that perform those jobs.

After placing the verified Winterreise 2.1 archive contents in the ignored local data directory,
generate its licensed manifest and reproducible public inventory from the repository root:

```powershell
uv run --project ml python -m museecho_ml.data.winterreise_inventory `
  ml/data/sources/schubert-winterreise-2.1 `
  --registry docs/ml/dataset-registry.example.json `
  --manifest-output ml/data/manifests/schubert-winterreise-2.1.json `
  --report-output docs/ml/winterreise-inventory-v2.1.json
```

The full manifest remains ignored because it contains local dataset paths. The public report
contains aggregate statistics, per-track content hashes, and the canonical manifest hash without
including audio.
