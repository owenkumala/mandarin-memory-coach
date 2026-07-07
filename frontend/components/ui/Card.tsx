import type { HTMLAttributes } from "react";

export function Card({ className = "", ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <section
      className={`rounded-lg border border-ink/10 bg-white p-5 shadow-soft ${className}`}
      {...props}
    />
  );
}
