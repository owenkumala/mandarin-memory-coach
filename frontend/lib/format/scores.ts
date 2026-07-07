export function formatScore(score: number): string {
  return `${Math.round(score)}%`;
}

export function formatSeverity(score: number): string {
  return score.toFixed(1);
}
