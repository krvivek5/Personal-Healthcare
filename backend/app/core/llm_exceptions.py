class LLMProviderError(Exception):
    """Base exception for all LLM provider errors."""


class LLMTimeoutError(LLMProviderError):
    """Raised when the provider times out."""


class LLMRateLimitError(LLMProviderError):
    """Raised when the provider rate limits requests (HTTP 429)."""


class LLMProvider5xxError(LLMProviderError):
    """Raised when the provider returns a 5xx server error."""


class LLMMalformedResponseError(LLMProviderError):
    """Raised when the provider response cannot be parsed or violates the schema."""


class LLMProviderRefusalError(LLMProviderError):
    """Raised when the provider refuses to answer due to safety or content filters."""


class LLMConfigurationError(ValueError):
    """Raised when LLM provider configuration is missing or invalid."""
