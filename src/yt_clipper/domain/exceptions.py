"""Domain-level exceptions."""


class DomainError(Exception):
    """Base class for domain errors."""


class InvalidClipRangeError(DomainError):
    """Raised when a requested clip range is invalid."""


class InvalidVideoUrlError(DomainError):
    """Raised when a video URL cannot be accepted."""
