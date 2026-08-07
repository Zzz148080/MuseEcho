# MuseEcho V1 Design

Date: 2026-08-08

Status: Approved conversational design; awaiting written-spec review

Canonical product specification: `SPEC.md`

## Purpose

MuseEcho turns a legally uploaded WAV or MP3 into time-aligned musical evidence that ordinary listeners can explore and understand. It uses deterministic DSP/MIR analysis and a deterministic music-theory engine to establish facts. An optional LLM explains those facts in accessible language but cannot create or change them.

## Approved Product Boundary

V1 supports files up to 30 MB and 10 minutes. It provides:

1. asynchronous upload and real analysis;
2. Music DNA derived from the current analysis;
3. a synchronized waveform, section, chord and energy timeline;
4. deterministic chord deconstruction;
5. evidence-grounded segment Q&A with a no-key fallback;
6. encrypted playback, explicit deletion and 24-hour expiry.

V1 excludes accounts, a persistent music library, recommendations, social features, source separation, instrument recognition, HarmonyOS, agent behavior and horizontal scaling.

## Architecture

The selected approach is a modular monolith:

```text
React/Vite/TypeScript browser
          │
          ▼
Caddy HTTPS reverse proxy
          │
          ▼
FastAPI application and static frontend
├── access/upload/security services
├── bounded process pool (one analysis at a time)
├── deterministic DSP/MIR pipeline
├── deterministic music-theory engine
├── optional LLM adapter and deterministic fallback
├── SQLite repositories
└── expiry/orphan cleanup scheduler
          │
          ▼
Persistent SQLite + encrypted audio chunks
```

The production target is a Tencent Cloud Lighthouse instance in Hong Kong with 2 vCPU, 4 GB RAM and persistent system storage. Docker and volume contracts remain platform-neutral.

## Evidence Pipeline

1. Validate the file signature, byte limit and real decoder output.
2. Encrypt the accepted audio with a per-analysis data key.
3. Decode a controlled PCM stream for analysis.
4. Compute waveform buckets, beat/tempo, RMS energy and chroma.
5. Estimate key/mode, structural boundaries and chord events.
6. Attach confidence, algorithm provenance and time bounds to every fact.
7. Convert low-confidence facts to `unknown` and exclude them from LLM input.
8. Derive chord notes, intervals, quality, scale degree and possible function in the theory engine.
9. Build a whitelisted evidence packet for LLM explanation or deterministic fallback.

The LLM never generates chord labels, key, structure, timestamps, instruments, modulation or energy changes. Specialized MIR models may generate facts only when their output is structured, traceable and confidence-scored.

## Interaction Design

The approved direction is “Warm Resonance” in a guided single canvas. The user moves from upload and analysis status to player and Music DNA, synchronized structure map, chord details and segment Q&A. Desktop layouts place related views side by side; mobile layouts stack them while keeping playback reachable.

The player, cursor, waveform, sections, chords and energy curve share one time coordinate. Clicking a chord seeks to its start and opens theory details. Dragging a segment constrains the evidence available to Q&A.

## Data and Privacy

An analysis has an unguessable ID and a separate access token whose hash is stored in SQLite. The browser receives the token only through a Secure, HttpOnly, SameSite=Strict cookie.

Audio is retained for at most 24 hours because the user explicitly chose refresh-safe playback over immediate server deletion. Each file uses chunked AEAD with a unique data key; a deployment key wraps the data key. Explicit deletion or expiry destroys the key, ciphertext, results, explanations and access grant. The persistent volume never contains plaintext source audio.

## Failure Behavior

Unsupported, oversized, over-duration and corrupt files fail with stable user-facing errors and immediate cleanup. Silence and insufficient evidence return partial/unknown analysis rather than fabricated results. Worker failure produces a failed or retryable job. Missing credentials, provider timeout and invalid LLM output use deterministic fallback. Expired or unauthorized access does not reveal whether another user's record exists.

## Security Design

- Validate signatures and decoder output; never trust extension, MIME or filename.
- Use random internal names and bounded streaming I/O.
- Rate-limit uploads and Q&A; cap queue length, decoder time and worker resources.
- Keep all long-lived credentials server-side.
- Manage credentials with a local CLI; use the OS credential store locally and repository-external read-only secret files in Docker.
- Redact keys, cookies, original filenames, audio and question bodies from logs.
- Use HTTPS, restricted same-origin CORS, CSP, security headers, Origin checks and CSRF defense.
- Run dependency and secret scans in CI.

## Test and Delivery Design

TDD is mandatory. Synthetic fixtures cover tones, major/minor chords, metronomes, simple progressions, silence, short and corrupt audio. Backend unit tests cover theory, confidence, state, access, encryption, cleanup and fallback. Frontend tests cover the workspace and error states. Playwright exercises the full upload-to-delete flow at desktop, tablet and mobile widths.

GitHub Actions and GitLab CI run tests, lint, typecheck, production build and Docker validation; GitLab includes a `unit-test` job. A multi-stage Docker image and Docker Compose provide local distribution. Production uses Caddy and Tencent Cloud Lighthouse, followed by a real public smoke test.

## Objective Completion Gate

Completion requires current evidence for every acceptance criterion in `SPEC.md`, all test/build/Docker/E2E commands, public deployment smoke testing, security scanning and three final audits. Human review, deployment authorization and the student's reflection remain human-owned.

## Approval Record

The user approved the architecture/data flow, function boundaries, data/API design, UI/UX, security/privacy and revised testing/deployment design in the 2026-08-08 brainstorming conversation. The written files themselves still require the separate Superpowers written-spec review gate.
