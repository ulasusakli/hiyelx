import { FolderTree, Layers, PlusCircle } from "lucide-react";
import {
  STARTER_TEMPLATES,
  type ProjectManifest,
  type StarterTemplate,
} from "@hiyelx/project-engine";

export function ProjectSidebar({
  manifest,
  activeProfile,
  onSelectProfile,
  onCreateFromTemplate,
}: {
  readonly manifest: ProjectManifest;
  readonly activeProfile: string;
  readonly onSelectProfile: (profile: string) => void;
  readonly onCreateFromTemplate: (template: StarterTemplate) => void;
}) {
  const profileNames = Object.keys(manifest.profiles);
  const workspaceTree = [
    "hiyelx.project.yaml",
    manifest.workspace.robot_config,
    manifest.workspace.graph_file,
    manifest.workspace.layout_file,
    ...Object.values(manifest.profiles).map((p) => p.overrides),
    "applications/main.yaml",
    "README.md",
  ];

  return (
    <aside
      aria-label="Project Workspace Explorer"
      className="flex w-64 shrink-0 flex-col border-r border-slate-800 bg-slate-900/70 p-3 text-sm"
    >
      <div className="mb-4 border-b border-slate-800 pb-3">
        <p className="text-[11px] font-bold tracking-wider text-cyan-400 uppercase">
          Workspace · M02
        </p>
        <h2 className="mt-0.5 truncate font-semibold text-slate-100">{manifest.project.name}</h2>
        <p className="font-mono text-xs text-slate-400">
          {manifest.project.id} · v{manifest.project.version}
        </p>
      </div>

      <div className="mb-4">
        <label
          htmlFor="profile-select"
          className="mb-1 flex items-center gap-1.5 text-xs font-semibold text-slate-400"
        >
          <Layers className="h-3.5 w-3.5" aria-hidden="true" />
          Environment profile
        </label>
        <select
          id="profile-select"
          className="w-full rounded-md border border-slate-700 bg-slate-950 px-2.5 py-1.5 text-xs text-slate-100"
          value={activeProfile}
          onChange={(event) => onSelectProfile(event.target.value)}
        >
          {profileNames.map((name) => (
            <option key={name} value={name}>
              {name}
            </option>
          ))}
        </select>
      </div>

      <div className="mb-4">
        <p className="mb-1.5 flex items-center gap-1.5 text-xs font-semibold text-slate-400">
          <FolderTree className="h-3.5 w-3.5" aria-hidden="true" />
          Project tree (Filesystem SoT)
        </p>
        <ul className="space-y-1 font-mono text-xs text-slate-300">
          {workspaceTree.map((filePath) => (
            <li
              key={filePath}
              className="truncate rounded px-2 py-1 hover:bg-slate-800/70"
              title={filePath}
            >
              {filePath}
            </li>
          ))}
        </ul>
      </div>

      <div className="mt-auto border-t border-slate-800 pt-3">
        <p className="mb-2 flex items-center gap-1.5 text-xs font-semibold text-slate-400">
          <PlusCircle className="h-3.5 w-3.5" aria-hidden="true" />
          New from starter template
        </p>
        <div className="flex flex-col gap-1.5">
          {STARTER_TEMPLATES.map((template) => (
            <button
              key={template}
              type="button"
              className="rounded-md border border-slate-700 bg-slate-950 px-2.5 py-1.5 text-left font-mono text-xs text-slate-200 hover:border-cyan-500/60 hover:bg-slate-800"
              onClick={() => onCreateFromTemplate(template)}
            >
              {template}
            </button>
          ))}
        </div>
      </div>
    </aside>
  );
}
