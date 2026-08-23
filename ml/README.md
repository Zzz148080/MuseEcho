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
uv run --project ml pytest -q ml/tests
```

Run the versioned two-track G3 overfit/reproducibility gate from the repository root. The output
directory is ignored by Git; only the path-free public G3 report is committed:

```powershell
uv run --project ml python -m museecho_ml.training.train `
  ml/configs/train-smoke.json `
  --run-dir ml/runs/g3-local
```

Pass `--resume ml/runs/g3-local/checkpoint-last.pt` to restore the exact optimizer, scheduler,
early-stop, RNG, counter, configuration, and data identity. `train-crnn-v1.json` documents the
formal CPU/GPU entry, but the command rejects it while G1 remains `NOT READY`; the G3 report is not
a model-quality score.

Install the `train` or `export` extras only on machines that perform those jobs.

### BTC-170 validation-only research comparison

BTC-170 is an ML-only research candidate. Its official checkpoint must remain at the ignored
local cache path `ml/cache/btc/btc_model_large_voca.pt`; the runner verifies the committed source
descriptor, byte-level artifact lock, safe `weights_only=True` checkpoint contract, and exact
model state before inference. Never commit or redistribute the checkpoint, and never weaken the
loader with `weights_only=False` or `strict=False`.

From the repository root, run only the frozen real-gold validation comparison:

```powershell
uv run --project ml python -m museecho_ml.evaluation.btc run `
  --manifest ml/data/manifests/splits-v1/real-gold-validation.manifest.json `
  --dataset-root guitarset=ml/data/sources `
  --dataset-root rwc-popular=ml/data/sources `
  --dataset-root schubert-winterreise=ml/data/sources/schubert-winterreise-2.1 `
  --evaluation-config ml/configs/evaluation-v1.json `
  --source ml/configs/btc-170-source-v1.json `
  --artifact-lock ml/configs/btc-170-artifact-lock-v1.json `
  --checkpoint ml/cache/btc/btc_model_large_voca.pt `
  --predictions-output ml/runs/btc-170/validation-v1/predictions.jsonl `
  --report-output docs/ml/btc-170/validation-report-v1.json `
  --decision-output docs/ml/btc-170/decision-v1.json `
  --markdown-output docs/ml/btc-170/comparison-v1.md
```

The command rejects every non-validation split before checkpoint or audio access. It does not
authorize access to any frozen test manifest and cannot promote or change the product default.
See the Chinese [BTC-170 model card](../docs/ml/MODEL_CARD_BTC_170.md), the immutable
[validation report](../docs/ml/btc-170/validation-report-v1.json), and the
[continuation decision](../docs/ml/btc-170/decision-v1.json).

After generating the three approved real-gold manifests, freeze the leakage-resistant v1 split
from the repository root. Dataset roots are explicit because legacy manifests intentionally retain
their original relative-path bases:

```powershell
uv run --project ml python -m museecho_ml.data.split_freeze `
  --manifest ml/data/manifests/guitarset-real-gold.manifest.json `
  --manifest ml/data/manifests/winterreise-real-gold.manifest.json `
  --manifest ml/data/manifests/rwc-popular-real-gold.manifest.json `
  --config ml/configs/split-v1.json `
  --dataset-root guitarset=ml/data/sources `
  --dataset-root schubert-winterreise=ml/data/sources/schubert-winterreise-2.1 `
  --dataset-root rwc-popular=ml/data/sources `
  --output-dir ml/data/manifests/splits-v1 `
  --audit-output docs/ml/split-audit-v1.json
```

Frozen artifacts are immutable: an identical rerun is accepted, while changed content at the same
v1 output path is rejected. Training code must use `load_training_manifest()`, which refuses
calibration, validation, and test manifests before returning track paths.

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

For the verified RWC-P re-release plus the pinned official annotation repository, run:

```powershell
uv run --project ml python -m museecho_ml.data.rwc_inventory `
  ml/data/sources `
  --audio-root ml/data/sources/rwc-popular-2026-02-16 `
  --annotations-root ml/data/sources/rwc-annotations `
  --registry docs/ml/dataset-registry.example.json `
  --manifest-output ml/data/manifests/rwc-popular-2026-02-16.json `
  --report-output docs/ml/rwc-popular-inventory-v2026-02-16.json
```
