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


class UtilitiesDiskUsage(BaseModel):
    """kind=volume: free/used for the whole disk; kind=directory: size of that folder only."""

    label: str
    path: str
    kind: str = "directory"  # volume | directory
    exists: bool = True
    total_bytes: int | None = None
    used_bytes: int | None = None
    free_bytes: int | None = None
    total_label: str = "—"
    used_label: str = "—"
    free_label: str = "—"
    free_percent: float | None = None
    error: str | None = None


class UtilitiesProbe(BaseModel):
    status: str = "ok"
    detail: str = ""


class UtilitiesCpuUsage(BaseModel):
    """Host CPU load for Administration → Utilities → Health."""

    percent: float | None = None
    percent_label: str = "—"
    status: str = "ok"  # ok | busy | hot (display only; does not degrade overall health)
    logical_cpus: int | None = None
    load_1: float | None = None
    load_5: float | None = None
    load_15: float | None = None
    load_label: str = "—"
    error: str | None = None


class UtilitiesIoUsage(BaseModel):
    """Host I/O wait, disk, and network throughput for Administration → Utilities → Health."""

    iowait_percent: float | None = None
    iowait_label: str = "—"
    status: str = "ok"  # ok | busy | hot from iowait (display only)
    read_bytes_per_sec: int | None = None
    write_bytes_per_sec: int | None = None
    read_label: str = "—"
    write_label: str = "—"
    net_rx_bytes_per_sec: int | None = None
    net_tx_bytes_per_sec: int | None = None
    net_rx_label: str = "—"
    net_tx_label: str = "—"
    error: str | None = None


class UtilitiesProductIssue(BaseModel):
    """One lightweight product/vault problem found by Utilities → Health."""

    code: str
    product_name: str = ""
    product_uuid: str = ""
    detail: str = ""


class UtilitiesProductHealth(BaseModel):
    """Read-only product vault / tip consistency for Utilities → Health."""

    status: str = "ok"  # ok | degraded
    checked: int = 0
    issue_count: int = 0
    issues: list[UtilitiesProductIssue] = Field(default_factory=list)
    summary: str = "No products to check."


class UtilitiesStatusResponse(BaseModel):
    """Administration → Utilities snapshot (health, disk, counts)."""

    status: str = "ok"
    app_name: str = APP_NAME
    app_version: str = APP_VERSION
    server_time: str = ""
    hostname: str = ""
    platform: str = ""
    python_version: str = ""
    auth_enabled: bool = True
    site_availability: str = "available"
    database: UtilitiesProbe = Field(default_factory=UtilitiesProbe)
    database_dialect: str = ""
    database_url: str = ""
    git: UtilitiesProbe = Field(default_factory=UtilitiesProbe)
    git_executable: str = "git"
    git_version: str = ""
    cpu: UtilitiesCpuUsage = Field(default_factory=UtilitiesCpuUsage)
    io: UtilitiesIoUsage = Field(default_factory=UtilitiesIoUsage)
    products: UtilitiesProductHealth = Field(default_factory=UtilitiesProductHealth)
    disk: list[UtilitiesDiskUsage] = Field(default_factory=list)
    product_count: int = 0
    user_count: int = 0
    active_checkout_count: int = 0
    data_dir: str = ""
    vaults_dir: str = ""
    logs_dir: str = ""
    agent_base_url: str = "http://127.0.0.1:8766"


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    error: ErrorBody


class ProductCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    number: str | None = Field(default=None, max_length=25)
    description: str | None = Field(default=None, max_length=256)
    # Vault folder under vaults/. Blank → server uses the product UUID.
    vault_folder: str | None = Field(default=None, max_length=200)


