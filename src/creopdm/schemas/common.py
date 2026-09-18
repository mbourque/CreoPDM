"""Pydantic request/response models."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from creopdm.constants import APP_NAME, APP_VERSION, CREO_OPEN_MODES, CREO_VIEW_OPEN_MODES
from creopdm.utils.native_dialog import native_picker_available


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
    number: str | None = None
    description: str | None = None


class ProjectUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

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
    creo_release: str | None = None
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
    type_label: str = ""
    relative_path: str
    revision: str
    iteration: int
    display_revision: str
    creo_release: str | None = None
    lifecycle_state: str
    checkout_status: str = "Available"
    checkout_user: str | None = None
    checkout_machine: str | None = None
    checkout_since: datetime | None = None
    owned_by_me: bool = False
    modified_locally: bool = False
    can_checkout: bool = True
    can_checkin: bool = False
    in_workspace: bool = False
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
    object_id: str | None = None
    project_id: str | None = None
    relative_path: str | None = None
    launch: bool = True

    @model_validator(mode="after")
    def require_open_target(self) -> "CreoOpenRequest":
        object_id = (self.object_id or "").strip()
        project_id = (self.project_id or "").strip()
        relative_path = (self.relative_path or "").strip().replace("\\", "/")
        if object_id:
            self.object_id = object_id
            return self
        if project_id and relative_path:
            self.project_id = project_id
            self.relative_path = relative_path
            return self
        raise ValueError("Select a file to open.")


class CreoOpenResponse(BaseModel):
    filename: str
    path: str
    method: str
    working_directory: str
    creo_object: bool = False
    creo_release: str | None = None


class CreoStatusResponse(BaseModel):
    connector: str
    available: bool
    running: bool
    label: str


class ProjectStatusResponse(BaseModel):
    files: int
    cad_models: int = 0
    creo_parts: int
    assemblies: int
    drawings: int
    documents: int
    other: int
    checked_out: int = 0
    checked_out_by_me: int
    checked_out_by_others: int
    modified_locally: int
    out_of_date: int
    untracked: int


class ImportLocalRequest(BaseModel):
    paths: list[str] = Field(default_factory=list)
    folder: str | None = None
    comment: str | None = None
    base_folder: str | None = None


class WorkspaceWatchResponse(BaseModel):
    stamp: str
    pending_saves: int = 0
    new_files: int = 0


class WorkspacePickerResponse(BaseModel):
    workspace_root: str
    initial_directory: str
    selected: list[str] = Field(default_factory=list)
    cancelled: bool = False
    folder: str | None = None
    ignored_count: int = 0
    warning: str = ""
    native_picker: bool = Field(default_factory=native_picker_available)


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
    creo_view_open_mode: str
    creo_view_executable: str | None
    workspace_root: str
    default_workspace_root: str
    open_browser_on_start: bool
    cad_extensions: list[str] = Field(default_factory=list)
    default_cad_extensions: list[str] = Field(default_factory=list)
    cad_openable_extensions: list[str] = Field(default_factory=list)
    default_cad_openable_extensions: list[str] = Field(default_factory=list)
    cad_model_extensions: list[str] = Field(default_factory=list)
    default_cad_model_extensions: list[str] = Field(default_factory=list)
    cad_models_extensions: list[str] = Field(default_factory=list)
    default_cad_models_extensions: list[str] = Field(default_factory=list)
    document_extensions: list[str] = Field(default_factory=list)
    default_document_extensions: list[str] = Field(default_factory=list)
    type_labels: list[dict[str, str]] = Field(default_factory=list)
    ignore_patterns: list[str] = Field(default_factory=list)
    default_ignore_patterns: list[str] = Field(default_factory=list)
    database_url: str = ""
    default_database_url: str = ""
    port: int = 0


class SettingsUpdateRequest(BaseModel):
    creo_open_mode: str = "executable"
    creo_executable: str | None = None
    creo_view_open_mode: str | None = None
    creo_view_executable: str | None = None
    workspace_root: str | None = None
    open_browser_on_start: bool | None = None
    cad_extensions: list[str] | None = None
    cad_openable_extensions: list[str] | None = None
    cad_model_extensions: list[str] | None = None
    cad_models_extensions: list[str] | None = None
    document_extensions: list[str] | None = None
    type_labels: list[dict[str, str]] | None = None
    ignore_patterns: list[str] | None = None
    database_url: str | None = None
    port: int | None = None

    @field_validator("creo_open_mode")
    @classmethod
    def valid_open_mode(cls, value: str) -> str:
        key = (value or "executable").strip().lower()
        if key not in CREO_OPEN_MODES:
            raise ValueError("Open mode must be 'executable', 'association', 'embedded', or 'view'.")
        return key

    @field_validator("creo_view_open_mode")
    @classmethod
    def valid_view_open_mode(cls, value: str | None) -> str | None:
        if value is None:
            return None
        key = value.strip().lower()
        if key not in CREO_VIEW_OPEN_MODES:
            raise ValueError("Creo View open mode must be 'executable' or 'association'.")
        return key

    @field_validator("cad_extensions")
    @classmethod
    def valid_cad_extensions(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        from creopdm.utils.classify import extra_cad_set

        return sorted(extra_cad_set(value))

    @field_validator("cad_openable_extensions")
    @classmethod
    def valid_cad_openable_extensions(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        from creopdm.utils.classify import extra_cad_set

        return sorted(extra_cad_set(value))

    @field_validator("cad_model_extensions")
    @classmethod
    def valid_cad_model_extensions(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        from creopdm.utils.classify import unique_extensions

        return unique_extensions(value)

    @field_validator("cad_models_extensions")
    @classmethod
    def valid_cad_models_extensions(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        from creopdm.utils.classify import unique_extensions

        return unique_extensions(value)

    @field_validator("document_extensions")
    @classmethod
    def valid_document_extensions(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        from creopdm.utils.classify import unique_extensions

        return unique_extensions(value)

    @field_validator("type_labels")
    @classmethod
    def valid_type_labels(cls, value: list[dict[str, str]] | None) -> list[dict[str, str]] | None:
        if value is None:
            return None
        from creopdm.utils.classify import unique_type_labels

        return unique_type_labels(value)

    @field_validator("ignore_patterns")
    @classmethod
    def valid_ignore_patterns(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        from creopdm.utils.ignore import unique_ignore_patterns

        return unique_ignore_patterns(value)

    @field_validator("database_url")
    @classmethod
    def valid_database_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        if not text:
            return ""
        if "://" not in text:
            raise ValueError(
                "Database URL must look like sqlite:///path or postgresql+psycopg://user@host/db"
            )
        return text

    @field_validator("port")
    @classmethod
    def valid_port(cls, value: int | None) -> int | None:
        if value is None:
            return None
        if not 0 <= int(value) <= 65535:
            raise ValueError("Port must be 0 (automatic) or 1–65535.")
        return int(value)
