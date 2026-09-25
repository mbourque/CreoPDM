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
    number: str | None = Field(default=None, max_length=25)
    description: str | None = Field(default=None, max_length=256)
    # Vault folder under vaults/. Blank → server uses the project UUID.
    vault_folder: str | None = Field(default=None, max_length=200)


class ProjectUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    number: str | None = Field(default=None, max_length=25)
    description: str | None = Field(default=None, max_length=256)

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
    vault_folder: str
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


class WorkspaceContentResponse(BaseModel):
    ok: bool = True
    object_id: str
    filename: str
    path: str
    bytes_written: int = 0


class ObjectResponse(BaseModel):
    uuid: str
    project_uuid: str
    number: str | None
    name: str
    filename: str
    extension: str
    object_type: str
    type_label: str = ""
    type_icon: str = ""
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
    # Bulk checkout→cache fills each selected file once; companions would re-download
    # the same parts. Real Open still defaults to True so Retrieve has neighbors.
    include_companions: bool = True

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


class CreoOpenCompanion(BaseModel):
    object_id: str | None = None
    project_id: str | None = None
    relative_path: str | None = None
    filename: str | None = None
    disk_name: str | None = None


class CreoOpenResponse(BaseModel):
    filename: str
    path: str
    method: str
    working_directory: str
    disk_name: str | None = None
    object_id: str | None = None
    project_id: str | None = None
    relative_path: str | None = None
    creo_object: bool = False
    open_with_creo: bool = False
    requires_agent_cache: bool = False
    creo_release: str | None = None
    url: str | None = None
    companions: list[CreoOpenCompanion] = Field(default_factory=list)


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
    folders: list[str] = Field(default_factory=list)
    recursive: bool = True
    comment: str | None = None
    base_folder: str | None = None
    # Files view location — imported paths land under this vault folder.
    parent_folder: str = ""


class CreateFolderRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    parent_folder: str = ""
    comment: str | None = None


class CreateFolderResponse(BaseModel):
    path: str
    name: str


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
    folders: list[str] = Field(default_factory=list)
    ignored_count: int = 0
    warning: str = ""
    native_picker: bool = Field(default_factory=native_picker_available)
    ignore_patterns: list[str] = Field(default_factory=list)
    import_extensions: list[str] = Field(default_factory=list)


class FolderPickResponse(BaseModel):
    path: str | None = None
    initial_directory: str


class BatchObjectRequest(BaseModel):
    object_ids: list[str] = Field(min_length=1)


class AgentCacheManifestItem(BaseModel):
    """Vault file identity for agent-cache hit detection."""

    object_id: str
    filename: str
    disk_name: str
    content_hash: str
    file_size: int = 0


class AgentCacheManifestResponse(BaseModel):
    project_id: str
    items: list[AgentCacheManifestItem] = Field(default_factory=list)


class PurgeWorkspacePathsRequest(BaseModel):
    relative_paths: list[str] = Field(min_length=1)


class PurgeFloorItem(BaseModel):
    """Vault save floor for one project Creo model (agent deletes local saves < min_keep)."""

    logical_path: str
    min_keep: int
    filename: str = ""
    object_id: str = ""


class PurgeFloorsResponse(BaseModel):
    floors: list[PurgeFloorItem] = Field(default_factory=list)
    model_extensions: list[str] = Field(default_factory=list)


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
    where_used_index: str | None = None  # "started" when background index kicked off


class SettingsResponse(BaseModel):
    creo_open_mode: str
    creo_executable: str | None
    creo_view_open_mode: str
    creo_view_executable: str | None
    creo_js_library: str | None = None
    creo_js_library_resolved: str | None = None
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
    purgeable_extensions: list[str] = Field(default_factory=list)
    default_purgeable_extensions: list[str] = Field(default_factory=list)
    type_labels: list[dict[str, str]] = Field(default_factory=list)
    ignore_patterns: list[str] = Field(default_factory=list)
    default_ignore_patterns: list[str] = Field(default_factory=list)
    database_url: str = ""
    default_database_url: str = ""
    port: int = 0
    agent_base_url: str = "http://127.0.0.1:8766"
    workspace_poll_interval_ms: int = 5000


