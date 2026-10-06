from pathlib import Path

import pytest

from hiyelx.config import ResourceDefinition, load_config
from hiyelx.drivers.dynamixel import (
    XL430_W250_T_MODEL,
    XL430Motor,
    register_dynamixel_xl430_motor,
)
from hiyelx.models import (
    DuplicateModelRegistrationError,
    InvalidModelSettingsError,
    ModelCreationError,
    ModelRegistry,
)
from hiyelx.resources import LifecycleState, ResourceIdentity
from tests.unit.drivers.dynamixel.fake_transport import FakeDynamixelTransport


def test_registration_is_explicit_and_performs_no_io(tmp_path: Path) -> None:
    transport = FakeDynamixelTransport()
    registry = ModelRegistry()

    assert registry.registered_model_names() == ()
    register_dynamixel_xl430_motor(registry, transport_factory=lambda _settings: transport)
    resource = registry.create(_definition(tmp_path, settings="{device: /dev/reference}"))

    assert registry.registered_model_names() == (XL430_W250_T_MODEL,)
    assert isinstance(resource, XL430Motor)
    assert resource.identity == ResourceIdentity("reference_motor")
    assert resource.state is LifecycleState.CREATED
    assert transport.events == []


def test_duplicate_registration_is_rejected() -> None:
    registry = ModelRegistry()
    register_dynamixel_xl430_motor(registry)

    with pytest.raises(DuplicateModelRegistrationError):
        register_dynamixel_xl430_motor(registry)


def test_default_sdk_backed_creation_remains_pre_start(tmp_path: Path) -> None:
    registry = ModelRegistry()
    register_dynamixel_xl430_motor(registry)

    resource = registry.create(_definition(tmp_path, settings="{device: /dev/not-opened}"))

    assert isinstance(resource, XL430Motor)
    assert resource.state is LifecycleState.CREATED


@pytest.mark.parametrize(
    "settings",
    [
        "{}",
        "{device: ' '}",
        "{device: /dev/reference, unexpected: true}",
        "{device: /dev/reference, motor_id: 253}",
        "{device: /dev/reference, baud_rate: 38400}",
    ],
)
def test_invalid_config_settings_are_rejected(tmp_path: Path, settings: str) -> None:
    registry = ModelRegistry()
    register_dynamixel_xl430_motor(
        registry, transport_factory=lambda _settings: FakeDynamixelTransport()
    )

    with pytest.raises(ModelCreationError) as caught:
        registry.create(_definition(tmp_path, settings=settings))

    assert isinstance(caught.value.__cause__, InvalidModelSettingsError)
    assert caught.value.__cause__.__cause__ is not None


def _definition(tmp_path: Path, *, settings: str) -> ResourceDefinition:
    path = tmp_path / "runtime.yaml"
    path.write_text(
        f"""\
schema_version: "1"
resources:
  - identity: reference_motor
    model: motor.dynamixel.xl430_w250_t
    settings: {settings}
""",
        encoding="utf-8",
    )
    return load_config(path).resources[0]
