import { useMemo, useState } from "react";
import SectionHeader from "../../../components/ui/SectionHeader";
import Card from "../../../components/ui/Card";
import { BarVisualizer } from "../../../components/elevenlabs/bar-visualizer";
import { LiveWaveform } from "../../../components/elevenlabs/live-waveform";
import {
  AudioPlayerProvider,
  AudioPlayerButton,
  AudioPlayerProgress,
  AudioPlayerTime,
  AudioPlayerDuration,
  AudioPlayerSpeed,
} from "../../../components/elevenlabs/audio-player";
import {
  TranscriptViewerContainer,
  TranscriptViewerAudio,
  TranscriptViewerPlayPauseButton,
  TranscriptViewerScrubBar,
  TranscriptViewerWords,
} from "../../../components/elevenlabs/transcript-viewer";
import {
  Conversation,
  ConversationContent,
  ConversationScrollButton,
} from "../../../components/elevenlabs/conversation";
import {
  Message,
  MessageContent,
  MessageAvatar,
} from "../../../components/elevenlabs/message";
import demoCallUrl from "./demo-call.wav?url";
import "./ui-kit.css";

// Hidden gallery for the adopted ElevenLabs UI kit — the place to eyeball the
// Vortex re-skin (tokens.css palette, radius, type) before the Live/Calls
// pages wire the components to real data. Not linked from the sidebar; lives
// at /clinic/ui-kit. Everything below runs on mock props, never real audio.

const AGENT_STATES = ["connecting", "listening", "thinking", "speaking"];

const DEMO_AUDIO = { id: "demo-call", src: demoCallUrl };

// The transcript viewer wants ElevenLabs character-alignment timing; the mock
// below invents evenly spaced timings over the bundled demo-call.wav.
const DEMO_TRANSCRIPT =
  "Buenos días, le llamo de la clínica para confirmar su cita de mañana con el doctor Ferrer a las diez y media.";

function mockAlignment(text, secondsPerChar = 0.042) {
  const characters = [...text];
  const characterStartTimesSeconds = characters.map(
    (_, i) => +(i * secondsPerChar).toFixed(3),
  );
  const characterEndTimesSeconds = characterStartTimesSeconds.map((s) =>
    +(s + secondsPerChar * 0.9).toFixed(3),
  );
  return { characters, characterStartTimesSeconds, characterEndTimesSeconds };
}

const DEMO_MESSAGES = [
  { from: "assistant", text: "Buenos días, clínica Arenal. ¿En qué puedo ayudarle?" },
  { from: "user", text: "Hola, quería pedir cita con el doctor Ferrer para esta semana." },
  { from: "assistant", text: "Un momento, miro la agenda. ¿Me dice su nombre y apellidos?" },
  { from: "user", text: "Marta Iglesias Rovira." },
  { from: "assistant", text: "Gracias, Marta. El doctor Ferrer tiene hueco el jueves a las diez y media. ¿Le viene bien?" },
  { from: "user", text: "Perfecto, me viene genial." },
  { from: "assistant", text: "Hecho. Le queda cita el jueves a las diez y media con el doctor Ferrer." },
];

function BarVisualizerDemo() {
  const [state, setState] = useState("listening");
  return (
    <div className="ui-kit-demo">
      <div className="ui-kit-pills" role="group" aria-label="Estado del agente">
        {AGENT_STATES.map((s) => (
          <button
            key={s}
            type="button"
            className={`ui-kit-pill ${state === s ? "on" : ""}`}
            onClick={() => setState(s)}
          >
            {s}
          </button>
        ))}
      </div>
      <BarVisualizer state={state} demo barCount={18} />
    </div>
  );
}

function LiveWaveformDemo() {
  const [active, setActive] = useState(false);
  const [micError, setMicError] = useState(null);
  return (
    <div className="ui-kit-demo">
      <div className="ui-kit-pills">
        <button
          type="button"
          className={`ui-kit-pill ${active ? "on" : ""}`}
          onClick={() => setActive((a) => !a)}
        >
          {active ? "Parar micrófono" : "Probar con micrófono"}
        </button>
      </div>
      {micError && <p className="ui-kit-note">Sin acceso al micrófono: {micError}</p>}
      <LiveWaveform
        active={active}
        processing={!active}
        mode="static"
        height={72}
        onError={(e) => {
          setActive(false);
          setMicError(e.message);
        }}
      />
      <p className="ui-kit-note">Sin micrófono la ona va simulada, como en la vista de llamadas en vivo.</p>
    </div>
  );
}

function AudioPlayerDemo() {
  return (
    <AudioPlayerProvider>
      <div className="ui-kit-player">
        <AudioPlayerButton item={DEMO_AUDIO} variant="outline" size="icon" />
        <AudioPlayerProgress className="ui-kit-player-progress" />
        <AudioPlayerTime />
        <AudioPlayerDuration />
        <AudioPlayerSpeed />
      </div>
    </AudioPlayerProvider>
  );
}

function TranscriptViewerDemo() {
  const alignment = useMemo(() => mockAlignment(DEMO_TRANSCRIPT), []);
  return (
    <TranscriptViewerContainer
      audioSrc={DEMO_AUDIO.src}
      audioType="audio/wav"
      alignment={alignment}
      className="ui-kit-transcript"
    >
      <TranscriptViewerAudio />
      <div className="ui-kit-transcript-controls">
        <TranscriptViewerPlayPauseButton />
        <TranscriptViewerScrubBar />
      </div>
      <TranscriptViewerWords className="ui-kit-transcript-words" />
    </TranscriptViewerContainer>
  );
}

function ConversationDemo() {
  return (
    <div className="ui-kit-conversation">
      <Conversation>
        <ConversationContent>
          {DEMO_MESSAGES.map((m, i) => (
            <Message key={i} from={m.from}>
              <MessageContent>{m.text}</MessageContent>
              <MessageAvatar
                src={m.from === "assistant" ? "/wall/vorty-face" : ""}
                name={m.from === "assistant" ? "VX" : "PA"}
              />
            </Message>
          ))}
        </ConversationContent>
        <ConversationScrollButton />
      </Conversation>
    </div>
  );
}

export default function UiKit() {
  return (
    <div className="ui-kit-page">
      <SectionHeader
        eyebrow="Kit interno"
        title="UI kit · ElevenLabs"
        subtitle="Componentes adoptados re-maquetados con los tokens de Vortex — solo para revisión visual."
      />

      <div className="ui-kit-grid">
        <Card padding="lg" className="ui-kit-cell">
          <SectionHeader eyebrow="Voz" title="bar-visualizer" />
          <BarVisualizerDemo />
        </Card>

        <Card padding="lg" className="ui-kit-cell">
          <SectionHeader eyebrow="Voz" title="live-waveform" />
          <LiveWaveformDemo />
        </Card>

        <Card padding="lg" className="ui-kit-cell wide">
          <SectionHeader eyebrow="Audio" title="audio-player" />
          <AudioPlayerDemo />
        </Card>

        <Card padding="lg" className="ui-kit-cell wide">
          <SectionHeader eyebrow="Audio" title="transcript-viewer" />
          <TranscriptViewerDemo />
        </Card>

        <Card padding="lg" className="ui-kit-cell wide">
          <SectionHeader eyebrow="Chat" title="message · conversation" />
          <ConversationDemo />
        </Card>
      </div>
    </div>
  );
}
