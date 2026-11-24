import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { StudioApp } from "../../apps/desktop/src/app/StudioApp.tsx";
import { useStudioUiStore } from "../../features/shell/uiStore.ts";

afterEach(() => {
  cleanup();
  useStudioUiStore.setState({
    activeView: "builder",
    activeProfile: "sim",
    selectedNodeId: null,
    activeEdgeKind: "dependency",
    commandPaletteOpen: false,
  });
});

describe("P4.3–P4.5 Studio RDE Workbench", () => {
  it("renders canonical-mock-rover workspace, adds a component, preserves YAML comments, and shows diff", () => {
    render(<StudioApp />);

    expect(screen.getByText("HIYELX Canonical Rover")).toBeInTheDocument();
    expect(screen.getByText("Lifecycle depends_on DAG valid")).toBeInTheDocument();
    expect(screen.getByText("Saved")).toBeDisabled();

    // Add a mock.motor from Robot Builder palette
    fireEvent.click(screen.getByRole("button", { name: "mock.motor" }));
    expect(screen.getByRole("button", { name: "Save robot.yaml" })).toBeEnabled();

    // Switch to Config & YAML view and verify comment round-trip preservation + new component
    fireEvent.click(screen.getByRole("button", { name: "Config & YAML" }));
    const editor = screen.getByLabelText("robot.yaml editor") as HTMLTextAreaElement;
    expect(editor.value).toContain("# HIYELX Canonical Simulation Rover");
    expect(editor.value).toContain("mock_motor_1");

    // Switch to Diff view and verify added lines appear
    fireEvent.click(screen.getByRole("button", { name: "Diff" }));
    expect(screen.getByText(/changed lines/)).toBeInTheDocument();
  });

  it("pauses visual write-back and disables Save when user enters invalid YAML without overwriting text", () => {
    render(<StudioApp />);
    fireEvent.click(screen.getByRole("button", { name: "Config & YAML" }));

    const editor = screen.getByLabelText("robot.yaml editor") as HTMLTextAreaElement;
    const brokenYaml = 'schema_version: "99"\nrobot:\n  id: broken\n  name: Broken\ncomponents: []\n';
    fireEvent.change(editor, { target: { value: brokenYaml } });

    expect(screen.getByRole("alert")).toHaveTextContent(/Unsupported schema_version/);
    expect(editor.value).toBe(brokenYaml);
    expect(screen.getByRole("button", { name: "Save robot.yaml" })).toBeDisabled();
  });

  it("switches starter templates and navigates via Command Palette", () => {
    render(<StudioApp />);
    fireEvent.click(screen.getByRole("button", { name: "single-sim-motor" }));
    expect(screen.getByText("HIYELX single-sim-motor")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Commands" }));
    expect(screen.getByRole("dialog", { name: "Command Palette" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Switch to Configuration Editor/ }));
    expect(screen.getByLabelText("robot.yaml editor")).toBeInTheDocument();
  });

  it("filters manifests in Component Explorer (M04) and adds a component into Robot Builder & robot.yaml", () => {
    render(<StudioApp />);
    fireEvent.click(screen.getByRole("button", { name: "Components" }));

    expect(screen.getByLabelText("Component and Driver Explorer")).toBeInTheDocument();
    const capSelect = screen.getByLabelText("Filter by capability");
    fireEvent.change(capSelect, { target: { value: "can_stream_frames" } });
    expect(screen.getByText("mock.camera")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Add to Robot Builder" }));
    expect(screen.getByLabelText("Visual Robot Builder")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save robot.yaml" })).toBeEnabled();

    fireEvent.click(screen.getByRole("button", { name: "Config & YAML" }));
    const editor = screen.getByLabelText("robot.yaml editor") as HTMLTextAreaElement;
    expect(editor.value).toContain("mock_camera_1");
  });
});
