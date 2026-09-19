import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import Card from "../../../components/ui/Card";
import { useCallTimeline } from "../../../lib/useCallTimeline";
import { deriveFinalAction } from "../../../lib/derive";
import { resolveRawId } from "../../../lib/callRoute";
import { formatClock } from "../../../lib/dates";
import { LANGUAGE_LABEL, STATUS_LABEL, phaseView } from "../../../lib/labels";
import { toolMeta } from "../../../lib/tools";
import { ToolIcon } from "../../../lib/icons";
import { useLiveCalls } from "./useLiveCalls";
import vortyAnimated from "../../../../media/avatar2d_animated.svg";
import "./live-call-detail.css";

const CALL_CAP = 180;

function listedCall(calls, id) {
  return calls.find((c) => c.id === id) || null;
}

function callerName(items, listed, call) {
  for (let i = items.length - 1; i >= 0; i -= 1) {
    const item = items[i];
    if (item.type !== "tool" || item.tool !== "find_patient") continue;
    const name = item.result?.patient?.full_name;
    if (name) return name;
  }
  if (listed?.patient) return listed.patient;
  if (call?.from_number) return call.from_number;
  return "Caller";
}

function patientFile(items) {
  for (let i = items.length - 1; i >= 0; i -= 1) {
    const item = items[i];
    if (item.type !== "tool" || item.tool !== "find_patient") continue;
    return item.result?.patient || null;
  }
  return null;
}

function initials(name) {
  const parts = String(name)
    .split(/\s+/)
    .filter((p) => p && p !== "Sin" && p !== "identificar");
  if (!parts.length) return "?";
  return parts
    .slice(0, 2)
    .map((p) => p[0])
    .join("")
    .toUpperCase();
}

function elapsedSeconds(call, listed) {
  if (call?.live && call.started_at) {
    return Math.max(0, (Date.now() - new Date(call.started_at).getTime()) / 1000);
  }
  if (call?.duration_ms != null) return call.duration_ms / 1000;
  if (listed?.duration) {
    return listed.duration.split(":").reduce((acc, n) => acc * 60 + Number(n), 0);
  }
  return 0;
}

function turnClock(item, index, startedAt) {
  if (item.ts && startedAt) {
    const sec = (new Date(item.ts) - new Date(startedAt)) / 1000;
    if (Number.isFinite(sec) && sec >= 0) return formatClock(sec);
  }
  return formatClock(index * 12);
}

function buildSummary(turns, name) {
  if (!turns.length) return "The line is open. Waiting for the caller to speak.";
  const asked = turns.find((t) => t.role === "user")?.text;
  const lastAgent = [...turns].reverse().find((t) => t.role === "assistant")?.text;
  if (asked && lastAgent) {
    return `${name} called in: “${asked}” Vortex last said “${lastAgent}”`;
  }
  return lastAgent || asked;
}

function preview(value) {
  if (value == null || value === "") return null;
  const leaf = (v) => {
    if (v == null) return "";
    if (typeof v !== "object") return String(v);
    if (Array.isArray(v)) return v.map(leaf).filter(Boolean).join(", ");
    return Object.entries(v)
      .slice(0, 2)
      .map(([k, x]) => `${k}=${leaf(x)}`)
      .join(" ");
  };
  return leaf(value);
}

