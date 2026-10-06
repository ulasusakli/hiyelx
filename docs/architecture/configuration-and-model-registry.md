# Configuration and Model Registry

HIYELX configuration schema version `"1"` is a local YAML or JSON object:

```yaml
schema_version: "1"
resources:
  - identity: controller
    model: test.controller
    settings: {}
    depends_on: [left_motor]
  - identity: left_motor
    model: motor.simulated
    settings: {}
    depends_on: []
```

Each resource definition contains the existing `ResourceIdentity`, represented
as a string in the document, a non-empty stable model name, and an object of
model-specific settings. The optional `depends_on` list also contains resource
identity strings and defaults to an immutable empty tuple after validation.
Existing version `"1"` documents without this field remain valid. Unknown
fields and duplicate resource identities are invalid.

Dependency topology is validated by the Runtime Manager before any factory is
called. Duplicate dependencies, self-dependencies, missing local references,
and cycles are rejected. Dependencies are local to the same document; cross-file,
optional, conditional, remote, and version-constrained dependencies are not
supported.

Model registration is explicit at the application composition boundary. A
`ModelRegistry` instance resolves configured names only against factories that
the application registered on that instance. Configuration cannot name Python
modules or classes, and the registry performs no dynamic imports, package
scanning, or entry-point discovery. This prevents configuration from becoming
an arbitrary code-loading mechanism.

Loading validates documents but does not create resources. Registry creation
calls exactly one registered factory but does not start the returned resource
or otherwise manage its lifecycle. Lifecycle ownership remains a separate
Runtime Manager responsibility.
