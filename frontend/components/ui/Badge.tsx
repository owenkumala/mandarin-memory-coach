import type { HTMLAttributes } from "react";

type BadgeTone = "neutral" | "active" | "improving" | "resolved";

const toneClasses: Record<BadgeTone, string> = {
  neutral: "bg-ink/10 text-ink",
  active: "bg-rose-100 text-rose-800",
  improving: "bg-amber-100 text-amber-800",
  resolved: "bg-emerald-100 text-emerald-800",
};

export function Badge({
  className = "",
  tone = "neutral",
  ...props
}: HTMLAttributes<HTMLSpanElement> & { tone?: BadgeTone }) {
  return (
    <span
      className={`inline-flex items-center rounded-md px-2.5 py-1 text-xs font-semibold ${toneClasses[tone]} ${className}`}
      {...props}
    />
  );
}
