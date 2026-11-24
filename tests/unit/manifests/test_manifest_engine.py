from pathlib import Path

import pytest

from hiyelx import __version__
from hiyelx.core.capabilities import ComponentCapability
from hiyelx.core.types import ComponentCategory
from hiyelx.manifests import (
    CompatibilityStatus,
    ComponentManifest,
    ManifestConfigurationSpec,
    ManifestDependency,
    ManifestRuntimeRequirement,
    ManifestType,
    ManifestValidationError,
    UnsupportedManifestVersionError,
    builtin_manifests,
    check_manifest_compatibility,
    load_manifest_file,
    load_manifest_from_str,
    parse_version_key,
)


def test_builtin_catalog_is_sorted_and_compatible_with_current_runtime() -> None:
    catalog = builtin_manifests()
    ids = tuple(item.id for item in catalog)
    assert ids == tuple(sorted(ids))
    assert "hiyelx.motor.dynamixel.xl430" in ids
    assert "hiyelx.motor.mock" in ids
    assert "hiyelx.encoder.mock" in ids
    assert "hiyelx.imu.mock" in ids
    assert "hiyelx.camera.mock" in ids

    by_id = {item.id: item for item in catalog}
    for manifest in catalog:
        report = check_manifest_compatibility(
            manifest,
            runtime_version=__version__,
            catalog=by_id,
        )
        assert report.compatible is True
        assert report.status is CompatibilityStatus.COMPATIBLE
        assert report.issues == ()


def test_load_manifest_from_yaml_and_file_round_trip(tmp_path: Path) -> None:
    yaml_text = """
manifest_version: "1.0"
id: acme.motor.ec
model: motor.acme.ec
name: ACME EC Motor Driver
version: "0.1.0"
type: driver
category: actuator
runtime:
  min_version: "0.1.0"
capabilities:
  - can_set_velocity
  - has_angular_position
interfaces:
  - name: command
    type: motor.command
    direction: input
  - name: state
    type: motor.state
    direction: output
configuration:
  schema: settings.schema.json
  defaults:
    max_rpm: 200
"""
    manifest_file = tmp_path / "hiyelx.manifest.yaml"
    manifest_file.write_text(yaml_text, encoding="utf-8")

    loaded = load_manifest_file(manifest_file)
    assert loaded.id == "acme.motor.ec"
    assert loaded.category is ComponentCategory.ACTUATOR
    assert loaded.capabilities == (
        ComponentCapability.CAN_SET_VELOCITY,
        ComponentCapability.HAS_ANGULAR_POSITION,
    )
    assert loaded.configuration.schema_path == "settings.schema.json"


def test_manifest_loader_fails_closed_on_bad_version_capability_or_path_traversal() -> None:
    with pytest.raises(UnsupportedManifestVersionError):
        load_manifest_from_str('manifest_version: "2.0"\nid: x\n')

    bad_cap = """
manifest_version: "1.0"
id: bad.cap
model: bad.cap
name: Bad Cap
version: "0.1.0"
type: driver
category: actuator
runtime:
  min_version: "0.1.0"
capabilities:
  - not_a_real_capability
configuration:
  schema: settings.schema.json
"""
    with pytest.raises(ManifestValidationError):
        load_manifest_from_str(bad_cap)

    bad_path = bad_cap.replace("not_a_real_capability", "can_set_velocity").replace(
        "settings.schema.json", "../escape.json"
    )
    with pytest.raises(ManifestValidationError):
        load_manifest_from_str(bad_path)


def test_compatibility_checker_detects_runtime_mismatch_missing_dep_and_cycles() -> None:
    assert parse_version_key("0.2.0a1") < parse_version_key("0.2.0b1")
    assert parse_version_key("0.2.0rc1") < parse_version_key("0.2.0")

    future_driver = ComponentManifest(
        manifest_version="1.0",
        id="acme.future",
        model="motor.acme.future",
        name="Future Driver",
        version="1.0.0",
        type=ManifestType.DRIVER,
        category=ComponentCategory.ACTUATOR,
        runtime=ManifestRuntimeRequirement(min_version="0.3.0"),
        configuration=ManifestConfigurationSpec(schema="settings.schema.json"),
    )
    rt_report = check_manifest_compatibility(future_driver, runtime_version="0.2.0a1")
    assert not rt_report.compatible
    assert rt_report.status is CompatibilityStatus.INCOMPATIBLE_RUNTIME

    needs_dep = ComponentManifest(
        manifest_version="1.0",
        id="acme.controller",
        model="service.acme.controller",
        name="Controller",
        version="0.1.0",
        type=ManifestType.SERVICE,
        category=ComponentCategory.SERVICE,
        runtime=ManifestRuntimeRequirement(min_version="0.1.0"),
        dependencies=(ManifestDependency(id="acme.missing", min_version="0.1.0"),),
        configuration=ManifestConfigurationSpec(schema="settings.schema.json"),
    )
    dep_report = check_manifest_compatibility(needs_dep, runtime_version="0.2.0a1")
    assert not dep_report.compatible
    assert dep_report.status is CompatibilityStatus.MISSING_DEPENDENCY

    node_a = ComponentManifest(
        manifest_version="1.0",
        id="acme.a",
        model="service.a",
        name="A",
        version="0.1.0",
        type=ManifestType.SERVICE,
        category=ComponentCategory.SERVICE,
        runtime=ManifestRuntimeRequirement(min_version="0.1.0"),
        dependencies=(ManifestDependency(id="acme.b"),),
        configuration=ManifestConfigurationSpec(schema="settings.schema.json"),
    )
    node_b = ComponentManifest(
        manifest_version="1.0",
        id="acme.b",
        model="service.b",
        name="B",
        version="0.1.0",
        type=ManifestType.SERVICE,
        category=ComponentCategory.SERVICE,
        runtime=ManifestRuntimeRequirement(min_version="0.1.0"),
        dependencies=(ManifestDependency(id="acme.a"),),
        configuration=ManifestConfigurationSpec(schema="settings.schema.json"),
    )
    cycle_report = check_manifest_compatibility(
        node_a,
        runtime_version="0.2.0a1",
        catalog={"acme.a": node_a, "acme.b": node_b},
    )
    assert not cycle_report.compatible
    assert cycle_report.status is CompatibilityStatus.DEPENDENCY_CYCLE
