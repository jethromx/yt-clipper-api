"""Domain-level exceptions."""


class DomainError(Exception):
    """Base class for domain errors."""


class InvalidClipRangeError(DomainError):
    """Raised when a requested clip range is invalid."""


class InvalidVideoUrlError(DomainError):
    """Raised when a video URL cannot be accepted."""


class CaptionNotAvailableError(DomainError):
    """Raised when a job has no metadata to generate a caption from."""


class CaptionGeneratorUnavailableError(DomainError):
    """Raised when no AI caption generator is configured."""


class CaptionGenerationError(DomainError):
    """Raised when the AI provider fails to generate a caption."""


class EmptySearchQueryError(DomainError):
    """Raised when a search query is empty."""


class EmptyBatchError(DomainError):
    """Raised when a batch download request has no URLs."""


class BatchTooLargeError(DomainError):
    """Raised when a batch download request exceeds the allowed size."""


class TrendsUnavailableError(DomainError):
    """Raised when no YouTube API key is configured for trends."""


class TrendsError(DomainError):
    """Raised when the YouTube trends API call fails."""
