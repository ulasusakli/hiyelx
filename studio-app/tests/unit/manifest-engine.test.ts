import { describe, expect, it } from "vitest";
import {
  BUILTIN_MANIFEST_CATALOG,
  UnsupportedManifestVersionError,
  compareVersions,
  evaluateManifestCompatibility,
  filterManifests,
  parseManifestYaml,
} from "@hiyelx/manifest-engine";

describe("P5.2 TypeScript manifest-engine", () => {
  it("validates every built-in manifest as compatible with runtime 0.2.0a1", () => {
    expect(BUILTIN_MANIFEST_CATALOG.length).toBeGreaterThanOrEqual(6);
    for (const manifest of BUILTIN_MANIFEST_CATALOG) {
      const report = evaluateManifestCompatibility(manifest, "0.2.0a1", BUILTIN_MANIFEST_CATALOG);
      expect(report.compatible).toBe(true);
      expect(report.status).toBe("compatible");
    }
  });

  it("parses hiyelx.manifest.yaml v1.0 and fails closed on unsupported versions", () => {
    const parsed = parseManifestYaml(`
manifest_version: "1.0"
id: acme.motor.ec
model: motor.acme.ec
name: ACME EC Motor
version: "0.1.0"
type: driver
category: actuator
runtime:
  min_version: "0.1.0"
capabilities:
  - can_set_velocity
interfaces:
  - name: command
    type: motor.command
    direction: input
configuration:
  schema: settings.schema.json
`);
    expect(parsed.id).toBe("acme.motor.ec");
    expect(parsed.capabilities).toEqual(["can_set_velocity"]);

    expect(() => parseManifestYaml('manifest_version: "2.0"\nid: bad\n')).toThrow(
      UnsupportedManifestVersionError,
    );
  });

  it("evaluates runtime version bounds, missing dependencies, and filters by capability", () => {
    expect(compareVersions("0.2.0a1", "0.2.0")).toBeLessThan(0);

    const futureManifest = parseManifestYaml(`
manifest_version: "1.0"
id: acme.future
model: motor.acme.future
name: Future Motor
version: "1.0.0"
type: driver
category: actuator
runtime:
  min_version: "0.3.0"
capabilities:
  - can_set_velocity
configuration:
  schema: settings.schema.json
`);
    const report = evaluateManifestCompatibility(futureManifest, "0.2.0a1", BUILTIN_MANIFEST_CATALOG);
    expect(report.compatible).toBe(false);
    expect(report.status).toBe("incompatible_runtime");

    const filtered = filterManifests(BUILTIN_MANIFEST_CATALOG, {
      capability: "can_stream_frames",
      compatibleOnly: true,
      runtimeVersion: "0.2.0a1",
    });
    expect(filtered.map((item) => item.model)).toEqual(["mock.camera"]);
  });
});
