import {
  createContext,
  useContext,
  useMemo
} from "react";
import { Pause, Play } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  useTranscriptViewer
} from "@/lib/use-transcript-viewer";
import { Button } from "@/components/elevenlabs/ui/button";
import {
  ScrubBarContainer,
  ScrubBarProgress,
  ScrubBarThumb,
  ScrubBarTimeLabel,
  ScrubBarTrack
} from "@/components/elevenlabs/scrub-bar";
const TranscriptViewerContext = createContext(null);
function useTranscriptViewerContext() {
  const context = useContext(TranscriptViewerContext);
  if (!context) {
    throw new Error(
      "useTranscriptViewerContext must be used within a TranscriptViewer"
    );
  }
  return context;
}
function TranscriptViewerProvider({
  value,
  children
}) {
  return <TranscriptViewerContext.Provider value={value}>
      {children}
    </TranscriptViewerContext.Provider>;
}
function TranscriptViewerContainer({
  audioSrc,
  audioType = "audio/mpeg",
  alignment,
  segmentComposer,
  hideAudioTags = true,
  children,
  className,
  onPlay,
  onPause,
  onTimeUpdate,
  onEnded,
  onDurationChange,
  ...props
}) {
  const viewerState = useTranscriptViewer({
    alignment,
    hideAudioTags,
    segmentComposer,
    onPlay,
    onPause,
    onTimeUpdate,
    onEnded,
    onDurationChange
  });
  const { audioRef } = viewerState;
  const audioProps = useMemo(
    () => ({
      ref: audioRef,
      controls: false,
      preload: "metadata",
      src: audioSrc,
      children: <source src={audioSrc} type={audioType} />
    }),
    [audioRef, audioSrc]
  );
  const contextValue = useMemo(
    () => ({
      ...viewerState,
      audioProps
    }),
    [viewerState, audioProps]
  );
  return <TranscriptViewerProvider value={contextValue}>
      <div
    data-slot="transcript-viewer-root"
    className={cn("space-y-4 p-4", className)}
    {...props}
  >
        {children}
      </div>
    </TranscriptViewerProvider>;
}
function TranscriptViewerWord({
  word,
  status,
  className,
  children,
  ...props
}) {
  return <span
    data-slot="transcript-word"
    data-kind="word"
    data-status={status}
    className={cn(
      "rounded-sm px-0.5 transition-colors",
      status === "spoken" && "text-foreground",
      status === "unspoken" && "text-muted-foreground",
      status === "current" && "bg-primary text-primary-foreground",
      className
    )}
    {...props}
  >
      {children ?? word.text}
    </span>;
}
function TranscriptViewerWords({
  className,
  renderWord,
  renderGap,
  wordClassNames,
  gapClassNames,
  ...props
}) {
  const {
    spokenSegments,
    unspokenSegments,
    currentWord,
    segments,
    duration,
    currentTime
  } = useTranscriptViewerContext();
  const nearEnd = useMemo(() => {
    if (!duration) return false;
    return currentTime >= duration - 0.01;
  }, [currentTime, duration]);
  const segmentsWithStatus = useMemo(() => {
    if (nearEnd) {
      return segments.map((segment) => ({ segment, status: "spoken" }));
    }
    const entries = [];
    for (const segment of spokenSegments) {
      entries.push({ segment, status: "spoken" });
    }
    if (currentWord) {
      entries.push({ segment: currentWord, status: "current" });
    }
    for (const segment of unspokenSegments) {
      entries.push({ segment, status: "unspoken" });
    }
    return entries;
  }, [spokenSegments, unspokenSegments, currentWord, nearEnd, segments]);
  return <div
    data-slot="transcript-words"
    className={cn("text-xl leading-relaxed", className)}
    {...props}
  >
      {segmentsWithStatus.map(({ segment, status }) => {
    if (segment.kind === "gap") {
      const content = renderGap ? renderGap({ segment, status }) : segment.text;
      return <span
        key={`gap-${segment.segmentIndex}`}
        data-kind="gap"
        data-status={status}
        className={cn(gapClassNames)}
      >
              {content}
            </span>;
    }
    if (renderWord) {
      return <span
        key={`word-${segment.segmentIndex}`}
        data-kind="word"
        data-status={status}
        className={cn(wordClassNames)}
      >
              {renderWord({ word: segment, status })}
            </span>;
    }
    return <TranscriptViewerWord
      key={`word-${segment.segmentIndex}`}
      word={segment}
      status={status}
      className={wordClassNames}
    />;
  })}
    </div>;
}
function TranscriptViewerAudio({
  ...props
}) {
  const { audioProps } = useTranscriptViewerContext();
  return <audio
    data-slot="transcript-audio"
    {...audioProps}
    {...props}
    ref={audioProps.ref}
  />;
}
function TranscriptViewerPlayPauseButton({
  className,
  children,
  onClick,
  ...props
}) {
  const { isPlaying, play, pause } = useTranscriptViewerContext();
  const Icon = isPlaying ? Pause : Play;
  const handleClick = (event) => {
    if (isPlaying) pause();
    else play();
    onClick?.(event);
  };
  const content = typeof children === "function" ? children({ isPlaying }) : children;
  return <Button
    data-slot="transcript-play-pause-button"
    type="button"
    variant="outline"
    size="icon"
    aria-label={isPlaying ? "Pause audio" : "Play audio"}
    data-playing={isPlaying}
    className={cn("cursor-pointer", className)}
    onClick={handleClick}
    {...props}
  >
      {content ?? <Icon className="size-5" />}
    </Button>;
}
function TranscriptViewerScrubBar({
  className,
  showTimeLabels = true,
  labelsClassName,
  trackClassName,
  progressClassName,
  thumbClassName,
  ...props
}) {
  const { duration, currentTime, seekToTime, startScrubbing, endScrubbing } = useTranscriptViewerContext();
  return <ScrubBarContainer
    data-slot="transcript-scrub-bar"
    duration={duration}
    value={currentTime}
    onScrubStart={startScrubbing}
    onScrubEnd={endScrubbing}
    onScrub={seekToTime}
    className={className}
    {...props}
  >
      <div className="flex flex-1 flex-col gap-1">
        <ScrubBarTrack className={trackClassName}>
          <ScrubBarProgress className={progressClassName} />
          <ScrubBarThumb className={thumbClassName} />
        </ScrubBarTrack>
        {showTimeLabels && <div
    className={cn(
      "text-muted-foreground flex items-center justify-between text-xs",
      labelsClassName
    )}
  >
            <ScrubBarTimeLabel time={currentTime} />
            <ScrubBarTimeLabel time={duration - currentTime} />
          </div>}
      </div>
    </ScrubBarContainer>;
}
export {
  TranscriptViewerAudio,
  TranscriptViewerContainer,
  TranscriptViewerPlayPauseButton,
  TranscriptViewerProvider,
  TranscriptViewerScrubBar,
  TranscriptViewerWord,
  TranscriptViewerWords,
  useTranscriptViewerContext
};
