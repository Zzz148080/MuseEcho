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
