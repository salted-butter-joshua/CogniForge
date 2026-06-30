/** Turn FastAPI error `detail` (string | object | array) into readable text. */
export function formatApiError(detail: unknown, fallback: string): string {
  if (detail == null || detail === "") return fallback;
  if (typeof detail === "string") return detail;

  if (Array.isArray(detail)) {
    const lines = detail.map((item) => formatApiErrorItem(item));
    const text = lines.filter(Boolean).join("；");
    return text || fallback;
  }

  if (typeof detail === "object") {
    return formatApiErrorItem(detail) || fallback;
  }

  return String(detail);
}

function formatApiErrorItem(item: unknown): string {
  if (item == null) return "";
  if (typeof item === "string") return item;
  if (typeof item !== "object") return String(item);

  const obj = item as Record<string, unknown>;
  const loc = Array.isArray(obj.loc)
    ? obj.loc.filter((p) => p !== "body").join(".")
    : "";
  const msg =
    (typeof obj.msg === "string" && obj.msg) ||
    (typeof obj.message === "string" && obj.message) ||
    "";

  if (loc && msg) return `${loc}: ${msg}`;
  if (msg) return msg;
  try {
    return JSON.stringify(item);
  } catch {
    return String(item);
  }
}
