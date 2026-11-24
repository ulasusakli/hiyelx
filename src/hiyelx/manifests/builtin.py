"""Built-in canonical manifest catalog for HIYELX Runtime components and drivers."""

from __future__ import annotations

from hiyelx.core.capabilities import ComponentCapability
from hiyelx.core.types import ComponentCategory
from hiyelx.manifests.models import (
    ComponentManifest,
    InterfaceDirection,
    ManifestConfigurationSpec,
    ManifestInterface,
    ManifestRuntimeRequirement,
    ManifestType,
)


def builtin_manifests() -> tuple[ComponentManifest, ...]:
    """Return the immutable sorted catalog of built-in HIYELX manifests."""
    catalog = (
        ComponentManifest(
            manifest_version="1.0",
            id="hiyelx.camera.mock",
            model="mock.camera",
            name="Mock RGB Camera",
            version="0.2.0a1",
            type=ManifestType.COMPONENT,
            category=ComponentCategory.VISION,
            description="Hardware-free deterministic mock RGB camera component.",
            runtime=ManifestRuntimeRequirement(min_version="0.2.0a1"),
            capabilities=(
                ComponentCapability.CAN_STREAM_FRAMES,
                ComponentCapability.HAS_RGB_FRAME,
            ),
            interfaces=(
                ManifestInterface(
                    name="frame",
                    type="camera.frame",
                    direction=InterfaceDirection.OUTPUT,
                ),
            ),
            configuration=ManifestConfigurationSpec(
                schema="settings.schema.json",
                defaults={"width": 640, "height": 480, "fps": 30},
            ),
        ),
        ComponentManifest(
            manifest_version="1.0",
            id="hiyelx.encoder.mock",
            model="mock.encoder",
            name="Mock Wheel Encoder",
            version="0.2.0a1",
            type=ManifestType.COMPONENT,
            category=ComponentCategory.FEEDBACK,
            description="Hardware-free deterministic quadrature encoder feedback component.",
            runtime=ManifestRuntimeRequirement(min_version="0.2.0a1"),
            capabilities=(
                ComponentCapability.HAS_ENCODER_TICKS,
                ComponentCapability.HAS_ANGULAR_POSITION,
                ComponentCapability.HAS_ANGULAR_VELOCITY,
            ),
            interfaces=(
                ManifestInterface(
                    name="state",
                    type="encoder.state",
                    direction=InterfaceDirection.OUTPUT,
                ),
            ),
            configuration=ManifestConfigurationSpec(
                schema="settings.schema.json",
                defaults={"resolution": 4096},
            ),
        ),
        ComponentManifest(
            manifest_version="1.0",
            id="hiyelx.imu.mock",
            model="mock.imu",
            name="Mock 9-DOF IMU",
            version="0.2.0a1",
            type=ManifestType.COMPONENT,
            category=ComponentCategory.SPATIAL,
            description="Hardware-free deterministic inertial measurement component.",
            runtime=ManifestRuntimeRequirement(min_version="0.2.0a1"),
            capabilities=(
                ComponentCapability.HAS_ORIENTATION_QUATERNION,
                ComponentCapability.HAS_ANGULAR_VELOCITY_3D,
                ComponentCapability.HAS_LINEAR_ACCELERATION_3D,
            ),
            interfaces=(
                ManifestInterface(
                    name="imu",
                    type="imu.measurement",
                    direction=InterfaceDirection.OUTPUT,
                ),
            ),
            configuration=ManifestConfigurationSpec(
                schema="settings.schema.json",
                defaults={"sample_rate_hz": 100.0},
            ),
        ),
        ComponentManifest(
            manifest_version="1.0",
            id="hiyelx.motor.dynamixel.xl430",
            model="motor.dynamixel.xl430",
            name="DYNAMIXEL XL430-W250-T Motor Driver",
            version="0.2.0a1",
            type=ManifestType.DRIVER,
            category=ComponentCategory.ACTUATOR,
            description=(
                "Reference Protocol 2.0 serial motor driver (opt-in physical bench track; "
                "software readiness only, not physical acceptance)."
            ),
            runtime=ManifestRuntimeRequirement(min_version="0.1.0"),
            capabilities=(
                ComponentCapability.CAN_SET_VELOCITY,
                ComponentCapability.HAS_ANGULAR_POSITION,
                ComponentCapability.HAS_ANGULAR_VELOCITY,
            ),
            interfaces=(
                ManifestInterface(
                    name="command",
                    type="motor.command",
                    direction=InterfaceDirection.INPUT,
                ),
                ManifestInterface(
                    name="state",
                    type="motor.state",
                    direction=InterfaceDirection.OUTPUT,
                ),
            ),
            configuration=ManifestConfigurationSpec(
                schema="settings.schema.json",
                defaults={"port": "/dev/ttyUSB0", "baudrate": 57600, "motor_id": 1},
            ),
            scaffold_command=(
                "hiyelx scaffold motor-driver ./acme-driver "
                "--package-name acme_motor_driver "
                "--model-name motor.acme.reference"
            ),
        ),
        ComponentManifest(
            manifest_version="1.0",
            id="hiyelx.motor.mock",
            model="mock.motor",
            name="Mock Drive Motor",
            version="0.2.0a1",
            type=ManifestType.COMPONENT,
            category=ComponentCategory.ACTUATOR,
            description="Hardware-free canonical mock actuator component for RobotConfig v2.",
            runtime=ManifestRuntimeRequirement(min_version="0.2.0a1"),
            capabilities=(
                ComponentCapability.CAN_SET_VELOCITY,
                ComponentCapability.HAS_ANGULAR_POSITION,
                ComponentCapability.HAS_ANGULAR_VELOCITY,
            ),
            interfaces=(
                ManifestInterface(
                    name="command",
                    type="motor.command",
                    direction=InterfaceDirection.INPUT,
                ),
                ManifestInterface(
                    name="state",
                    type="motor.state",
                    direction=InterfaceDirection.OUTPUT,
                ),
            ),
            configuration=ManifestConfigurationSpec(
                schema="settings.schema.json",
                defaults={"max_rpm": 300.0},
            ),
        ),
        ComponentManifest(
            manifest_version="1.0",
            id="hiyelx.motor.simulated",
            model="motor.simulated",
            name="Deterministic Simulated Motor",
            version="0.2.0a1",
            type=ManifestType.DRIVER,
            category=ComponentCategory.ACTUATOR,
            description="Explicit-time deterministic simulated motor driver.",
            runtime=ManifestRuntimeRequirement(min_version="0.1.0"),
            capabilities=(
                ComponentCapability.CAN_SET_VELOCITY,
                ComponentCapability.HAS_ANGULAR_POSITION,
                ComponentCapability.HAS_ANGULAR_VELOCITY,
            ),
            interfaces=(
                ManifestInterface(
                    name="command",
                    type="motor.command",
                    direction=InterfaceDirection.INPUT,
                ),
                ManifestInterface(
                    name="state",
                    type="motor.state",
                    direction=InterfaceDirection.OUTPUT,
                ),
            ),
            configuration=ManifestConfigurationSpec(
                schema="settings.schema.json",
                defaults={},
            ),
            scaffold_command=(
                "hiyelx scaffold motor-driver ./acme-driver "
                "--package-name acme_motor_driver "
                "--model-name motor.acme.reference"
            ),
        ),
    )
    return tuple(sorted(catalog, key=lambda item: item.id))
