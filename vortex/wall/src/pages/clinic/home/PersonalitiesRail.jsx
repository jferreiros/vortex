import { useRef, useState } from "react";
import SectionHeader from "../../../components/ui/SectionHeader";
import Button from "../../../components/ui/Button";
import Modal from "../../../components/ui/Modal";
import { usePersonalities } from "./usePersonalities";
import "./personalities.css";

const LANGUAGES = [
  ["es", "Español"],
  ["en", "English"],
  ["ca", "Català"],
  ["gl", "Galego"],
  ["eu", "Euskera"],
];

function emptyDraft(person) {
  return {
    name: person.name,
    role: person.role,
    description: person.description,
    tone: person.tone,
    greetings: { ...(person.greetings || {}) },
    voices: { ...(person.voices || {}) },
    avatar: person.avatar,
  };
}

function PersonalityCard({ person, on, offline, onActivate, onEdit }) {
  return (
    <article className={`persona-card ${on ? "on" : ""}`}>
      <div className="persona-art">
        <img src={`/wall/personalities/${person.avatar}`} alt="" />
      </div>
      <span className="persona-badge">En la línea</span>
      <span className="persona-name">{person.name}</span>
      <span className="persona-role">{person.role}</span>
      <p className="persona-blurb">{person.description}</p>
      <div className="persona-actions">
        <Button variant={on ? "primary" : "secondary"} disabled={offline || on} onClick={() => onActivate(person.slug)}>
          {on ? "Activa" : "Activar"}
        </Button>
        <Button variant="ghost" disabled={offline} onClick={() => onEdit(person)}>
          Editar
        </Button>
      </div>
    </article>
  );
}

function PersonalityEditor({ person, onClose, onSave }) {
  const [draft, setDraft] = useState(() => emptyDraft(person));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const setField = (key, value) => {
    setDraft((prev) => ({ ...prev, [key]: value }));
    setError(null);
  };

  const setLang = (bucket, code, value) => {
    setDraft((prev) => ({ ...prev, [bucket]: { ...prev[bucket], [code]: value } }));
    setError(null);
  };

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    const result = await onSave(person.slug, draft);
    setBusy(false);
    if (result.ok) onClose();
    else setError(result.error);
  };

  return (
    <form className="persona-form" onSubmit={submit}>
      <label className="persona-field">
        <span>Nombre</span>
        <input value={draft.name} onChange={(e) => setField("name", e.target.value)} required />
      </label>
      <label className="persona-field">
        <span>Rol</span>
        <input value={draft.role} onChange={(e) => setField("role", e.target.value)} required />
      </label>
      <label className="persona-field">
        <span>Descripción (la ve el equipo)</span>
        <textarea value={draft.description} onChange={(e) => setField("description", e.target.value)} required />
      </label>
      <label className="persona-field">
        <span>Tono (va en el prompt, en inglés)</span>
        <textarea value={draft.tone} onChange={(e) => setField("tone", e.target.value)} required maxLength={400} />
        <span className="persona-field-hint">{draft.tone.length}/400</span>
      </label>
      <div className="persona-form-grid">
        {LANGUAGES.map(([code, label]) => (
          <label className="persona-field" key={`g-${code}`}>
            <span>Saludo · {label}</span>
            <input
              value={draft.greetings[code] || ""}
              onChange={(e) => setLang("greetings", code, e.target.value)}
            />
          </label>
        ))}
      </div>
      <div className="persona-form-grid">
        {LANGUAGES.map(([code, label]) => (
          <label className="persona-field" key={`v-${code}`}>
            <span>Voz TTS · {label}</span>
            <input value={draft.voices[code] || ""} onChange={(e) => setLang("voices", code, e.target.value)} />
          </label>
        ))}
      </div>
      <label className="persona-field">
        <span>Archivo del retrato (vortex/wall/media/personalities)</span>
        <input value={draft.avatar} onChange={(e) => setField("avatar", e.target.value)} required />
      </label>
      {error && <p className="persona-form-error">{error}</p>}
      <div className="persona-form-actions">
        <Button type="button" variant="ghost" onClick={onClose}>
          Cancelar
        </Button>
        <Button type="submit" disabled={busy}>
          {busy ? "Guardando…" : "Guardar"}
        </Button>
      </div>
    </form>
  );
}

export default function PersonalitiesRail() {
  const rail = useRef(null);
  const { items, active, offline, loading, error, activate, save } = usePersonalities();
  const [editing, setEditing] = useState(null);
  const [flash, setFlash] = useState(null);

  const shift = (dir) => {
    const node = rail.current;
    if (!node) return;
    node.scrollBy({ left: dir * 240, behavior: "smooth" });
  };

  const onActivate = async (slug) => {
    const result = await activate(slug);
    if (!result.ok) setFlash(result.error);
  };

  return (
    <section className="persona-block">
      <SectionHeader
        eyebrow="Personalidades"
        title="Quién atiende el teléfono"
        subtitle="Elige la voz de la clínica. El retrato animado lo sustituye el equipo; esto guarda el nombre, el tono y las voces."
        action={
          <div className="persona-shifts">
            <button type="button" className="persona-shift" onClick={() => shift(-1)} aria-label="Anterior">
              <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M15 6l-6 6 6 6" />
              </svg>
            </button>
            <button type="button" className="persona-shift" onClick={() => shift(1)} aria-label="Siguiente">
              <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M9 6l6 6-6 6" />
              </svg>
            </button>
          </div>
        }
      />

      {offline && (
        <p className="persona-note warn">La línea no responde. Se muestran las tres voces de fábrica; Activar y Editar no se guardan.</p>
      )}
      {error && <p className="persona-note warn">{error}</p>}
      {flash && <p className="persona-note warn">{flash}</p>}
      {loading && !items.length && <p className="persona-note">Cargando personalidades…</p>}

      <div className="persona-rail-wrap">
        <div className="persona-rail" ref={rail}>
          {items.map((person) => (
            <PersonalityCard
              key={person.slug}
              person={person}
              on={person.slug === active || person.active}
              offline={offline}
              onActivate={onActivate}
              onEdit={setEditing}
            />
          ))}
        </div>
      </div>

      <Modal
        className="wide"
        open={Boolean(editing)}
        title={editing ? `Editar · ${editing.name}` : ""}
        onClose={() => setEditing(null)}
      >
        {editing && (
          <PersonalityEditor person={editing} onClose={() => setEditing(null)} onSave={save} />
        )}
      </Modal>
    </section>
  );
}
