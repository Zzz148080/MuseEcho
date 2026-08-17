# Chord model artifacts

Each release candidate receives an immutable version directory containing a validated
`manifest.json` and an ONNX model distributed through the release process. ONNX files are not
tracked directly in Git.

The manifest must validate against `manifest.schema.json` and bind the model, feature
configuration, vocabulary, and calibration configuration by SHA-256. A runtime must reject a
missing, altered, unsupported, or incomplete artifact and use the explicitly reported legacy
fallback instead.
