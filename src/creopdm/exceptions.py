"""Explicit domain exceptions. The API layer maps these to HTTP responses."""

from __future__ import annotations

from typing import Any


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


class ProjectNotFoundError(CreoPDMError):
    code = "PROJECT_NOT_FOUND"
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


class WorkspaceConflictError(CreoPDMError):
    code = "WORKSPACE_CONFLICT"
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


class DuplicateProjectError(CreoPDMError):
    code = "DUPLICATE_PROJECT"
    http_status = 409


class ValidationAppError(CreoPDMError):
    code = "VALIDATION_ERROR"
    http_status = 400


class ConfigurationError(CreoPDMError):
    code = "CONFIGURATION_ERROR"
    http_status = 500
