/** True when the page is served from the Vite dev server (localhost/127.0.0.1, ports 5173–5189). */
export function isLocalViteDevPage() {
  if (!import.meta.env.DEV || typeof window === "undefined" || !window.location?.origin) {
    return false;
  }
  try {
    const u = new URL(window.location.origin);
    if (!/^(localhost|127\.0\.0\.1)$/i.test(u.hostname)) return false;
    const port = u.port ? Number(u.port) : u.protocol === "https:" ? 443 : 80;
    return port >= 5173 && port <= 5189;
  } catch {
    return false;
  }
}
