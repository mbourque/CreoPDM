"""Audit trail for important PDM actions."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from creopdm.constants import ActivityAction
from creopdm.models.activity import Activity
from creopdm.utils.identity import UserIdentity


class ActivityService:
    def record(
        self,
        session: Session,
        action: ActivityAction | str,
        user: UserIdentity,
        project_id: int | None = None,
        object_id: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> Activity:
        activity = Activity(
            project_id=project_id,
            object_id=object_id,
            user=user.user_name,
            machine=user.machine_name,
            action=str(action),
            details_json=json.dumps(details) if details else None,
        )
        session.add(activity)
        session.flush()
        return activity
