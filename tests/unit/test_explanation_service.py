import uuid

import pytest

from museecho.application.explanations import ExplanationService
from museecho.domain.models import Evidence, ExplanationDraft


def _evidence() -> tuple[Evidence, ...]:
    analysis_id = uuid.uuid4()
    return (
        Evidence(
            id=uuid.uuid4(),
            analysis_id=analysis_id,
            kind="chord",
            start_seconds=1.0,
            end_seconds=3.0,
            value_json={"symbol": "G"},
            confidence=0.9,
            algorithm="chroma-v1",
            eligible_for_llm=True,
        ),
    )


def test_missing_key_uses_deterministic_fallback():
    evidence = _evidence()

    answer = ExplanationService(provider=None).explain("为什么有张力？", evidence)

    assert answer.mode == "fallback"
    assert answer.evidence_ids == tuple(item.id for item in evidence)
    assert "和弦" in answer.text
    assert "置信度 0.90" in answer.text
    assert "chroma-v1" in answer.text
    assert "不表示唯一因果关系" in answer.text


class StubProvider:
    def __init__(self, draft=None, error: Exception | None = None) -> None:
        self.draft = draft
        self.error = error
        self.calls: list[tuple[str, tuple[Evidence, ...]]] = []

    def explain(self, question: str, evidence: tuple[Evidence, ...]) -> ExplanationDraft:
        self.calls.append((question, evidence))
        if self.error is not None:
            raise self.error
        assert self.draft is not None
        return self.draft


def test_provider_observes_only_revalidated_whitelisted_evidence():
    valid = _evidence()[0]
    low = Evidence(
        uuid.uuid4(),
        valid.analysis_id,
        "chord",
        1.0,
        3.0,
        {"symbol": "C"},
        0.2,
        "legacy",
        True,
    )
    forbidden = Evidence(
        uuid.uuid4(),
        valid.analysis_id,
        "instrument",
        1.0,
        3.0,
        {"name": "piano"},
        0.99,
        "legacy",
        True,
    )
    provider = StubProvider(ExplanationDraft("llm", "基于和弦证据的解释。", (valid.id,)))

    answer = ExplanationService(provider).explain(
        "为什么有张力？",
        (forbidden, low, valid),
    )

    assert answer.mode == "llm"
    assert provider.calls == [("为什么有张力？", (valid,))]
    assert answer.evidence_ids == (valid.id,)


@pytest.mark.parametrize("error", [TimeoutError(), RuntimeError("provider failed")])
def test_provider_failure_uses_fallback_with_actual_evidence(error):
    evidence = _evidence()
    provider = StubProvider(error=error)

    answer = ExplanationService(provider).explain("为什么？", evidence)

    assert answer.mode == "fallback"
    assert answer.evidence_ids == tuple(item.id for item in evidence)


def test_unknown_provider_evidence_id_forces_fallback():
    evidence = _evidence()
    provider = StubProvider(ExplanationDraft("llm", "不可信引用。", (uuid.uuid4(),)))

    answer = ExplanationService(provider).explain("为什么？", evidence)

    assert answer.mode == "fallback"
    assert answer.evidence_ids == tuple(item.id for item in evidence)


def test_runtime_mutated_provider_draft_falls_back_without_raising():
    evidence = _evidence()
    draft = ExplanationDraft("llm", "valid", (evidence[0].id,))
    object.__setattr__(draft, "text", None)
    provider = StubProvider(draft)

    answer = ExplanationService(provider).explain("为什么？", evidence)

    assert answer.mode == "fallback"


def test_provider_cannot_mutate_fallback_evidence():
    evidence = _evidence()

    class MutatingProvider:
        def explain(self, question, received):
            received[0].value_json = {"emotion": "injected"}
            raise RuntimeError("fail after mutation")

    answer = ExplanationService(MutatingProvider()).explain("为什么？", evidence)

    assert answer.mode == "fallback"
    assert "injected" not in answer.text
    assert evidence[0].public_value == {"symbol": "G"}


def test_no_eligible_evidence_skips_provider():
    item = _evidence()[0]
    item.eligible_for_llm = False
    provider = StubProvider(ExplanationDraft("llm", "不应调用。", (item.id,)))

    answer = ExplanationService(provider).explain("为什么？", (item,))

    assert answer.mode == "fallback"
    assert answer.evidence_ids == ()
    assert provider.calls == []


@pytest.mark.parametrize("question", ["", "   ", "x" * 501])
def test_question_must_be_nonempty_and_bounded(question):
    with pytest.raises(ValueError, match="question"):
        ExplanationService(provider=None).explain(question, _evidence())
