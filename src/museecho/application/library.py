from __future__ import annotations

import json
import uuid
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, sessionmaker

from museecho.application.lifecycle import AnalysisLifecycleService, ResultNotReadyError
from museecho.infrastructure.db import session_scope
from museecho.infrastructure.repositories import AnalysisJobModel, SavedAnalysisModel, UserModel

LIBRARY_LIMIT = 100
SNAPSHOT_MAX_BYTES = 2 * 1024 * 1024


class LibraryError(Exception):
    def __init__(self, code: str, status_code: int = 400):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


class LibraryService:
    def __init__(
        self, session_factory: sessionmaker[Session], lifecycle: AnalysisLifecycleService
    ) -> None:
        self._sessions = session_factory
        self._lifecycle = lifecycle

    def save(self, user_id: str, analysis_id: uuid.UUID, title: str) -> dict[str, Any]:
        from museecho.api.results import _serialize_result

        cleaned_title = _title(title)
        try:
            job = self._lifecycle.status(analysis_id)
            result = self._lifecycle.result(analysis_id)
        except (KeyError, ValueError):
            raise LibraryError("analysis_unavailable", 404) from None
        except ResultNotReadyError:
            raise LibraryError("analysis_not_ready", 409) from None
        if job.source_kind.value != "real" or job.stage.value != "complete":
            raise LibraryError("analysis_not_savable", 409)
        snapshot = _serialize_result(result, job.source_kind.value, job.pipeline_version)
        packed = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        if len(packed.encode("utf-8")) > SNAPSHOT_MAX_BYTES:
            raise LibraryError("snapshot_too_large", 413)
        now = datetime.now(timezone.utc)
        with session_scope(self._sessions) as session:
            # SQLite has no SELECT FOR UPDATE. Reserve the writer before checking quota/expiry.
            if session.bind is not None and session.bind.dialect.name == "sqlite":
                session.connection().exec_driver_sql("BEGIN IMMEDIATE")
            elif session.get(UserModel, user_id, with_for_update=True) is None:
                raise LibraryError("not_found", 404)
            source = session.get(AnalysisJobModel, str(analysis_id))
            if (
                source is None
                or source.expires_at is None
                or source.expires_at <= now
                or source.stage != "complete"
                or source.source_kind != "real"
            ):
                raise LibraryError("analysis_unavailable", 404)
            existing = session.scalar(
                select(SavedAnalysisModel).where(
                    SavedAnalysisModel.user_id == user_id,
                    SavedAnalysisModel.original_analysis_id == str(analysis_id),
                )
            )
            if existing is not None:
                return _metadata(existing)
            count = session.scalar(
                select(func.count())
                .select_from(SavedAnalysisModel)
                .where(SavedAnalysisModel.user_id == user_id)
            )
            if count is not None and count >= LIBRARY_LIMIT:
                raise LibraryError("library_full", 409)
            saved = SavedAnalysisModel(
                id=str(uuid.uuid4()),
                user_id=user_id,
                original_analysis_id=str(analysis_id),
                title=cleaned_title,
                snapshot_json=packed,
                snapshot_version=1,
                preference="unmarked",
                saved_at=now,
            )
            session.add(saved)
            session.flush()
            return _metadata(saved)

    def list(
        self,
        user_id: str,
        *,
        offset: int = 0,
        limit: int = 20,
        query: str = "",
        sort: str = "newest",
    ) -> dict[str, Any]:
        if offset < 0 or limit < 1 or limit > 100:
            raise LibraryError("invalid_page")
        if len(query) > 80 or sort not in {"newest", "oldest", "title"}:
            raise LibraryError("invalid_filter")
        with session_scope(self._sessions) as session:
            saved_count = session.scalar(
                select(func.count())
                .select_from(SavedAnalysisModel)
                .where(SavedAnalysisModel.user_id == user_id)
            )
            filters = [SavedAnalysisModel.user_id == user_id]
            if query.strip():
                safe = query.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                filters.append(SavedAnalysisModel.title.like(f"%{safe}%", escape="\\"))
            count = session.scalar(
                select(func.count()).select_from(SavedAnalysisModel).where(*filters)
            )
            ordering: tuple[Any, Any]
            if sort == "oldest":
                ordering = (SavedAnalysisModel.saved_at.asc(), SavedAnalysisModel.id.asc())
            elif sort == "title":
                ordering = (SavedAnalysisModel.title.asc(), SavedAnalysisModel.id.asc())
            else:
                ordering = (SavedAnalysisModel.saved_at.desc(), SavedAnalysisModel.id.desc())
            rows = session.scalars(
                select(SavedAnalysisModel)
                .where(*filters)
                .order_by(*ordering)
                .offset(offset)
                .limit(limit)
            ).all()
            return {
                "items": [_metadata(row) for row in rows],
                "total": count or 0,
                "saved_count": saved_count or 0,
                "limit": LIBRARY_LIMIT,
            }

    def get(self, user_id: str, saved_id: uuid.UUID) -> dict[str, Any]:
        with session_scope(self._sessions) as session:
            saved = self._owned(session, user_id, saved_id)
            if saved is None:
                raise LibraryError("not_found", 404)
            return {
                **_metadata(saved),
                "analysis": json.loads(saved.snapshot_json),
                "audio_available": False,
            }

    def update(
        self, user_id: str, saved_id: uuid.UUID, *, title: str | None, preference: str | None
    ) -> dict[str, Any]:
        if title is None and preference is None:
            raise LibraryError("empty_update")
        if preference is not None and preference not in {"unmarked", "liked", "disliked"}:
            raise LibraryError("invalid_preference")
        with session_scope(self._sessions) as session:
            saved = self._owned(session, user_id, saved_id)
            if saved is None:
                raise LibraryError("not_found", 404)
            if title is not None:
                saved.title = _title(title)
            if preference is not None:
                saved.preference = preference
            session.flush()
            return _metadata(saved)

    def delete(self, user_id: str, saved_id: uuid.UUID) -> None:
        with session_scope(self._sessions) as session:
            saved = self._owned(session, user_id, saved_id)
            if saved is None:
                raise LibraryError("not_found", 404)
            session.delete(saved)

    def delete_by_source(self, user_id: str, analysis_id: uuid.UUID) -> None:
        with session_scope(self._sessions) as session:
            session.execute(
                delete(SavedAnalysisModel).where(
                    SavedAnalysisModel.user_id == user_id,
                    SavedAnalysisModel.original_analysis_id == str(analysis_id),
                )
            )

    def profile(self, user_id: str) -> dict[str, Any]:
        with session_scope(self._sessions) as session:
            user = session.get(UserModel, user_id)
            if user is None:
                raise LibraryError("not_found", 404)
            enabled = user.profile_enabled
            rows = session.scalars(
                select(SavedAnalysisModel).where(
                    SavedAnalysisModel.user_id == user_id,
                    SavedAnalysisModel.preference == "liked",
                )
            ).all()
            liked = [
                {"id": row.id, "title": row.title, "analysis": json.loads(row.snapshot_json)}
                for row in rows
            ]
        if not enabled:
            return {"enabled": False, "sample_count": len(liked), "tags": []}
        if len(liked) < 5:
            return {"enabled": True, "sample_count": len(liked), "minimum_samples": 5, "tags": []}
        return {
            "enabled": True,
            "sample_count": len(liked),
            "minimum_samples": 5,
            "version": "preference_v1",
            "tags": _profile_tags(liked),
        }

    def set_profile_enabled(self, user_id: str, enabled: bool) -> dict[str, Any]:
        with session_scope(self._sessions) as session:
            user = session.get(UserModel, user_id)
            if user is None:
                raise LibraryError("not_found", 404)
            user.profile_enabled = enabled
        return self.profile(user_id)

    @staticmethod
    def _owned(session: Session, user_id: str, saved_id: uuid.UUID) -> SavedAnalysisModel | None:
        return session.scalar(
            select(SavedAnalysisModel).where(
                SavedAnalysisModel.id == str(saved_id), SavedAnalysisModel.user_id == user_id
            )
        )


