/**
 * Copy text to the clipboard, with a fallback for non-secure contexts.
 *
 * `navigator.clipboard` only exists in a secure context (HTTPS or localhost). When the app
 * is served over plain HTTP on a LAN IP (e.g. http://192.168.50.81:8080) it's `undefined`,
 * so we fall back to the legacy execCommand('copy') via a hidden textarea.
 */
export async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    // fall through to the legacy path
  }
  try {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.setAttribute("readonly", "");
    ta.style.position = "fixed";
    ta.style.top = "-1000px";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.focus();
    ta.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(ta);
    return ok;
  } catch {
    return false;
  }
}
