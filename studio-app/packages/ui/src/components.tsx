import type { ReactNode } from "react";

export type BadgeTone = "neutral" | "success" | "warning" | "error";

const TONE_CLASSES: Record<BadgeTone, string> = {
  neutral: "border-slate-700 bg-slate-900 text-slate-200",
  success: "border-emerald-700/70 bg-emerald-950/70 text-emerald-300",
  warning: "border-amber-700/70 bg-amber-950/70 text-amber-300",
  error: "border-rose-700/70 bg-rose-950/70 text-rose-300",
};

export function StatusBadge({
  tone = "neutral",
  children,
}: {
  readonly tone?: BadgeTone;
  readonly children: ReactNode;
}) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-semibold ${TONE_CLASSES[tone]}`}
    >
      {children}
    </span>
  );
}
