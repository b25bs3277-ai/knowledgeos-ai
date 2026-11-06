"""Typed exception hierarchy. Every error carries a category and a user-safe message."""
from __future__ import annotations

from typing import Optional


class KnowledgeOSError(Exception):
    """Base class. `user_message` is safe to show in the UI (no paths/secrets)."""

    category = "internal"

    def __init__(self, message: str, *, user_message: Optional[str] = None) -> None:
        super().__init__(message)
        self.user_message = user_message or message


class ConfigurationError(KnowledgeOSError):
    category = "configuration"


class DependencyError(KnowledgeOSError):
    category = "dependency"


class ValidationError(KnowledgeOSError):
    category = "validation"


class SecurityError(KnowledgeOSError):
    category = "security"


class UnsupportedFileTypeError(ValidationError):
    category = "unsupported_file"


class FileTooLargeError(ValidationError):
    category = "file_too_large"


class DuplicateDocumentError(ValidationError):
    category = "duplicate"

    def __init__(self, message: str, *, existing_doc_id: str, user_message: Optional[str] = None) -> None:
        super().__init__(message, user_message=user_message)
        self.existing_doc_id = existing_doc_id


class ExtractionError(KnowledgeOSError):
    category = "extraction"


class EmptyDocumentError(ExtractionError):
    category = "empty_document"


class EmbeddingError(KnowledgeOSError):
    category = "embedding"


class IndexError_(KnowledgeOSError):
    """Vector/keyword index failure (trailing underscore avoids shadowing builtin IndexError)."""

    category = "index"


class RetrievalError(KnowledgeOSError):
    category = "retrieval"


class ProviderUnavailableError(KnowledgeOSError):
    category = "provider_unavailable"


class GenerationError(KnowledgeOSError):
    category = "generation"


class GenerationTimeoutError(GenerationError):
    category = "generation_timeout"


class NotFoundError(KnowledgeOSError):
    category = "not_found"


def safe_user_message(exc: BaseException) -> str:
    """Return a message safe for display; unknown exceptions get a generic text."""
    if isinstance(exc, KnowledgeOSError):
        return exc.user_message
    return f"An unexpected {type(exc).__name__} occurred. See System Diagnostics → Logs."


def error_category(exc: BaseException) -> str:
    return exc.category if isinstance(exc, KnowledgeOSError) else "unexpected"

