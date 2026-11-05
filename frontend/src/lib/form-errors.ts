/** Normalize Django/DRF field errors without discarding additional messages. */
export function errorMessages(value: unknown): string {
  if (typeof value === "string") return value.trim();
  if (Array.isArray(value)) return value.map(errorMessages).filter(Boolean).join(" ");
  if (value && typeof value === "object") return Object.values(value).map(errorMessages).filter(Boolean).join(" ");
  return "";
}

export function parseFormErrors(value: unknown, fallback = "Unable to create user.") {
  const fields: Record<string, string> = {};
  const general: string[] = [];
  if (value && typeof value === "object" && !Array.isArray(value)) {
    for (const [key, messages] of Object.entries(value)) {
      const message = errorMessages(messages);
      if (!message) continue;
      if (["detail", "message", "error", "non_field_errors"].includes(key)) general.push(message);
      else {
        const field = key === "username" ? "email" : key === "groups" ? "group" : key;
        fields[field] = [fields[field], message].filter(Boolean).join(" ");
      }
    }
  } else {
    const message = errorMessages(value);
    if (message && !message.startsWith("<")) general.push(message);
  }
  return { fields, message: general.join(" ") || (Object.keys(fields).length ? "Please correct the highlighted fields." : fallback) };
}

export async function readFormErrors(response: Response) {
  const text = await response.text();
  let value: unknown = text;
  try { value = JSON.parse(text); } catch { /* A proxy may return plain text. */ }
  return parseFormErrors(value, `Unable to create user (${response.status}).`);
}
