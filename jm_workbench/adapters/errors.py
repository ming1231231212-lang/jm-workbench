class LocalBrowserError(RuntimeError):
    """Local connection/login failure; never interpreted as a platform ban."""


class PlatformRisk(RuntimeError):
    """Platform restriction; stop all bindings on this platform."""


class Cancelled(RuntimeError):
    pass
