class RateLimitExceeded(Exception):
    """Raised when a configurable per-phone daily session limit is exceeded."""


class OutboundCallBlocked(Exception):
    """Raised when SIP UP spacing rules block a new outbound call (overlap or cooldown)."""

    def __init__(self, message: str, *, wait_seconds: int = 0) -> None:
        super().__init__(message)
        self.wait_seconds = max(0, int(wait_seconds))


class InvalidIvrTransition(ValueError):
    """Raised when a requested IVR logical step change is not allowed."""


class SipUpAriConfigurationError(RuntimeError):
    """Raised when required SIP UP media (ARI) environment configuration is missing or invalid."""


class SipUpConfigurationError(RuntimeError):
    """Raised when required SIP UP (``SIPUP_*`` SIP trunk) configuration is missing or invalid."""