def _title(value: str) -> str:
    cleaned = value.strip()
    if not cleaned or len(cleaned) > 120 or any(ord(char) < 32 for char in cleaned):
        raise LibraryError("invalid_title")
    return cleaned


def _metadata(row: SavedAnalysisModel) -> dict[str, Any]:
    return {
        "id": row.id,
        "original_analysis_id": row.original_analysis_id,
        "title": row.title,
        "preference": row.preference,
        "saved_at": row.saved_at.isoformat(),
    }


def _profile_tags(liked: list[dict[str, Any]]) -> list[dict[str, Any]]:
    tags: list[dict[str, Any]] = []
    tempo: list[tuple[float, str]] = []
    modes: list[tuple[str, str]] = []
    chord_variety: list[tuple[int, str]] = []
    section_variety: list[tuple[int, str]] = []
    for item in liked:
        analysis = item["analysis"]
        track = analysis.get("track", {})
        bpm = track.get("bpm")
        if isinstance(bpm, (float, int)) and (track.get("bpm_confidence") or 0) >= 0.7:
            tempo.append((float(bpm), item["id"]))
        mode = track.get("mode")
        if mode in {"major", "minor"} and (track.get("key_confidence") or 0) >= 0.7:
            modes.append((mode, item["id"]))
        chords = {
            event["symbol"]
            for event in analysis.get("chords", [])
            if event.get("symbol") != "unknown" and (event.get("confidence") or 0) >= 0.7
        }
        if len(chords) >= 2:
            chord_variety.append((len(chords), item["id"]))
        sections = {
            event["label"]
            for event in analysis.get("sections", [])
            if event.get("label") != "unknown" and (event.get("confidence") or 0) >= 0.7
        }
        if len(sections) >= 2:
            section_variety.append((len(sections), item["id"]))
    if len(tempo) >= 5:
        median = sorted(value for value, _ in tempo)[len(tempo) // 2]
        name = "舒缓速度" if median < 90 else "明快速度" if median >= 125 else "中速律动"
        tags.append(
            {
                "name": name,
                "basis": "高置信 BPM 中位数",
                "sample_count": len(tempo),
                "song_ids": [song_id for _, song_id in tempo],
                "version": "preference_v1",
            }
        )
    if len(modes) >= 5:
        dominant, count = Counter(mode for mode, _ in modes).most_common(1)[0]
        if count / len(modes) >= 0.7:
            tags.append(
                {
                    "name": "大调作品较多" if dominant == "major" else "小调作品较多",
                    "basis": "高置信调式占比至少 70%",
                    "sample_count": len(modes),
                    "song_ids": [song_id for mode, song_id in modes if mode == dominant],
                    "version": "preference_v1",
                }
            )
    if len(chord_variety) >= 5:
        median = sorted(value for value, _ in chord_variety)[len(chord_variety) // 2]
        if median >= 4:
            tags.append(
                {
                    "name": "和声变化较丰富",
                    "basis": "高置信和弦种类中位数至少 4",
                    "sample_count": len(chord_variety),
                    "song_ids": [song_id for _, song_id in chord_variety],
                    "version": "preference_v1",
                }
            )
    if len(section_variety) >= 5:
        median = sorted(value for value, _ in section_variety)[len(section_variety) // 2]
        if median >= 3:
            tags.append(
                {
                    "name": "段落结构变化较多",
                    "basis": "高置信段落类别中位数至少 3",
                    "sample_count": len(section_variety),
                    "song_ids": [song_id for _, song_id in section_variety],
                    "version": "preference_v1",
                }
            )
    titles = {item["id"]: item["title"] for item in liked}
    for tag in tags:
        tag["sources"] = [{"id": song_id, "title": titles[song_id]} for song_id in tag["song_ids"]]
    return tags
