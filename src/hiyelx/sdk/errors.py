"""Typed public errors for HIYELX driver authoring helpers."""


class DriverSdkError(Exception):
    """Base class for driver authoring errors."""


class InvalidMotorDriverResultError(DriverSdkError):
    """Raised when a motor driver builder does not return a Motor."""

    def __init__(self, model_name: str, result_type: type[object]) -> None:
        self.model_name = model_name
        self.result_type = result_type
        super().__init__(
            f"motor driver {model_name!r} returned {result_type.__name__}, not Motor"
        )


class MotorDriverScaffoldError(DriverSdkError):
    """Base class for motor-driver scaffold errors."""


class InvalidScaffoldPackageNameError(MotorDriverScaffoldError):
    """Raised when a scaffold package name is not a safe Python identifier."""

    def __init__(self, package_name: str) -> None:
        self.package_name = package_name
        super().__init__("scaffold package name must be a lowercase Python identifier")


class InvalidScaffoldModelNameError(MotorDriverScaffoldError):
    """Raised when a scaffold model name is empty or unsafe to render."""

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        super().__init__("scaffold model name must be a non-empty single-line value")


class ScaffoldTargetExistsError(MotorDriverScaffoldError):
    """Raised when scaffold generation would overwrite an existing path."""

    def __init__(self) -> None:
        super().__init__("scaffold target already exists")


class ScaffoldParentMissingError(MotorDriverScaffoldError):
    """Raised when the target parent directory does not exist."""

    def __init__(self) -> None:
        super().__init__("scaffold target parent does not exist")
