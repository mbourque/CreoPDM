"""Pydantic request/response models."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from creopdm.constants import APP_NAME, APP_VERSION


class HealthResponse(BaseModel):
    status: str = "ok"
    name: str = APP_NAME
    version: str = APP_VERSION


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    error: ErrorBody


class ProjectCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    repository_path: str = Field(min_length=1)
    number: str | None = None
    description: str | None = None

    @field_validator("repository_path")
    @classmethod
    def location_required(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("A project location is required.")
        return cleaned


class ProjectUpdateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    number: str | None = None
    description: str | None = None


class ForgetProjectRequest(BaseModel):
    confirm_name: str = Field(min_length=1, max_length=255)


class ForgetProjectResponse(BaseModel):
    uuid: str
    name: str
    repository_path: str
    warning: str = ""


class ProjectResponse(BaseModel):
    uuid: str
    name: str
    number: str | None
    description: str | None
    repository_path: str
    default_branch: str
    remote_url: str | None
    created_at: datetime | None
    updated_at: datetime | None
    active: bool
    remote_mode: str


class ObjectVersionResponse(BaseModel):
    uuid: str
    revision: str
    iteration: int
    display: str
    filename: str | None = None
    relative_path: str | None = None
    content_hash: str
    file_size: int
    created_by: str
    created_at: datetime | None
    comment: str


class ObjectResponse(BaseModel):
    uuid: str
    project_uuid: str
    number: str | None
    name: str
    filename: str
    extension: str
    object_type: str
    relative_path: str
    revision: str
    iteration: int
    display_revision: str
    lifecycle_state: str
    checkout_status: str = "Available"
    checkout_user: str | None = None
    checkout_machine: str | None = None
    checkout_since: datetime | None = None
    owned_by_me: bool = False
    modified_locally: bool = False
    can_checkout: bool = True
    can_checkin: bool = False
    created_at: datetime | None
    updated_at: datetime | None
    current_version: ObjectVersionResponse | None = None


class CheckinRequest(BaseModel):
    comment: str = Field(min_length=1)
    add_relative_paths: list[str] = Field(default_factory=list)

    @field_validator("comment")
    @classmethod
    def comment_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("A check-in comment is required.")
        return stripped


class QueueCheckinRequest(BaseModel):
    comment: str = Field(min_length=1)
    object_ids: list[str] = Field(default_factory=list)
    add_relative_paths: list[str] = Field(default_factory=list)

    @field_validator("comment")
    @classmethod
    def comment_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("A check-in comment is required.")
        return stripped


class CheckinNewFile(BaseModel):
    filename: str
    relative_path: str
    path: str
    object_type: str
    same_folder: bool = False


class CheckinPreviewResponse(BaseModel):
    filename: str
    current_display: str
    next_display: str
    file_modified: bool
    parameters_changed: bool
    dependencies_unchanged: bool
    can_checkin: bool
    force_checkin: bool = False
    warning: str = ""
    queue_mode: bool = False
    object_ids: list[str] = Field(default_factory=list)
    pending_files: list[str] = Field(default_factory=list)
    new_files: list[CheckinNewFile] = Field(default_factory=list)


class CreoOpenRequest(BaseModel):
    object_id: str


class CreoOpenResponse(BaseModel):
    filename: str
    path: str
    method: str
    working_directory: str


class CreoStatusResponse(BaseModel):
    connector: str
    available: bool
    running: bool
    label: str


class ProjectStatusResponse(BaseModel):
    files: int
    creo_parts: int
    assemblies: int
    drawings: int
    documents: int
    checked_out_by_me: int
    checked_out_by_others: int
    modified_locally: int
    out_of_date: int
    untracked: int


class ImportLocalRequest(BaseModel):
    paths: list[str] = Field(min_length=1)
    comment: str | None = None


class WorkspacePickerResponse(BaseModel):
    workspace_root: str
    initial_directory: str
    selected: list[str] = Field(default_factory=list)


class FolderPickResponse(BaseModel):
    path: str | None = None
    initial_directory: str


class BatchObjectRequest(BaseModel):
    object_ids: list[str] = Field(min_length=1)


class BatchItemResult(BaseModel):
    uuid: str
    filename: str
    status: str | None = None
    path: str | None = None
    code: str | None = None
    message: str | None = None


class BatchOperationResponse(BaseModel):
    ok: list[BatchItemResult]
    failed: list[BatchItemResult]
    workspace_root: str | None = None


class SettingsResponse(BaseModel):
    creo_open_mode: str
    creo_executable: str | None
    workspace_root: str
    default_workspace_root: str
    open_browser_on_start: bool
    cad_extensions: list[str] = Field(default_factory=list)
    default_cad_extensions: list[str] = Field(default_factory=list)


class SettingsUpdateRequest(BaseModel):
    creo_open_mode: str = "executable"
    creo_executable: str | None = None
    workspace_root: str | None = None
    open_browser_on_start: bool | None = None
    cad_extensions: list[str] | None = None

    @field_validator("creo_open_mode")
    @classmethod
    def valid_open_mode(cls, value: str) -> str:
        key = (value or "executable").strip().lower()
        if key not in {"executable", "association"}:
            raise ValueError("Open mode must be 'executable' or 'association'.")
        return key

    @field_validator("cad_extensions")
    @classmethod
    def valid_cad_extensions(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        from creopdm.utils.classify import extra_cad_set

        return sorted(extra_cad_set(value))