class SettingsUpdateRequest(BaseModel):
    creo_open_mode: str = "association"
    creo_executable: str | None = None
    creo_view_open_mode: str | None = None
    creo_view_executable: str | None = None
    creo_js_library: str | None = None
    workspace_root: str | None = None
    open_browser_on_start: bool | None = None
    cad_extensions: list[str] | None = None
    cad_openable_extensions: list[str] | None = None
    cad_model_extensions: list[str] | None = None
    cad_models_extensions: list[str] | None = None
    document_extensions: list[str] | None = None
    purgeable_extensions: list[str] | None = None
    type_labels: list[dict[str, str]] | None = None
    ignore_patterns: list[str] | None = None
    database_url: str | None = None
    port: int | None = None
    agent_base_url: str | None = None
    workspace_poll_interval_ms: int | None = None

    @field_validator("creo_open_mode")
    @classmethod
    def valid_open_mode(cls, value: str) -> str:
        key = (value or "association").strip().lower()
        if key not in CREO_OPEN_MODES:
            raise ValueError("Open mode must be 'association' or 'embedded'.")
        return key

    @field_validator("creo_view_open_mode")
    @classmethod
    def valid_view_open_mode(cls, value: str | None) -> str | None:
        if value is None:
            return None
        key = value.strip().lower()
        if key not in CREO_VIEW_OPEN_MODES:
            raise ValueError("Creo View open mode must be 'association'.")
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

    @field_validator("purgeable_extensions")
    @classmethod
    def valid_purgeable_extensions(cls, value: list[str] | None) -> list[str] | None:
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

    @field_validator("agent_base_url")
    @classmethod
    def valid_agent_base_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip().rstrip("/")
        if not text:
            return "http://127.0.0.1:8766"
        if "://" not in text:
            raise ValueError("Agent base URL must include a scheme, e.g. http://127.0.0.1:8766")
        return text

    @field_validator("workspace_poll_interval_ms")
    @classmethod
    def valid_workspace_poll(cls, value: int | None) -> int | None:
        if value is None:
            return None
        ms = int(value)
        if ms < 500:
            return 500
        if ms > 120_000:
            return 120_000
        return ms


class CreoParamPayload(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    value: str | None = None
    data_type: str = "STRING"
    units: str | None = None
    description: str | None = None
    is_designated: bool = False


class CreoDependencyPayload(BaseModel):
    filename: str = Field(min_length=1)
    quantity: float = 1.0
    dependency_type: str = "ASSEMBLY_MEMBER"


class CreoBomNode(BaseModel):
    filename: str = ""
    quantity: float = 1.0
    dependency_type: str = "ASSEMBLY_MEMBER"
    resolved: bool = False
    object_id: str | None = None
    children: list["CreoBomNode"] = Field(default_factory=list)


class CreoMetadataRequest(BaseModel):
    version_id: str | None = None
    identity: dict[str, object] | None = None
    parameters: list[CreoParamPayload] = Field(default_factory=list)
    materials: dict[str, object] | None = None
    dependencies: list[CreoDependencyPayload] = Field(default_factory=list)
    bom: list[CreoBomNode] | dict[str, object] | None = None
    units: dict[str, object] | None = None
    mass: dict[str, object] | None = None
    family_table: dict[str, object] | None = None
    features: list[dict[str, object]] | None = None


class CreoMetadataResponse(BaseModel):
    object_id: str
    version_id: str | None = None
    identity: dict[str, object] | None = None
    parameters: list[CreoParamPayload] = Field(default_factory=list)
    materials: dict[str, object] | None = None
    dependencies: list[CreoDependencyPayload] = Field(default_factory=list)
    bom: list[object] | dict[str, object] | None = None
    units: dict[str, object] | None = None
    mass: dict[str, object] | None = None
    family_table: dict[str, object] | None = None
    features: list[dict[str, object]] | None = None
    captured: bool = False


class WhereUsedItem(BaseModel):
    object_id: str
    filename: str
    relative_path: str
    display_revision: str
    quantity: float = 1.0
    dependency_type: str = "ASSEMBLY_MEMBER"
    object_type: str = ""
    type_label: str = ""


class WhereUsedResponse(BaseModel):
    object_id: str
    items: list[WhereUsedItem] = Field(default_factory=list)
    # Populated only when GET …/where-used?debug=1
    debug: dict[str, object] | None = None


class RebuildWhereUsedResponse(BaseModel):
    """Chunked vault → Dependency index so Where Used is a fast SQL lookup."""

    parents_total: int = 0
    parents_processed: int = 0
    next_offset: int = 0
    done: bool = False
    edges_added: int = 0
    edges_existing: int = 0
    parents_missing_vault: int = 0
    parents_scanned: list[str] = Field(default_factory=list)


class WhereUsedIndexJobResponse(BaseModel):
    """Background Where Used vault index job status."""

    project_id: str
    state: str = "idle"
    parents_total: int = 0
    parents_done: int = 0
    edges_added: int = 0
    edges_existing: int = 0
    parents_missing_vault: int = 0
    error: str | None = None
    done: bool = False
    started_at: float | None = None
    finished_at: float | None = None
