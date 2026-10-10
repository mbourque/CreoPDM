"""Persist and read per-version experimental AI model snapshots."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from creopdm.ai_prompts import (
    CHECKIN_BATCH_COMMENT_SYSTEM,
    build_checkin_batch_comment_user_prompt,
    build_snapshot_compare_user_prompt,
    format_checkin_batch_comment_fallback,
    format_snapshot_compare_diff_text,
    format_snapshot_compare_text,
    prepare_snapshot_for_compare,
    resolve_snapshot_compare_prompt,
)
from creopdm.config import AppSettings
from creopdm.exceptions import NotFoundError, ValidationAppError
from creopdm.models.ai_snapshot import ObjectVersionSnapshot
from creopdm.models.object import EngineeringObject
from creopdm.models.version import ObjectVersion
from creopdm.product_state import ensure_product_allows
from creopdm.schemas.common import (
    AiCheckinCommentSynthesizeResponse,
    AiSnapshotCompareResponse,
    AiSnapshotListItem,
    AiSnapshotListResponse,
    AiSnapshotRequest,
    AiSnapshotResponse,
    AiSnapshotWhatChangedResponse,
)
from creopdm.services.object_service import ObjectService
from creopdm.services.ollama_service import chat_ollama

AI_SNAPSHOT_SCHEMA_VERSION = 1


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def _loads(raw: str | None) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


def _display_revision(version: ObjectVersion) -> str:
    rev = str(version.revision or "").strip() or "A"
    return f"{rev}.{int(version.iteration or 0)}"


def _snapshot_with_bom_fallback(
    snapshot: dict[str, Any] | None,
    version: ObjectVersion,
) -> dict[str, Any] | None:
    """
    Older AI snapshots omit Structure/BOM (Features skip components).
    Fall back to the version's bom_json / features_json structure so Compare
    Revisions can trust Structure.
    """
    if not isinstance(snapshot, dict):
        return snapshot
    merged = dict(snapshot)
    changed = False
    bom = merged.get("bom")
    if not (isinstance(bom, list) and bom):
        fallback = _loads(getattr(version, "bom_json", None))
        if isinstance(fallback, list) and fallback:
            merged["bom"] = fallback
            changed = True
    need_struct = not (isinstance(merged.get("structure"), list) and merged.get("structure"))
    need_simp = not (isinstance(merged.get("simp_reps"), dict) and merged.get("simp_reps"))
    if need_struct or need_simp:
        from creopdm.services.metadata_service import unpack_features_json

        _feats, struct, simp = unpack_features_json(
            _loads(getattr(version, "features_json", None))
        )
        if need_struct and isinstance(struct, list) and struct:
            merged["structure"] = struct
            changed = True
        if need_simp and isinstance(simp, dict) and simp:
            merged["simp_reps"] = simp
            changed = True
            capture = merged.get("capture")
            if not isinstance(capture, dict):
                capture = {}
                merged["capture"] = capture
            if capture.get("assembly_context") is None and isinstance(
                simp.get("active"), dict
            ):
                capture["assembly_context"] = {"active_simp_rep": simp.get("active")}
    return merged if changed else snapshot


class AiSnapshotService:
    def __init__(self, objects: ObjectService) -> None:
        self._objects = objects

    def _resolve_version(
        self,
        session: Session,
        obj: EngineeringObject,
        version_uuid: str | None,
    ) -> ObjectVersion | None:
        if version_uuid:
            version = session.scalar(
                select(ObjectVersion).where(
                    ObjectVersion.uuid == version_uuid,
                    ObjectVersion.object_id == obj.id,
                )
            )
            if version is None:
                raise NotFoundError(
                    "Version not found for this file.",
                    details={"version_id": version_uuid, "object_id": obj.uuid},
                )
            return version
        if obj.current_version_id:
            return session.get(ObjectVersion, obj.current_version_id)
        return session.scalar(
            select(ObjectVersion)
            .where(ObjectVersion.object_id == obj.id)
            .order_by(ObjectVersion.iteration.desc())
            .limit(1)
        )

    def _row_to_response(
        self,
        obj: EngineeringObject,
        version: ObjectVersion,
        row: ObjectVersionSnapshot | None,
    ) -> AiSnapshotResponse:
        if row is None:
            return AiSnapshotResponse(
                object_id=obj.uuid,
                version_id=version.uuid,
                display_revision=_display_revision(version),
                has_snapshot=False,
                schema_version=AI_SNAPSHOT_SCHEMA_VERSION,
                content_hash=version.content_hash or None,
                captured_at=None,
                capture_status=None,
                capture_errors=[],
                snapshot=None,
                outline=None,
            )
        errors = _loads(row.capture_errors)
        if not isinstance(errors, list):
            errors = []
        snapshot = _loads(row.snapshot_json)
        if not isinstance(snapshot, dict):
            snapshot = {"raw": snapshot} if snapshot is not None else None
        if isinstance(snapshot, dict):
            snapshot = _snapshot_with_bom_fallback(snapshot, version)
            # Same prep Compare panes + Check In Ask AI use (parts/asm/drawings).
            snapshot = prepare_snapshot_for_compare(snapshot)
        outline = (
            format_snapshot_compare_text(snapshot)
            if isinstance(snapshot, dict)
            else None
        )
        return AiSnapshotResponse(
            object_id=obj.uuid,
            version_id=version.uuid,
            display_revision=_display_revision(version),
            has_snapshot=True,
            schema_version=int(row.schema_version or AI_SNAPSHOT_SCHEMA_VERSION),
            content_hash=row.content_hash or version.content_hash or None,
            captured_at=row.captured_at,
            capture_status=row.capture_status,
            capture_errors=[str(item) for item in errors],
            snapshot=snapshot,
            outline=outline,
        )

    def save(
        self,
        session: Session,
        object_uuid: str,
        payload: AiSnapshotRequest,
    ) -> AiSnapshotResponse:
        obj = self._objects.get_object(session, object_uuid)
        ensure_product_allows(obj.product, "edit_metadata", action="save AI snapshot")
        version = self._resolve_version(session, obj, payload.version_id)
        if version is None:
            raise ValidationAppError(
                "This file has no version to attach an AI snapshot to.",
                details={"object_id": object_uuid},
            )
        if not isinstance(payload.snapshot, dict) or not payload.snapshot:
            raise ValidationAppError(
                "AI snapshot body is required.",
                details={"object_id": object_uuid},
            )

        # Refuse PART/ASSEMBLY solid walks stored on a drawing object (stem collision).
        obj_name = str(version.filename or obj.filename or "").lower()
        identity = payload.snapshot.get("identity") if isinstance(payload.snapshot, dict) else None
        snap_type = ""
        snap_file = ""
        if isinstance(identity, dict):
            snap_type = str(identity.get("model_type") or "").strip().upper()
            snap_file = str(identity.get("filename") or "").strip().lower()
        if obj_name.endswith(".drw") and (
            snap_type in {"PART", "ASSEMBLY"}
            or snap_file.endswith(".prt")
            or snap_file.endswith(".asm")
        ):
            raise ValidationAppError(
                "AI snapshot for a drawing cannot be a part/assembly solid. "
                "Re-Collect the drawing in Creo Connected.",
                details={
                    "object_id": object_uuid,
                    "object_filename": version.filename or obj.filename,
                    "snapshot_filename": snap_file or None,
                    "snapshot_model_type": snap_type or None,
                },
            )

        schema_version = int(payload.schema_version or AI_SNAPSHOT_SCHEMA_VERSION)
        status = str(payload.capture_status or "ok").strip().lower() or "ok"
        if status not in {"ok", "partial", "error"}:
            status = "partial"
        errors = [str(item) for item in (payload.capture_errors or []) if str(item).strip()]
        content_hash = str(payload.content_hash or version.content_hash or "").strip() or None

        document = dict(payload.snapshot)
        document["schema_version"] = schema_version
        item = document.get("item") if isinstance(document.get("item"), dict) else {}
        item = {
            **item,
            "object_uuid": obj.uuid,
            "version_uuid": version.uuid,
            "display_revision": _display_revision(version),
            "filename": version.filename or obj.filename,
            "content_hash": content_hash or item.get("content_hash"),
        }
        document["item"] = item
        capture = document.get("capture") if isinstance(document.get("capture"), dict) else {}
        now = datetime.now(timezone.utc)
        capture = {
            **capture,
            "status": status,
            "errors": errors,
            "captured_at": now.isoformat(),
        }
        document["capture"] = capture

        row = session.scalar(
            select(ObjectVersionSnapshot).where(ObjectVersionSnapshot.version_id == version.id)
        )
        if row is None:
            row = ObjectVersionSnapshot(
                uuid=str(uuid.uuid4()),
                object_id=obj.id,
                version_id=version.id,
            )
            session.add(row)
        row.schema_version = schema_version
        row.content_hash = content_hash
        row.captured_at = now
        row.capture_status = status
        row.capture_errors = _dumps(errors) if errors else None
        row.snapshot_json = _dumps(document)
        session.flush()
        return self._row_to_response(obj, version, row)

    def get(
        self,
        session: Session,
        object_uuid: str,
        version_uuid: str | None = None,
    ) -> AiSnapshotResponse:
        obj = self._objects.get_object(session, object_uuid)
        version = self._resolve_version(session, obj, version_uuid)
        if version is None:
            return AiSnapshotResponse(
                object_id=obj.uuid,
                version_id=None,
                display_revision="",
                has_snapshot=False,
                schema_version=AI_SNAPSHOT_SCHEMA_VERSION,
            )
        row = session.scalar(
            select(ObjectVersionSnapshot).where(ObjectVersionSnapshot.version_id == version.id)
        )
        return self._row_to_response(obj, version, row)

    def list_for_object(self, session: Session, object_uuid: str) -> AiSnapshotListResponse:
        obj = self._objects.get_object(session, object_uuid)
        versions = session.scalars(
            select(ObjectVersion)
            .where(ObjectVersion.object_id == obj.id)
            .order_by(ObjectVersion.iteration.desc())
        ).all()
        snap_by_version = {
            row.version_id: row
            for row in session.scalars(
                select(ObjectVersionSnapshot).where(ObjectVersionSnapshot.object_id == obj.id)
            ).all()
        }
        items: list[AiSnapshotListItem] = []
        for version in versions:
            row = snap_by_version.get(version.id)
            items.append(
                AiSnapshotListItem(
                    version_id=version.uuid,
                    display_revision=_display_revision(version),
                    has_snapshot=row is not None,
                    captured_at=row.captured_at if row else None,
                    capture_status=row.capture_status if row else None,
                    content_hash=(row.content_hash if row else None) or version.content_hash,
                )
            )
        return AiSnapshotListResponse(object_id=obj.uuid, items=items)

    def count_with_snapshot(self, session: Session, object_uuid: str) -> int:
        """How many History revisions have a saved AI snapshot (for Modifications tab)."""
        return sum(1 for item in self.list_for_object(session, object_uuid).items if item.has_snapshot)

    def outline_from_snapshot(
        self,
        snapshot: dict[str, Any],
        *,
        display_revision: str = "pending",
    ) -> tuple[str, str]:
        """Plain-language outline for a gathered (not yet saved) snapshot — same prep as Compare."""
        if not isinstance(snapshot, dict) or not snapshot:
            raise ValidationAppError("Snapshot JSON is required.")
        prepared = prepare_snapshot_for_compare(snapshot)
        text = format_snapshot_compare_text(prepared)
        label = (display_revision or "").strip() or "pending"
        return str(text or "").strip(), label

    def _load_compare_pair(
        self,
        session: Session,
        object_uuid: str,
        older_version_id: str,
        newer_version_id: str,
    ) -> tuple[AiSnapshotResponse, AiSnapshotResponse]:
        older_id = (older_version_id or "").strip()
        newer_id = (newer_version_id or "").strip()
        if not older_id or not newer_id:
            raise ValidationAppError("Choose both an older and a newer snapshot revision.")
        if older_id == newer_id:
            raise ValidationAppError("Pick two different revisions to compare.")

        older = self.get(session, object_uuid, older_id)
        newer = self.get(session, object_uuid, newer_id)
        if not older.has_snapshot or not isinstance(older.snapshot, dict):
            raise ValidationAppError(
                f"Revision {older.display_revision or older_id} has no snapshot yet. "
                "Collect metadata while that version is tip.",
                details={"version_id": older_id},
            )
        if not newer.has_snapshot or not isinstance(newer.snapshot, dict):
            raise ValidationAppError(
                f"Revision {newer.display_revision or newer_id} has no snapshot yet. "
                "Collect metadata while that version is tip.",
                details={"version_id": newer_id},
            )
        return older, newer

    def _load_compare_pending(
        self,
        session: Session,
        object_uuid: str,
        newer_snapshot: dict[str, Any],
        *,
        older_version_id: str | None = None,
        newer_display_revision: str = "pending",
    ) -> tuple[AiSnapshotResponse, dict[str, Any], str]:
        if not isinstance(newer_snapshot, dict) or not newer_snapshot:
            raise ValidationAppError("Newer snapshot JSON is required.")
        older_id = (older_version_id or "").strip() or None
        older = self.get(session, object_uuid, older_id)
        if not older.version_id:
            raise ValidationAppError("This file has no version to compare against.")
        if not older.has_snapshot or not isinstance(older.snapshot, dict):
            raise ValidationAppError(
                f"Revision {older.display_revision or older.version_id} has no snapshot yet. "
                "Collect metadata while that version is tip, then try again.",
                details={"version_id": older.version_id},
            )
        newer_label = (newer_display_revision or "").strip() or "pending"
        return older, newer_snapshot, newer_label

    def _build_what_changed(
        self,
        *,
        object_uuid: str,
        older_snapshot: dict[str, Any],
        newer_snapshot: dict[str, Any],
        older_revision: str,
        newer_revision: str,
        older_version_id: str,
        newer_version_id: str,
    ) -> AiSnapshotWhatChangedResponse:
        """Same Computed differences block Ask AI receives — no Ollama, AI may be off."""
        older_prepared = prepare_snapshot_for_compare(older_snapshot)
        newer_prepared = prepare_snapshot_for_compare(newer_snapshot)
        diff_text = format_snapshot_compare_diff_text(older_prepared, newer_prepared)
        return AiSnapshotWhatChangedResponse(
            object_id=object_uuid,
            older_version_id=older_version_id,
            newer_version_id=newer_version_id,
            older_display_revision=older_revision,
            newer_display_revision=newer_revision,
            computed_differences=str(diff_text or "").strip(),
        )

    def what_changed(
        self,
        session: Session,
        object_uuid: str,
        older_version_id: str,
        newer_version_id: str,
        _settings: AppSettings,
    ) -> AiSnapshotWhatChangedResponse:
        """Computed differences for two History snapshots (works with AI off)."""
        older, newer = self._load_compare_pair(
            session, object_uuid, older_version_id, newer_version_id
        )
        return self._build_what_changed(
            object_uuid=object_uuid,
            older_snapshot=older.snapshot,
            newer_snapshot=newer.snapshot,
            older_revision=older.display_revision,
            newer_revision=newer.display_revision,
            older_version_id=older.version_id or older_version_id,
            newer_version_id=newer.version_id or newer_version_id,
        )

    def what_changed_pending(
        self,
        session: Session,
        object_uuid: str,
        newer_snapshot: dict[str, Any],
        _settings: AppSettings,
        *,
        older_version_id: str | None = None,
        newer_display_revision: str = "pending",
    ) -> AiSnapshotWhatChangedResponse:
        """Computed differences for tip vs live gather (works with AI off)."""
        older, newer_snap, newer_label = self._load_compare_pending(
            session,
            object_uuid,
            newer_snapshot,
            older_version_id=older_version_id,
            newer_display_revision=newer_display_revision,
        )
        return self._build_what_changed(
            object_uuid=object_uuid,
            older_snapshot=older.snapshot,
            newer_snapshot=newer_snap,
            older_revision=older.display_revision,
            newer_revision=newer_label,
            older_version_id=older.version_id or "",
            newer_version_id="",
        )

    def _chat_compare(
        self,
        *,
        object_uuid: str,
        older_snapshot: dict[str, Any],
        newer_snapshot: dict[str, Any],
        older_revision: str,
        newer_revision: str,
        older_version_id: str,
        newer_version_id: str,
        settings: AppSettings,
    ) -> AiSnapshotCompareResponse:
        if not bool(settings.ai.enabled):
            raise ValidationAppError(
                "AI features are turned off. Open System Settings → AI, "
                "check Enable AI features, and Save."
            )
        model = str(settings.ai.ollama_model or "").strip()
        if not model:
            raise ValidationAppError(
                "No Ollama model selected. Open System Settings → AI, Refresh models, choose a model, and Save."
            )
        # One prompt path for Modifications Ask AI and Check In Ask AI
        # (parts, assemblies, drawings) — prepare lives inside build_*.
        system_prompt = resolve_snapshot_compare_prompt(settings.ai.snapshot_compare_prompt)
        user_prompt = build_snapshot_compare_user_prompt(
            older_snapshot=older_snapshot,
            newer_snapshot=newer_snapshot,
            older_revision=older_revision,
            newer_revision=newer_revision,
        )
        summary = chat_ollama(
            settings.ai.ollama_base_url,
            model,
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        return AiSnapshotCompareResponse(
            object_id=object_uuid,
            older_version_id=older_version_id,
            newer_version_id=newer_version_id,
            older_display_revision=older_revision,
            newer_display_revision=newer_revision,
            model=model,
            summary=summary,
        )

    def compare_with_ollama(
        self,
        session: Session,
        object_uuid: str,
        older_version_id: str,
        newer_version_id: str,
        settings: AppSettings,
    ) -> AiSnapshotCompareResponse:
        """Load two saved snapshots and ask the configured Ollama model what changed."""
        older, newer = self._load_compare_pair(
            session, object_uuid, older_version_id, newer_version_id
        )
        return self._chat_compare(
            object_uuid=object_uuid,
            older_snapshot=older.snapshot,
            newer_snapshot=newer.snapshot,
            older_revision=older.display_revision,
            newer_revision=newer.display_revision,
            older_version_id=older.version_id or older_version_id,
            newer_version_id=newer.version_id or newer_version_id,
            settings=settings,
        )

    def compare_pending_with_ollama(
        self,
        session: Session,
        object_uuid: str,
        newer_snapshot: dict[str, Any],
        settings: AppSettings,
        *,
        older_version_id: str | None = None,
        newer_display_revision: str = "pending",
    ) -> AiSnapshotCompareResponse:
        """Check In Ask AI: tip snapshot vs pending gather — same ``_chat_compare``
        as Modifications (parts, assemblies, drawings)."""
        older, newer_snap, newer_label = self._load_compare_pending(
            session,
            object_uuid,
            newer_snapshot,
            older_version_id=older_version_id,
            newer_display_revision=newer_display_revision,
        )
        # Same Ask AI path as compare_with_ollama → _chat_compare →
        # prepare_snapshot_for_compare + build_snapshot_compare_user_prompt.
        return self._chat_compare(
            object_uuid=object_uuid,
            older_snapshot=older.snapshot,
            newer_snapshot=newer_snap,
            older_revision=older.display_revision,
            newer_revision=newer_label,
            older_version_id=older.version_id,
            newer_version_id="",
            settings=settings,
        )

    def synthesize_checkin_comment(
        self,
        notes: list[dict[str, str]],
        settings: AppSettings,
    ) -> AiCheckinCommentSynthesizeResponse:
        """Turn per-file Ask AI notes into one shared check-in comment."""
        if not bool(settings.ai.enabled):
            raise ValidationAppError(
                "AI features are turned off. Open System Settings → AI, "
                "check Enable AI features, and Save."
            )
        model = str(settings.ai.ollama_model or "").strip()
        if not model:
            raise ValidationAppError(
                "No Ollama model selected. Open System Settings → AI, Refresh models, "
                "choose a model, and Save."
            )
        cleaned: list[dict[str, str]] = []
        for note in notes or []:
            if not isinstance(note, dict):
                continue
            summary = str(note.get("summary") or "").strip()
            if not summary:
                continue
            cleaned.append(
                {
                    "filename": str(note.get("filename") or "").strip(),
                    "summary": summary,
                }
            )
        if not cleaned:
            raise ValidationAppError("No per-file change notes to summarize.")
        if len(cleaned) == 1:
            return AiCheckinCommentSynthesizeResponse(
                summary=cleaned[0]["summary"],
                model=model,
                fallback=False,
            )
        user_prompt = build_checkin_batch_comment_user_prompt(cleaned)
        try:
            summary = chat_ollama(
                settings.ai.ollama_base_url,
                model,
                [
                    {"role": "system", "content": CHECKIN_BATCH_COMMENT_SYSTEM},
                    {"role": "user", "content": user_prompt},
                ],
            )
            text = str(summary or "").strip()
            if text:
                return AiCheckinCommentSynthesizeResponse(
                    summary=text,
                    model=model,
                    fallback=False,
                )
        except Exception:
            pass
        return AiCheckinCommentSynthesizeResponse(
            summary=format_checkin_batch_comment_fallback(cleaned),
            model=model,
            fallback=True,
        )
