from __future__ import annotations

import pytest

from museecho_ml.data.course import (
    CorpusRole,
    decide_training_route,
    select_manifest_role,
)


def _inventory(
    dataset_id: str,
    *,
    role: str,
    hours: float,
    grouping_passed: bool = True,
    label_passed: bool = True,
) -> dict[str, object]:
    return {
        "dataset_id": dataset_id,
        "corpus_role": role,
        "total_annotated_seconds": hours * 3600,
        "grouping_audit_passed": grouping_passed,
        "label_audit_passed": label_passed,
    }


def test_route_b_requires_sixty_audited_synthetic_hours() -> None:
    decision = decide_training_route(
        [
            _inventory("idmt", role="synthetic-supervised", hours=58.0),
            _inventory("jazznet", role="synthetic-supervised", hours=2.0),
            _inventory("gold", role="real-gold", hours=80.0),
        ]
    )

    assert decision.route == "B"
    assert decision.usable_synthetic_seconds == 60 * 3600
    assert decision.included_datasets == ("idmt", "jazznet")


def test_route_a_excludes_failed_grouping_or_label_audit() -> None:
    decision = decide_training_route(
        [
            _inventory("idmt", role="synthetic-supervised", hours=59.0),
            _inventory(
                "jazznet",
                role="synthetic-supervised",
                hours=20.0,
                grouping_passed=False,
            ),
        ]
    )

    assert decision.route == "A"
    assert decision.usable_synthetic_seconds == 59 * 3600
    assert decision.excluded_datasets == ("jazznet",)


def test_real_evaluation_selection_cannot_include_synthetic_tracks() -> None:
    manifest = {
        "schema_version": 1,
        "tracks": [
            {"track_id": "real", "corpus_role": "real-gold"},
            {"track_id": "synthetic", "corpus_role": "synthetic-supervised"},
        ],
    }

    selected = select_manifest_role(manifest, role=CorpusRole.REAL_GOLD)

    assert selected["corpus_role"] == "real-gold"
    assert [track["track_id"] for track in selected["tracks"]] == ["real"]


def test_route_rejects_implicit_or_unknown_corpus_role() -> None:
    with pytest.raises(ValueError, match="corpus_role"):
        decide_training_route(
            [{"dataset_id": "unknown", "total_annotated_seconds": 100.0}]
        )
