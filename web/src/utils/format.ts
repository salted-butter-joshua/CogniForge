export function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  const sec = ms / 1000;
  if (sec < 60) return `${sec.toFixed(1)}s`;
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  if (m < 60) return `${m}:${s.toString().padStart(2, "0")}`;
  const h = Math.floor(m / 60);
  const rm = m % 60;
  return `${h}:${rm.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
}

export function formatClock(ts: number): string {
  return new Date(ts * 1000).toLocaleTimeString("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}
