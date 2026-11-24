import { create } from "zustand";
import type { StudioEdgeKind } from "@hiyelx/graph-engine";

export type StudioViewId =
  | "builder"
  | "data-flow"
  | "explorer"
  | "config"
  | "diff"
  | "applications"
  | "dev-env"
  | "monitor"
  | "diagnostics";

/**
 * Transient UI state ONLY (ADR 0002 v1.1 Decision 6).
 * Authoritative project and robot files live on the local filesystem, never in Zustand.
 */
interface StudioUiState {
  readonly activeView: StudioViewId;
  readonly activeProfile: string;
  readonly selectedNodeId: string | null;
  readonly activeEdgeKind: StudioEdgeKind;
  readonly commandPaletteOpen: boolean;
  setActiveView: (view: StudioViewId) => void;
  setActiveProfile: (profile: string) => void;
  setSelectedNodeId: (nodeId: string | null) => void;
  setActiveEdgeKind: (kind: StudioEdgeKind) => void;
  setCommandPaletteOpen: (open: boolean) => void;
}

export const useStudioUiStore = create<StudioUiState>((set) => ({
  activeView: "builder",
  activeProfile: "sim",
  selectedNodeId: null,
  activeEdgeKind: "dependency",
  commandPaletteOpen: false,
  setActiveView: (activeView) => set({ activeView }),
  setActiveProfile: (activeProfile) => set({ activeProfile }),
  setSelectedNodeId: (selectedNodeId) => set({ selectedNodeId }),
  setActiveEdgeKind: (activeEdgeKind) => set({ activeEdgeKind }),
  setCommandPaletteOpen: (commandPaletteOpen) => set({ commandPaletteOpen }),
}));
