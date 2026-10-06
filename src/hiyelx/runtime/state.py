"""Runtime Manager lifecycle contracts."""

from enum import Enum


class RuntimeManagerState(Enum):
    """Explicit lifecycle state of one Runtime Manager instance."""

    NEW = "new"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"


class RuntimeManagerOperation(Enum):
    """Lifecycle operations guarded by Runtime Manager state."""

    START = "start"
    SHUTDOWN = "shutdown"