function downloadTranscript(name, turns, startedAt) {
  const lines = [
    `Clínica Arenal · ${name}`,
    "",
    ...turns.map((t, i) => `${turnClock(t, i, startedAt)}  ${t.role === "user" ? name : "Vortex"}: ${t.text}`),
  ];
  const blob = new Blob([lines.join("\n")], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${name.replace(/\s+/g, "-").toLowerCase()}-transcript.txt`;
  a.click();
  URL.revokeObjectURL(url);
}

function PlayerBar({ elapsed, playing, onToggle, onDownload }) {
  const ratio = Math.min(1, elapsed / CALL_CAP);
  return (
    <div className="tx-player">
      <button type="button" className="tx-play" aria-label={playing ? "Pause" : "Play"} onClick={onToggle}>
        {playing ? (
          <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
            <rect x="6" y="5" width="4" height="14" rx="1" fill="currentColor" />
            <rect x="14" y="5" width="4" height="14" rx="1" fill="currentColor" />
          </svg>
        ) : (
          <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
            <path d="M8 5v14l11-7z" fill="currentColor" />
          </svg>
        )}
      </button>
      <span className="tx-player-time">{formatClock(elapsed)}</span>
      <div className="tx-track" aria-hidden="true">
        <span className={ratio > 0.8 ? "fill warn" : "fill"} style={{ width: `${ratio * 100}%` }} />
      </div>
      <span className="tx-player-time faint">{formatClock(CALL_CAP)}</span>
      <button type="button" className="tx-download" onClick={onDownload}>
        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
          <path d="M12 4v11M7 11l5 5 5-5M5 19h14" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        Download
      </button>
    </div>
  );
}

export default function LiveCallDetail() {
  const { callId: rawParam } = useParams();
  const navigate = useNavigate();
  const { callId } = resolveRawId(rawParam);
  const { items, call } = useCallTimeline(callId);
  // useLiveCalls() is the same real-with-fallback feed the list page reads:
  // the mock while the first /api/wall/live-calls answer is in flight, the
  // real "in progress right now" list after that — so the pager here always
  // walks whatever Live Calls itself is showing, never a frozen demo set.
  const calls = useLiveCalls();
  const listed = listedCall(calls, rawParam);
  const streamedTurns = items.filter((it) => it.type === "turn");
  const streamedTools = items.filter((it) => it.type === "tool");
  const turns = streamedTurns.length ? streamedTurns : listed?.turns || [];
  const tools = streamedTools.length ? streamedTools : listed?.tools || [];
  const file = patientFile(items);
  const name = callerName(items, listed, call);
  const direction = listed?.direction || "inbound";
  const streamRef = useRef(null);
  const index = calls.findIndex((c) => c.id === rawParam);
  const hasPager = index >= 0;
  const [, tick] = useState(0);
  const [playing, setPlaying] = useState(false);

  useEffect(() => {
    const id = setInterval(() => tick((n) => n + 1), 1000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    const el = streamRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [turns.length]);

  const elapsed = elapsedSeconds(call, listed);
  const language = LANGUAGE_LABEL[call?.language] || listed?.language;
  const statusKey = listed?.status || (call?.live ? "live" : call?.status);
  const summary = useMemo(() => buildSummary(turns, name), [turns, name]);
  const final = deriveFinalAction(call);
  const finalLabel =
    final.label === "—" ? (listed?.status === "escalated" ? "Escalada" : "En curso…") : final.label;

  function go(delta) {
    if (!hasPager) return;
    const next = calls[index + delta];
    if (next) navigate(`/clinic/live-calls/${next.id}`);
  }

  return (
    <div className="transcript-page">
      <Card padding="sm" className="transcript-card">
        <header className="tx-head">
          <div className="tx-head-left">
            {hasPager ? (
              <div className="tx-pager">
                <button type="button" disabled={index === 0} onClick={() => go(-1)} aria-label="Previous call">
                  ‹
                </button>
                <span>
                  {index + 1} / {calls.length}
                </span>
                <button
                  type="button"
                  disabled={index === calls.length - 1}
                  onClick={() => go(1)}
                  aria-label="Next call"
                >
                  ›
                </button>
              </div>
            ) : null}
            <div className="tx-head-copy">
              <h1>{name}</h1>
              <p>
                Started by phone
                <span className="dot">·</span>
                {direction === "outbound" ? "Outbound" : "Inbound"}
              </p>
            </div>
          </div>
          <button type="button" className="tx-close" aria-label="Close" onClick={() => navigate("/clinic/live-calls")}>
            ×
          </button>
        </header>

        <div className="tx-body">
          <div className="tx-stream" ref={streamRef}>
            {turns.length === 0 ? (
              <p className="tx-empty">Waiting for the first turn…</p>
            ) : (
              turns.map((item, i) => {
                const agent = item.role !== "user";
                return (
                  <article key={item.id} className="tx-row">
                    <span className={`tx-avatar ${agent ? "agent" : ""}`}>
                      {agent ? (
                        <span className="tx-vorty" style={{ animationDelay: `${(i % 5) * 0.35}s` }}>
                          <img src={vortyAnimated} alt="" />
                        </span>
                      ) : (
                        initials(name)
                      )}
                    </span>
                    <div className="tx-msg">
                      <span className="tx-who">{agent ? "Vortex" : name}</span>
                      <p>{item.text}</p>
                      <time>{turnClock(item, i, call?.started_at)}</time>
                    </div>
                  </article>
                );
              })
            )}
          </div>

          <aside className="tx-side">
            <div className="tx-profile">
              <span className="tx-profile-avatar">{initials(name)}</span>
              <div className="tx-profile-copy">
                <strong>{name}</strong>
                <p>{listed?.phone || call?.from_number || "—"}</p>
                <p>
                  {direction === "outbound" ? "Outbound" : "Inbound"}
                  {language ? ` · ${language}` : ""}
                </p>
                <span className={`tx-status ${listed?.status === "escalated" ? "warn" : ""}`}>
                  {STATUS_LABEL[statusKey] || (listed ? phaseView(listed).label : "En llamada")}
                </span>
              </div>
            </div>
            {file?.national_id || file?.date_of_birth ? (
              <dl className="tx-profile-meta">
                {file.national_id ? (
                  <div>
                    <dt>DNI</dt>
                    <dd>{file.national_id}</dd>
                  </div>
                ) : null}
                {file.date_of_birth ? (
                  <div>
                    <dt>Born</dt>
                    <dd>{file.date_of_birth}</dd>
                  </div>
                ) : null}
              </dl>
            ) : null}

            <section>
              <h2>Summary</h2>
              <p>{summary}</p>
            </section>

            <section className="tx-tools">
              <h2>Tool calls</h2>
              {tools.length === 0 ? (
                <p className="tx-empty">No tools yet.</p>
              ) : (
                tools.map((item) => {
                  const meta = toolMeta(item.tool);
                  const ms = typeof item.ms === "number" ? `${Math.round(item.ms)} ms` : item.status === "running" ? "…" : "";
                  const line = preview(item.result) || preview(item.args);
                  return (
                    <article key={item.id} className={`tx-tool ${item.status === "running" ? "live" : ""}`}>
                      <header>
                        <ToolIcon name={item.tool} size={15} />
                        <span>{meta.label}</span>
                        <em>{ms}</em>
                      </header>
                      {line ? <p>{line}</p> : null}
                    </article>
                  );
                })
              )}
            </section>

            <div className={`tx-final ${final.accepted ? "done" : ""}`}>
              <span>Final action</span>
              <strong>{finalLabel}</strong>
            </div>
          </aside>
        </div>

        <PlayerBar
          elapsed={elapsed || 32}
          playing={playing}
          onToggle={() => setPlaying((v) => !v)}
          onDownload={() => downloadTranscript(name, turns, call?.started_at)}
        />
      </Card>
    </div>
  );
}
