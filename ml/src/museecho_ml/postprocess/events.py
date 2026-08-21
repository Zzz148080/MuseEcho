from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from museecho_ml.evaluation.metrics import ScoredChordInterval


def serialize_events(events: Sequence[ScoredChordInterval]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "event_version": "chord-events-v1",
        "events": [
            {
                "start_seconds": event.start_seconds,
                "end_seconds": event.end_seconds,
                "root": event.chord.root,
                "quality": event.chord.quality,
                "bass": event.chord.bass,
                "symbol": event.chord.display_symbol,
                "confidence": event.confidence,
            }
            for event in events
        ],
    }
