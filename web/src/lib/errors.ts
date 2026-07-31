/**
 * Pull the human message out of an ApiError. `request()` throws with the raw response body
 * as the message, which for FastAPI is a JSON `{detail}` envelope — showing it unparsed puts
 * literal braces in front of the user.
 */
export function errorDetail(err: unknown, fallback: string): string {
  if (err && typeof err === "object" && "message" in err && typeof err.message === "string") {
    try {
      const parsed = JSON.parse(err.message);
      if (parsed && typeof parsed.detail === "string") return parsed.detail;
    } catch {
      /* not JSON — fall through */
    }
    if (err.message) return err.message;
  }
  return fallback;
}
