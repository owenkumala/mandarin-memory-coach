export function formatDateTime(timestamp: string | null): string {
  if (!timestamp) {
    return "Not saved yet";
  }

  return new Intl.DateTimeFormat("en", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(timestamp));
}
