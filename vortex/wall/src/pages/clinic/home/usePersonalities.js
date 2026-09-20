import { useCallback, useEffect, useState } from "react";

const FALLBACK_STYLES = [
  { id: "warm", label: "Warm", hint: "Greets, uses the name, and confirms the appointment without rushing." },
  { id: "brisk", label: "Brisk", hint: "Gets straight to the point and offers two slots, not ten." },
  { id: "calm", label: "Calm", hint: "Repeats back what it heard and isn't in a hurry." },
];
const FALLBACK_LOOKS = ["none", "headset", "beanie", "baseball-cap", "sunglasses", "halo"];

// The personas are rows in public.personalities. The board reads and writes
// that table itself under /api/wall/personalities — no hop to the line — so a
// save that returns 200 has landed. The fallbacks below only cover the first
// paint, before the catalogue arrives.
export function usePersonalities() {
  const [items, setItems] = useState([]);
  const [active, setActive] = useState(null);
  const [styles, setStyles] = useState(FALLBACK_STYLES);
  const [looks, setLooks] = useState(FALLBACK_LOOKS);
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
      if (json.styles?.length) setStyles(json.styles);
      if (json.looks?.length) setLooks(json.looks);
      setError(null);
    } catch (e) {
      setError(e.message || "couldn't load");
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

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
      if (!res.ok) throw new Error(body.error || `save: ${res.status}`);
      setItems((list) => list.map((p) => (p.slug === slug ? body : p)));
      return { ok: true };
    } catch (e) {
      return { ok: false, error: e.message };
    }
  }, []);

  const create = useCallback(async (draft) => {
    try {
      const res = await fetch("/api/wall/personalities", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(draft),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body.error || `create: ${res.status}`);
      setItems((list) => [...list, body]);
      return { ok: true };
    } catch (e) {
      return { ok: false, error: e.message };
    }
  }, []);

  return { items, active, styles, looks, loading, error, reload, activate, save, create };
}

export function lookOf(person) {
  const stem = String(person?.avatar || "headset")
    .replace(/\.svg$/i, "")
    .toLowerCase();
  if (stem === "lucia") return "headset";
  if (stem === "mateo") return "baseball-cap";
  if (stem === "carla") return "beanie";
  return stem || "headset";
}

export function styleOf(person) {
  const tone = person?.tone || "";
  if (tone.startsWith("Brisk")) return "brisk";
  if (tone.startsWith("Calm")) return "calm";
  return "warm";
}
