"""Helpers that translate ORM rows into Pydantic responses."""

from __future__ import annotations

from creopdm.constants import RemoteMode
from creopdm.models.checkout import Checkout
from creopdm.models.object import EngineeringObject
from creopdm.models.project import Project
from creopdm.models.version import ObjectVersion
from creopdm.schemas.common import ObjectResponse, ObjectVersionResponse, ProjectResponse
from creopdm.services.checkout_service import CheckoutView
from creopdm.utils.classify import display_type_label
from creopdm.utils.identity import UserIdentity


def revision_display(revision: str, iteration: int) -> str:
    return f"{revision}.{iteration}"


def project_to_response(project: Project) -> ProjectResponse:
    remote_mode = RemoteMode.LOCAL_WITH_REMOTE if project.remote_url else RemoteMode.LOCAL_ONLY
    return ProjectResponse(
        uuid=project.uuid,
        name=project.name,
        number=project.number,
        description=project.description,
        repository_path=project.repository_path,
        default_branch=project.default_branch,
        remote_url=project.remote_url,
        created_at=project.created_at,
        updated_at=project.updated_at,
        active=project.active,
        remote_mode=remote_mode.value,
    )


def version_to_response(
    version: ObjectVersion | None,
    filename: str | None = None,
    relative_path: str | None = None,
) -> ObjectVersionResponse | None:
    if version is None:
        return None
    obj = getattr(version, "object", None)
    return ObjectVersionResponse(
        uuid=version.uuid,
        revision=version.revision,
        iteration=version.iteration,
        display=revision_display(version.revision, version.iteration),
        filename=filename or version.filename or (obj.filename if obj is not None else None),
        relative_path=relative_path or version.relative_path or (obj.relative_path if obj is not None else None),
        content_hash=version.content_hash,
        file_size=version.file_size,
        created_by=version.created_by,
        created_at=version.created_at,
        comment=version.comment,
    )


def object_to_response(
    obj: EngineeringObject,
    project_uuid: str,
    view: CheckoutView | None = None,
    modified_locally: bool = False,
    current_user: UserIdentity | None = None,
    can_checkin: bool | None = None,
    in_workspace: bool = False,
    type_label: str | None = None,
) -> ObjectResponse:
    checkout: Checkout | None = view.checkout if view else None
    label = view.label if view else "Available"
    if modified_locally and (view is None or view.owned_by_me or checkout is None):
        label = "Modified locally" if view is None or checkout is None else f"{view.label} · Modified locally"
    return ObjectResponse(
        uuid=obj.uuid,
        project_uuid=project_uuid,
        number=obj.number,
        name=obj.name,
        filename=obj.filename,
        extension=obj.extension,
        object_type=obj.object_type,
        type_label=type_label if type_label is not None else display_type_label(obj.filename, obj.object_type),
        relative_path=obj.relative_path,
        revision=obj.revision,
        iteration=obj.iteration,
        display_revision=revision_display(obj.revision, obj.iteration),
        lifecycle_state=obj.lifecycle_state,
        checkout_status=label,
        checkout_user=checkout.user_name if checkout else None,
        checkout_machine=checkout.machine_name if checkout else None,
        checkout_since=checkout.checkout_time if checkout else None,
        owned_by_me=view.owned_by_me if view else False,
        modified_locally=modified_locally,
        can_checkout=view.can_checkout if view else obj.lifecycle_state == "IN_WORK",
        can_checkin=can_checkin if can_checkin is not None else (view.can_checkin if view else False),
        in_workspace=in_workspace,
        created_at=obj.created_at,
        updated_at=obj.updated_at,
        current_version=version_to_response(
            obj.current_version,
            filename=obj.filename,
            relative_path=obj.relative_path,
        ),
    )
