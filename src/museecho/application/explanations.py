from __future__ import annotations

import copy
import json
import uuid

from museecho.application.evidence import select_for_segment
from museecho.domain.models import Evidence, ExplanationDraft
from museecho.domain.ports import ExplanationProvider

_KIND_LABELS = {
    "rhythm": "节奏",
    "energy": "能量",
    "tonality": "调性",
    "section": "结构段落",
    "chord": "和弦",
    "deterministic_theory": "确定性乐理",
}


class ExplanationService:
    def __init__(self, provider: ExplanationProvider | None) -> None:
        self._provider = provider

    def explain(
        self,
        question: str,
        evidence: tuple[Evidence, ...],
    ) -> ExplanationDraft:
        if not isinstance(question, str) or not question.strip() or len(question) > 500:
            raise ValueError("question must contain between 1 and 500 characters")
        selected = _select_all(evidence)
        if self._provider is not None and selected:
            allowed_ids = {item.id for item in selected}
            provider_evidence = copy.deepcopy(selected)
            try:
                draft = self._provider.explain(question.strip(), provider_evidence)
            except Exception:
                pass
            else:
                if _valid_provider_draft(draft, allowed_ids):
                    return draft
        return _fallback(selected)


def _select_all(evidence: tuple[Evidence, ...]) -> tuple[Evidence, ...]:
    if not evidence:
        return ()
    return select_for_segment(
        evidence,
        min(item.start_seconds for item in evidence),
        max(item.end_seconds for item in evidence),
    )


def _fallback(evidence: tuple[Evidence, ...]) -> ExplanationDraft:
    evidence_ids = tuple(item.id for item in evidence)
    if not evidence:
        text = "当前片段没有达到置信度门槛的音乐证据，因此无法给出事实性解释。"
    else:
        parts: list[str] = []
        fact_characters = 0
        for item in evidence:
            value = json.dumps(item.public_value, ensure_ascii=False, sort_keys=True)
            part = (
                f"{_KIND_LABELS[item.kind]} {value}"
                f"（置信度 {item.confidence:.2f}，来源 {item.algorithm}）"
            )
            if fact_characters + len(part) > 3_400:
                break
            parts.append(part)
            fact_characters += len(part)
        facts = "；".join(parts)
        text = (
            f"确定性回退解释：当前可确认的分析证据为 {facts}。"
            "这些标签描述该时间窗中的可观察模式，可帮助学习和声与结构，"
            "但不表示唯一因果关系。"
        )
    return ExplanationDraft(mode="fallback", text=text, evidence_ids=evidence_ids)


def _valid_provider_draft(
    draft: object,
    allowed_ids: set[uuid.UUID],
) -> bool:
    if not isinstance(draft, ExplanationDraft):
        return False
    if (
        draft.mode != "llm"
        or not isinstance(draft.text, str)
        or not draft.text.strip()
        or len(draft.text) > 4_000
    ):
        return False
    if (
        not isinstance(draft.evidence_ids, tuple)
        or not draft.evidence_ids
        or not all(isinstance(evidence_id, uuid.UUID) for evidence_id in draft.evidence_ids)
        or len(set(draft.evidence_ids)) != len(draft.evidence_ids)
    ):
        return False
    return all(evidence_id in allowed_ids for evidence_id in draft.evidence_ids)