class ProductUpdateRequest(BaseModel):
    """Rename / metadata only. vault_folder is omitted and forbidden (immutable)."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    number: str | None = Field(default=None, max_length=25)
    description: str | None = Field(default=None, max_length=256)

class ForgetProductRequest(BaseModel):
    confirm_name: str = Field(min_length=1, max_length=255)


class ForgetProductResponse(BaseModel):
    uuid: str
    name: str
    repository_path: str
    warning: str = ""


class ProductResponse(BaseModel):
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
    state: str = "IN_WORK"
    read_only: bool = False
    allows_mutation: bool = True


class ProductWatchResponse(BaseModel):
    watching: bool
    can_watch: bool
    email_notifications_enabled: bool
    reason: str | None = None


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
    product_uuid: str
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
    product_id: str | None = None
    relative_path: str | None = None
    launch: bool = True
    # Bulk checkout→cache fills each selected file once; dependencies would re-download
    # the same parts. Real Open still defaults to True so Retrieve has neighbors.
    include_dependencies: bool = True

    @model_validator(mode="after")
    def require_open_target(self) -> "CreoOpenRequest":
        object_id = (self.object_id or "").strip()
        product_id = (self.product_id or "").strip()
        relative_path = (self.relative_path or "").strip().replace("\\", "/")
        if object_id:
            self.object_id = object_id
            return self
        if product_id and relative_path:
            self.product_id = product_id
            self.relative_path = relative_path
            return self
        raise ValueError("Select a file to open.")


class CreoOpenDependency(BaseModel):
    object_id: str | None = None
    product_id: str | None = None
    relative_path: str | None = None
    filename: str | None = None
    disk_name: str | None = None
    content_hash: str | None = None
    file_size: int | None = None
    prefer_local: bool = False


class CreoOpenResponse(BaseModel):
    filename: str
    path: str
    method: str
    working_directory: str
    disk_name: str | None = None
    object_id: str | None = None
    product_id: str | None = None
    relative_path: str | None = None
    content_hash: str | None = None
    file_size: int | None = None
    prefer_local: bool = False
    replace_newer: bool = True
    creo_object: bool = False
    open_with_creo: bool = False
    requires_agent_cache: bool = False
    creo_release: str | None = None
    url: str | None = None
    dependencies: list[CreoOpenDependency] = Field(default_factory=list)


class CreoStatusResponse(BaseModel):
    connector: str
    available: bool
    running: bool
    label: str


class ProductStatusResponse(BaseModel):
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
    # Full picker count when this request is one chunk of a larger Add.
    batch_total: int | None = None
    # Shared across upload chunks so Audit shows one Object added row.
    import_batch_id: str | None = None
    base_folder: str | None = None
    # When true (default), vault paths include the chosen folder name.
    keep_root_folder: bool = True
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


class ProductExportRequest(BaseModel):
    """Empty lists = entire product; otherwise selected files and/or folders."""

    object_ids: list[str] = Field(default_factory=list)
    folder_paths: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def normalize_export_targets(self) -> "ProductExportRequest":
        ids = [str(item).strip() for item in (self.object_ids or []) if str(item or "").strip()]
        folders = [
            str(item).replace("\\", "/").strip().strip("/")
            for item in (self.folder_paths or [])
            if str(item or "").strip()
        ]
        self.object_ids = list(dict.fromkeys(ids))
        self.folder_paths = list(dict.fromkeys(folders))
        return self


class BatchRemoveRequest(BaseModel):
    """Remove by object id and/or whole vault folder paths (descendants included)."""

    object_ids: list[str] = Field(default_factory=list)
    folder_paths: list[str] = Field(default_factory=list)
    product_id: str | None = None

    @model_validator(mode="after")
    def require_remove_target(self) -> "BatchRemoveRequest":
        ids = [str(item).strip() for item in (self.object_ids or []) if str(item or "").strip()]
        folders = [
            str(item).replace("\\", "/").strip().strip("/")
            for item in (self.folder_paths or [])
            if str(item or "").strip()
        ]
        product_id = (self.product_id or "").strip() or None
        self.object_ids = ids
        self.folder_paths = folders
        self.product_id = product_id
        if not ids and not folders:
            raise ValueError("Choose files or a folder to remove.")
        if folders and not product_id and not ids:
            raise ValueError("Choose a product before removing folders.")
        return self


class AgentCacheManifestItem(BaseModel):
    """Vault file identity for agent-cache hit detection."""

    object_id: str
    filename: str
    disk_name: str
    relative_path: str = ""
    content_hash: str
    file_size: int = 0


class AgentCacheManifestResponse(BaseModel):
    product_id: str
    items: list[AgentCacheManifestItem] = Field(default_factory=list)


class PurgeWorkspacePathsRequest(BaseModel):
    relative_paths: list[str] = Field(min_length=1)


class PurgeFloorItem(BaseModel):
    """Vault save floor for one product Creo model (agent deletes local saves < min_keep)."""

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
    workspace_poll_idle_minutes: int = 10
    site_availability: str = "available"
    site_unavailable_message: str = ""
    default_site_unavailable_message: str = ""


class SettingsUpdateRequest(BaseModel):
    # Partial updates: omit a field (or leave None) to keep the saved value.
    creo_open_mode: str | None = None
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
    workspace_poll_idle_minutes: int | None = None
    site_availability: str | None = None
    site_unavailable_message: str | None = None

    @field_validator("creo_open_mode")
    @classmethod
    def valid_open_mode(cls, value: str | None) -> str | None:
        if value is None:
            return None
        key = (value or "association").strip().lower()
        if key not in CREO_OPEN_MODES:
            raise ValueError("Open mode must be 'association' or 'embedded'.")
        return key

    @field_validator("site_availability")
    @classmethod
    def valid_site_availability(cls, value: str | None) -> str | None:
        if value is None:
            return None
        from creopdm.site_availability import (
            SITE_AVAILABLE,
            SITE_UNAVAILABLE,
            normalize_site_availability,
        )

        key = normalize_site_availability(value)
        if key not in {SITE_AVAILABLE, SITE_UNAVAILABLE}:
            raise ValueError("Availability must be 'available' or 'unavailable'.")
        return key

    @field_validator("site_unavailable_message")
    @classmethod
    def valid_site_unavailable_message(cls, value: str | None) -> str | None:
        if value is None:
            return None
        from creopdm.site_availability import normalize_site_unavailable_message

        return normalize_site_unavailable_message(value)

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

    @field_validator("workspace_poll_idle_minutes")
    @classmethod
    def valid_workspace_poll_idle(cls, value: int | None) -> int | None:
        if value is None:
            return None
        minutes = int(value)
        if minutes < 0:
            return 0
        if minutes > 24 * 60:
            return 24 * 60
        return minutes


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

    product_id: str
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


class ZipImportJobResponse(BaseModel):
    """Progress for Add ▾ → Compressed data… (zip upload / extract / import)."""

    job_id: str
    product_id: str
    state: str = "queued"
    phase: str = "queued"
    message: str = ""
    bytes_total: int = 0
    bytes_done: int = 0
    files_total: int = 0
    files_done: int = 0
    error: str | None = None
    done: bool = False
    started_at: float | None = None
    finished_at: float | None = None
