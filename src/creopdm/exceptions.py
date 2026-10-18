"""Explicit domain exceptions. The API layer maps these to HTTP responses."""

from __future__ import annotations

from typing import Any


def batch_failure(object_uuid: str, filename: str, exc: BaseException) -> dict[str, str]:
    """One batch-item error. Unexpected exceptions stay in ``failed`` instead of a 500."""
    if isinstance(exc, CreoPDMError):
        return {
            "uuid": object_uuid,
            "filename": filename,
            "code": exc.code,
            "message": exc.message,
        }
    return {
        "uuid": object_uuid,
        "filename": filename,
        "code": "APPLICATION_ERROR",
        "message": str(exc) or exc.__class__.__name__,
    }


class CreoPDMError(Exception):
    """Base application error. Never expose raw Python exceptions to the UI."""

    code = "APPLICATION_ERROR"
    http_status = 500

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_payload(self) -> dict[str, Any]:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "details": self.details,
            }
        }


class ProductNotFoundError(CreoPDMError):
    code = "PRODUCT_NOT_FOUND"
    http_status = 404


class ObjectNotFoundError(CreoPDMError):
    code = "OBJECT_NOT_FOUND"
    http_status = 404


class ObjectAlreadyCheckedOutError(CreoPDMError):
    code = "OBJECT_ALREADY_CHECKED_OUT"
    http_status = 409


class CheckoutOwnershipError(CreoPDMError):
    code = "CHECKOUT_OWNERSHIP"
    http_status = 403


class ReleasedObjectError(CreoPDMError):
    code = "OBJECT_NOT_IN_WORK"
    http_status = 409


class ReviseNotAllowedError(CreoPDMError):
    """Revise blocked by product state or policy."""

    code = "REVISE_NOT_ALLOWED"
    http_status = 409


class ReviseInvalidLifecycleError(CreoPDMError):
    """Only a Released file can be revised."""

    code = "REVISE_INVALID_LIFECYCLE"
    http_status = 409


class ReviseActiveCheckoutError(CreoPDMError):
    """A checkout would make the revise source ambiguous."""

    code = "REVISE_ACTIVE_CHECKOUT"
    http_status = 409


class ReviseOperationAlreadyCompletedError(CreoPDMError):
    """An operation id was reused for a different file."""

    code = "REVISE_OPERATION_ALREADY_COMPLETED"
    http_status = 409


class ReviseSourceNotFoundError(CreoPDMError):
    """The file has no current version to revise from."""

    code = "REVISE_SOURCE_NOT_FOUND"
    http_status = 404


class ReviseNextRevisionExistsError(CreoPDMError):
    """The revision that would come next is already used (history is linear)."""

    code = "REVISE_NEXT_REVISION_EXISTS"
    http_status = 409


class ReviseRevisionSchemeError(CreoPDMError):
    """The current revision does not fit the revision scheme."""

    code = "REVISE_REVISION_SCHEME_ERROR"
    http_status = 409


class BaselineNotFoundError(CreoPDMError):
    code = "BASELINE_NOT_FOUND"
    http_status = 404


class BaselineNameConflictError(CreoPDMError):
    code = "BASELINE_NAME_CONFLICT"
    http_status = 409


class BaselineImmutableError(CreoPDMError):
    """A finalized baseline's membership (or snapshot) can never be changed."""

    code = "BASELINE_IMMUTABLE"
    http_status = 409


class BaselineStructureNotIndexedError(CreoPDMError):
    """The product has assemblies or drawings but Where Used was never built: no structure to capture."""

    code = "BASELINE_STRUCTURE_NOT_INDEXED"
    http_status = 409


class BaselineValidationError(CreoPDMError):
    """The configuration failed validation: no baseline is created."""

    code = "BASELINE_VALIDATION_FAILED"
    http_status = 409


class BaselineReconstructionError(CreoPDMError):
    """Exact baseline content is unavailable or damaged. Nothing else is ever substituted."""

    code = "BASELINE_RECONSTRUCTION_FAILED"
    http_status = 409


class ProductHasBaselinesError(CreoPDMError):
    """A product that has baselines is deleted only by an administrator, with a warning."""

    code = "PRODUCT_HAS_BASELINES"
    http_status = 409


class BaselineEmptyError(CreoPDMError):
    """A product with no checked-in files has nothing to capture."""

    code = "BASELINE_EMPTY"
    http_status = 409


class BaselineReferencedError(CreoPDMError):
    """An exact version (or the history holding it) is kept by a baseline."""

    code = "VERSION_REFERENCED_BY_BASELINE"
    http_status = 409


class WorkspaceConflictError(CreoPDMError):
    code = "WORKSPACE_CONFLICT"
    http_status = 409


class ProductBusyError(CreoPDMError):
    """Another mutation (Add, check-in, Where Used index) still holds the product."""

    code = "PRODUCT_BUSY"
    http_status = 409


class RepositoryError(CreoPDMError):
    code = "REPOSITORY_ERROR"
    http_status = 500


class RemoteSyncError(CreoPDMError):
    code = "REMOTE_SYNC_ERROR"
    http_status = 502


class CreoUnavailableError(CreoPDMError):
    code = "CREO_UNAVAILABLE"
    http_status = 503


class DependencyError(CreoPDMError):
    code = "DEPENDENCY_ERROR"
    http_status = 400


class PathValidationError(CreoPDMError):
    code = "INVALID_PATH"
    http_status = 400


class DuplicateObjectError(CreoPDMError):
    code = "DUPLICATE_OBJECT"
    http_status = 409


class DuplicateProductError(CreoPDMError):
    code = "DUPLICATE_PRODUCT"
    http_status = 409


class ValidationAppError(CreoPDMError):
    code = "VALIDATION_ERROR"
    http_status = 400


class NotFoundError(CreoPDMError):
    code = "NOT_FOUND"
    http_status = 404


class PermissionDeniedError(CreoPDMError):
    code = "FORBIDDEN"
    http_status = 403


class ConfigurationError(CreoPDMError):
    code = "CONFIGURATION_ERROR"
    http_status = 500
