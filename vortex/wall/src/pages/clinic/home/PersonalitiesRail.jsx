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

function PersonalityCard({ person, on, onActivate, onEdit }) {
  return (
    <article className={`persona-card ${on ? "on" : ""}`}>
      <VortyLook look={lookOf(person)} />
      <span className="persona-badge">On the line</span>
      <span className="persona-name">{person.name}</span>
      <span className="persona-role">{person.role}</span>
      <p className="persona-blurb">{person.description}</p>
      <div className="persona-actions">
        <Button variant={on ? "primary" : "secondary"} disabled={on} onClick={() => onActivate(person.slug)}>
          {on ? "Active" : "Activate"}
        </Button>
        <Button variant="ghost" onClick={() => onEdit(person)}>
          Edit
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
        <span>Name</span>
        <input value={name} onChange={(e) => setName(e.target.value)} required placeholder="Lucía" autoFocus />
      </label>

      <fieldset className="persona-fieldset">
        <legend>How they speak</legend>
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
        <legend>Face</legend>
        <div className="persona-looks">
          {looks.map((id) => (
            <button
              type="button"
              key={id}
              className={`persona-look ${look === id ? "on" : ""}`}
              onClick={() => setLook(id)}
              aria-label={id === "none" ? "No accessory" : id}
            >
              <VortyLook look={id} />
            </button>
          ))}
        </div>
      </fieldset>

      {error && <p className="persona-form-error">{error}</p>}
      <div className="persona-form-actions">
        <Button type="button" variant="ghost" onClick={onClose}>
          Cancel
        </Button>
        <Button type="submit" disabled={busy || !name.trim()}>
          {busy ? "Saving…" : isNew ? "Add" : "Save"}
        </Button>
      </div>
    </form>
  );
}

export default function PersonalitiesRail() {
  const { items, active, styles, looks, loading, error, activate, save, create } = usePersonalities();
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
        eyebrow="Customize agent"
        title="Who answers the phone"
        subtitle="Choose a face and how they speak. Below, voice and pace."
      />

      {error && <p className="persona-note warn">{error}</p>}
      {flash && <p className="persona-note warn">{flash}</p>}
      {loading && !items.length && <p className="persona-note">Loading personalities…</p>}

      <div className="persona-rail">
        {items.map((person) => (
          <PersonalityCard
            key={person.slug}
            person={person}
            on={person.slug === active || person.active}
            onActivate={onActivate}
            onEdit={setEditing}
          />
        ))}
        <button type="button" className="persona-card persona-add" onClick={() => setEditing({ name: "" })}>
          <span className="persona-add-mark">+</span>
          <span className="persona-name">New personality</span>
          <span className="persona-blurb">Give it a name, choose how it speaks and a face.</span>
        </button>
      </div>

      <Modal
        className="wide"
        open={Boolean(editing)}
        title={editing?.slug ? `Edit · ${editing.name}` : "New personality"}
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
