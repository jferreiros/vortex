import { useState } from "react";
import SectionHeader from "../../../components/ui/SectionHeader";
import Button from "../../../components/ui/Button";
import Modal from "../../../components/ui/Modal";
import { lookOf, styleOf, usePersonalities } from "./usePersonalities";
import "./personalities.css";

function VortyLook({ look, className = "" }) {
  const stem = look && look !== "none" ? look.replace(/\.svg$/i, "") : "";
  return (
    <div className={`persona-art ${className}`.trim()}>
      <img src="/wall/vorty-face-no-headphones" alt="" />
      {stem ? <img src={`/wall/accessories/${stem}.svg`} alt="" /> : null}
    </div>
  );
}

function PersonalityCard({ person, on, offline, onActivate, onEdit }) {
  return (
    <article className={`persona-card ${on ? "on" : ""}`}>
      <VortyLook look={lookOf(person)} />
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

function PersonalityEditor({ person, styles, looks, onClose, onSubmit }) {
  const isNew = !person?.slug;
  const [name, setName] = useState(person?.name || "");
  const [style, setStyle] = useState(isNew ? "warm" : styleOf(person));
  const [look, setLook] = useState(isNew ? "headset" : lookOf(person));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    const result = await onSubmit({ name: name.trim(), style, look });
    setBusy(false);
    if (result.ok) onClose();
    else setError(result.error);
  };

  return (
    <form className="persona-form" onSubmit={submit}>
      <label className="persona-field">
        <span>Nombre</span>
        <input value={name} onChange={(e) => setName(e.target.value)} required placeholder="Lucía" autoFocus />
      </label>

      <fieldset className="persona-fieldset">
        <legend>Cómo habla</legend>
        <div className="persona-choices">
          {styles.map((item) => (
            <button
              type="button"
              key={item.id}
              className={`persona-choice ${style === item.id ? "on" : ""}`}
              onClick={() => setStyle(item.id)}
            >
              <strong>{item.label}</strong>
              <span>{item.hint}</span>
            </button>
          ))}
        </div>
      </fieldset>

      <fieldset className="persona-fieldset">
        <legend>Cara</legend>
        <div className="persona-looks">
          {looks.map((id) => (
            <button
              type="button"
              key={id}
              className={`persona-look ${look === id ? "on" : ""}`}
              onClick={() => setLook(id)}
              aria-label={id === "none" ? "Sin accesorio" : id}
            >
              <VortyLook look={id} />
            </button>
          ))}
        </div>
      </fieldset>

      {error && <p className="persona-form-error">{error}</p>}
      <div className="persona-form-actions">
        <Button type="button" variant="ghost" onClick={onClose}>
          Cancelar
        </Button>
        <Button type="submit" disabled={busy || !name.trim()}>
          {busy ? "Guardando…" : isNew ? "Añadir" : "Guardar"}
        </Button>
      </div>
    </form>
  );
}

export default function PersonalitiesRail() {
  const { items, active, styles, looks, offline, loading, error, activate, save, create } = usePersonalities();
  const [editing, setEditing] = useState(null);
  const [flash, setFlash] = useState(null);

  const onActivate = async (slug) => {
    const result = await activate(slug);
    if (!result.ok) setFlash(result.error);
  };

  const onSubmit = (draft) => {
    if (editing?.slug) return save(editing.slug, draft);
    return create(draft);
  };

  return (
    <section className="persona-block">
      <SectionHeader
        eyebrow="Personalizar agente"
        title="Quién atiende el teléfono"
        subtitle="Elige una cara y cómo habla. Debajo, voz y ritmo."
      />

      {offline && (
        <p className="persona-note warn">La línea no responde. Se muestran las voces de fábrica; los cambios no se guardan.</p>
      )}
      {error && <p className="persona-note warn">{error}</p>}
      {flash && <p className="persona-note warn">{flash}</p>}
      {loading && !items.length && <p className="persona-note">Cargando personalidades…</p>}

      <div className="persona-rail">
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
        <button type="button" className="persona-card persona-add" disabled={offline} onClick={() => setEditing({ name: "" })}>
          <span className="persona-add-mark">+</span>
          <span className="persona-name">Nueva personalidad</span>
          <span className="persona-blurb">Ponle un nombre, elige cómo habla y una cara.</span>
        </button>
      </div>

      <Modal
        className="wide"
        open={Boolean(editing)}
        title={editing?.slug ? `Editar · ${editing.name}` : "Nueva personalidad"}
        onClose={() => setEditing(null)}
      >
        {editing && (
          <PersonalityEditor
            key={editing.slug || "new"}
            person={editing}
            styles={styles}
            looks={looks}
            onClose={() => setEditing(null)}
            onSubmit={onSubmit}
          />
        )}
      </Modal>
    </section>
  );
}
