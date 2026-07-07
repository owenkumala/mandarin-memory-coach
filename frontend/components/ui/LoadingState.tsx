export function LoadingState({ label }: { label: string }) {
  return (
    <div className="rounded-md border border-ink/10 bg-white px-4 py-3 text-sm text-ink/65">
      {label}
    </div>
  );
}
