import { useCallback, useEffect, useState } from "react";

// The personas live on the line (personalities.db next to its calls log); the
// board proxies them under /api/wall/personalities. When the line is down the
// proxy answers with the seed personas and `offline: true` — the rail still
// renders, but Activar and Editar are dead, because a write would not land.
export function usePersonalities() {
  const [items, setItems] = useState([]);
  const [active, setActive] = useState(null);
  const [offline, setOffline] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch("/api/wall/personalities");
      if (!res.ok) throw new Error(`personalities: ${res.status}`);
      const json = await res.json();
      setItems(json.items || []);
      setActive(json.active ?? null);
      setOffline(Boolean(json.offline));
      setError(null);
    } catch (e) {
      setError(e.message || "no se pudo cargar");
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  // The rail repaints on the click and the list is re-read afterwards, so a
  // refused activation cannot leave a card lit that the line never accepted.
  const activate = useCallback(
    async (slug) => {
      const previous = active;
      setActive(slug);
      try {
        const res = await fetch(`/api/wall/personalities/${slug}/activate`, { method: "POST" });
        const body = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(body.error || `activate: ${res.status}`);
        setItems((list) => list.map((p) => ({ ...p, active: p.slug === slug })));
        return { ok: true };
      } catch (e) {
        setActive(previous);
        return { ok: false, error: e.message };
      }
    },
    [active],
  );

  const save = useCallback(async (slug, draft) => {
    try {
      const res = await fetch(`/api/wall/personalities/${slug}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(draft),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body.error || `guardar: ${res.status}`);
      setItems((list) => list.map((p) => (p.slug === slug ? body : p)));
      return { ok: true };
    } catch (e) {
      return { ok: false, error: e.message };
    }
  }, []);

  return { items, active, offline, loading, error, reload, activate, save };
}
