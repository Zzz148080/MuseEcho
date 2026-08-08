# Synthetic audio test fixtures

`audio_factory.py` generates deterministic, copyright-free inputs: sine waves, a metronome,
major and minor triads, a four-chord progression, segmented energy, silence, very short audio,
and corrupt bytes. Tests generate WAV files on demand. MP3 files are encoded from synthetic WAV
inputs by the test environment's FFmpeg executable; no binary media files are committed.

The same parameters must produce the documented stable WAV hashes. Algorithm tests must state
sample rate, duration, frequencies, and tolerances, and must never present these fixtures as real
music or production analysis results.
