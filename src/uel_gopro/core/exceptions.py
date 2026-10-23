class UelError(Exception):
    """Base exception for all UEL-GoPro errors."""
    pass


class CameraNotFoundError(UelError):
    """Raised when no GoPro camera can be located over the requested transport."""
    pass


class TransportError(UelError):
    """Raised on network, socket, or communication failures."""
    pass


class CommandError(UelError):
    """Raised when a camera command or setting mutation fails."""
    pass


class MediaError(UelError):
    """Raised on media list, download, or file processing errors."""
    pass


class StitchError(MediaError):
    """Raised during chapter concatenation failures."""
    pass


class TelemetryError(UelError):
    """Raised during GPMF parsing or export failures."""
    pass
