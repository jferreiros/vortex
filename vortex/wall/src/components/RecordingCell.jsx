import { useEffect, useRef, useState } from "react";
import { formatClock } from "../lib/dates";
import "./recording-cell.css";

// The recording column of the Calls table, as ONE swappable seam:
// live call -> simulated wave strip (by phase), ended call with a
// call.recording event -> compact player on the native <audio> element,
// anything else -> a muted "no recording". When the ElevenLabs
// audio-player / wavesurfer components land (docs/product-control-center.md
// coordination rules), they replace this file's internals only — the page
// keeps passing the same props.

// The line serves the WAV here (GET /recordings/{call_id}); until the
// data-layer PR merges the route 404s and the cell degrades to "no
// recording" via the audio element's error event.
export function recordingUrl(callId) {
  return `/recordings/${encodeURIComponent(callId)}`;
}

const WAVE_BARS = 5;

// Simulated wave — no audio leaves the server mid-call, so the strip
// breathes by phase instead (same rule as the Live page's wave).
function LiveWave({ phase }) {
  return (
    <span className={`rec-wave rec-wave-${phase || "listening"}`} role="img" aria-label="Llamada en curso">
      {Array.from({ length: WAVE_BARS }, (_, i) => (
        <i key={i} />
      ))}
    </span>
  );
}

function PlayIcon() {
  return (
    <svg viewBox="0 0 24 24" width="13" height="13" fill="currentColor" stroke="none" aria-hidden="true">
      <path d="M8 5.5v13l11-6.5z" />
    </svg>
  );
}

function PauseIcon() {
  return (
    <svg viewBox="0 0 24 24" width="13" height="13" fill="currentColor" stroke="none" aria-hidden="true">
      <rect x="7" y="5.5" width="3.4" height="13" rx="1" />
      <rect x="13.6" y="5.5" width="3.4" height="13" rx="1" />
    </svg>
  );
}

function DownloadIcon() {
  return (
    <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M12 4v11" />
      <path d="M7 10.5l5 5 5-5" />
      <path d="M5 19.5h14" />
    </svg>
  );
}

function AudioPlayer({ callId, recording }) {
  const url = recordingUrl(callId);
  const audioRef = useRef(null);
  const trackRef = useRef(null);
  // "loading" until metadata lands (or errors) — the shell renders already
  // so the swap to "missing" doesn't move the row.
  const [ready, setReady] = useState(false);
  const [missing, setMissing] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [position, setPosition] = useState(0);
  const [duration, setDuration] = useState(recording?.durationMs ? recording.durationMs / 1000 : 0);

  useEffect(() => {
    setReady(false);
    setMissing(false);
    setPlaying(false);
    setPosition(0);
    setDuration(recording?.durationMs ? recording.durationMs / 1000 : 0);
  }, [callId, recording]);

  if (missing) {
    return <span className="rec-none">Sin grabación</span>;
  }

  const toggle = () => {
    const audio = audioRef.current;
    if (!audio) return;
    if (audio.paused) {
      audio.play().catch(() => setMissing(true));
    } else {
      audio.pause();
    }
  };

  const seek = (event) => {
    const audio = audioRef.current;
    const track = trackRef.current;
    if (!audio || !track || !duration) return;
    const rect = track.getBoundingClientRect();
    const ratio = Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width));
    audio.currentTime = ratio * duration;
    setPosition(audio.currentTime);
  };

  return (
    <span className="rec-player" onClick={(e) => e.stopPropagation()}>
      <button
        type="button"
        className="rec-play"
        onClick={toggle}
        disabled={!ready}
        aria-label={playing ? "Pausar grabación" : "Reproducir grabación"}
        title={playing ? "Pausar" : "Reproducir"}
      >
        {playing ? <PauseIcon /> : <PlayIcon />}
      </button>
      <span
        ref={trackRef}
        className={`rec-track ${ready ? "" : "pending"}`}
        onClick={seek}
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={Math.round(duration)}
        aria-valuenow={Math.round(position)}
      >
        <span className="rec-track-fill" style={{ width: duration ? `${(position / duration) * 100}%` : "0%" }} />
      </span>
      <span className="rec-time mono">
        {formatClock(position)} / {formatClock(duration)}
      </span>
      {ready && (
        <a
          className="rec-download"
          href={url}
          download
          title="Descargar grabación"
          aria-label="Descargar grabación"
        >
          <DownloadIcon />
        </a>
      )}
      <audio
        ref={audioRef}
        src={url}
        preload="metadata"
        onLoadedMetadata={(e) => {
          const d = e.currentTarget.duration;
          if (Number.isFinite(d) && d > 0) setDuration(d);
          setReady(true);
        }}
        onTimeUpdate={(e) => setPosition(e.currentTarget.currentTime)}
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onEnded={() => setPosition(0)}
        onError={() => setMissing(true)}
      />
    </span>
  );
}

export default function RecordingCell({ call }) {
  if (!call || call.live) {
    return <LiveWave phase={call?.phase} />;
  }
  if (!call.recording) {
    return <span className="rec-none">Sin grabación</span>;
  }
  return <AudioPlayer callId={call.callId} recording={call.recording} />;
}
