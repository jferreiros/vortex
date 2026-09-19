import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState
} from "react";
import { Slider as SliderPrimitive } from "radix-ui";
import { Check, PauseIcon, PlayIcon, Settings } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/elevenlabs/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger
} from "@/components/elevenlabs/ui/dropdown-menu";
var ReadyState = /* @__PURE__ */ ((ReadyState2) => {
  ReadyState2[ReadyState2["HAVE_NOTHING"] = 0] = "HAVE_NOTHING";
  ReadyState2[ReadyState2["HAVE_METADATA"] = 1] = "HAVE_METADATA";
  ReadyState2[ReadyState2["HAVE_CURRENT_DATA"] = 2] = "HAVE_CURRENT_DATA";
  ReadyState2[ReadyState2["HAVE_FUTURE_DATA"] = 3] = "HAVE_FUTURE_DATA";
  ReadyState2[ReadyState2["HAVE_ENOUGH_DATA"] = 4] = "HAVE_ENOUGH_DATA";
  return ReadyState2;
})(ReadyState || {});
var NetworkState = /* @__PURE__ */ ((NetworkState2) => {
  NetworkState2[NetworkState2["NETWORK_EMPTY"] = 0] = "NETWORK_EMPTY";
  NetworkState2[NetworkState2["NETWORK_IDLE"] = 1] = "NETWORK_IDLE";
  NetworkState2[NetworkState2["NETWORK_LOADING"] = 2] = "NETWORK_LOADING";
  NetworkState2[NetworkState2["NETWORK_NO_SOURCE"] = 3] = "NETWORK_NO_SOURCE";
  return NetworkState2;
})(NetworkState || {});
function formatTime(seconds) {
  const hrs = Math.floor(seconds / 3600);
  const mins = Math.floor(seconds % 3600 / 60);
  const secs = Math.floor(seconds % 60);
  const formattedMins = mins < 10 ? `0${mins}` : mins;
  const formattedSecs = secs < 10 ? `0${secs}` : secs;
  return hrs > 0 ? `${hrs}:${formattedMins}:${formattedSecs}` : `${mins}:${formattedSecs}`;
}
const AudioPlayerContext = createContext(null);
function useAudioPlayer() {
  const api = useContext(AudioPlayerContext);
  if (!api) {
    throw new Error(
      "useAudioPlayer cannot be called outside of AudioPlayerProvider"
    );
  }
  return api;
}
const AudioPlayerTimeContext = createContext(null);
const useAudioPlayerTime = () => {
  const time = useContext(AudioPlayerTimeContext);
  if (time === null) {
    throw new Error(
      "useAudioPlayerTime cannot be called outside of AudioPlayerProvider"
    );
  }
  return time;
};
function AudioPlayerProvider({
  children
}) {
  const audioRef = useRef(null);
  const itemRef = useRef(null);
  const playPromiseRef = useRef(null);
  const [readyState, setReadyState] = useState(0);
  const [networkState, setNetworkState] = useState(0);
  const [time, setTime] = useState(0);
  const [duration, setDuration] = useState(void 0);
  const [error, setError] = useState(null);
  const [activeItem, _setActiveItem] = useState(
    null
  );
  const [paused, setPaused] = useState(true);
  const [playbackRate, setPlaybackRateState] = useState(1);
  const setActiveItem = useCallback(
    async (item) => {
      if (!audioRef.current) return;
      if (item?.id === itemRef.current?.id) {
        return;
      }
      itemRef.current = item;
      const currentRate = audioRef.current.playbackRate;
      audioRef.current.pause();
      audioRef.current.currentTime = 0;
      if (item === null) {
        audioRef.current.removeAttribute("src");
      } else {
        audioRef.current.src = item.src;
      }
      audioRef.current.load();
      audioRef.current.playbackRate = currentRate;
    },
    []
  );
  const play = useCallback(
    async (item) => {
      if (!audioRef.current) return;
      if (playPromiseRef.current) {
        try {
          await playPromiseRef.current;
        } catch (error2) {
          console.error("Play promise error:", error2);
        }
      }
      if (item === void 0) {
        const playPromise2 = audioRef.current.play();
        playPromiseRef.current = playPromise2;
        return playPromise2;
      }
      if (item?.id === activeItem?.id) {
        const playPromise2 = audioRef.current.play();
        playPromiseRef.current = playPromise2;
        return playPromise2;
      }
      itemRef.current = item;
      const currentRate = audioRef.current.playbackRate;
      if (!audioRef.current.paused) {
        audioRef.current.pause();
      }
      audioRef.current.currentTime = 0;
      if (item === null) {
        audioRef.current.removeAttribute("src");
      } else {
        audioRef.current.src = item.src;
      }
      audioRef.current.load();
      audioRef.current.playbackRate = currentRate;
      const playPromise = audioRef.current.play();
      playPromiseRef.current = playPromise;
      return playPromise;
    },
    [activeItem]
  );
  const pause = useCallback(async () => {
    if (!audioRef.current) return;
    if (playPromiseRef.current) {
      try {
        await playPromiseRef.current;
      } catch (e) {
        console.error(e);
      }
    }
    audioRef.current.pause();
    playPromiseRef.current = null;
  }, []);
  const seek = useCallback((time2) => {
    if (!audioRef.current) return;
    audioRef.current.currentTime = time2;
  }, []);
  const setPlaybackRate = useCallback((rate) => {
    if (!audioRef.current) return;
    audioRef.current.playbackRate = rate;
    setPlaybackRateState(rate);
  }, []);
  const isItemActive = useCallback(
    (id) => {
      return activeItem?.id === id;
    },
    [activeItem]
  );
  useAnimationFrame(() => {
    if (audioRef.current) {
      _setActiveItem(itemRef.current);
      setReadyState(audioRef.current.readyState);
      setNetworkState(audioRef.current.networkState);
      setTime(audioRef.current.currentTime);
      setDuration(audioRef.current.duration);
      setPaused(audioRef.current.paused);
      setError(audioRef.current.error);
      setPlaybackRateState(audioRef.current.playbackRate);
    }
  });
  const isPlaying = !paused;
  const isBuffering = readyState < 3 /* HAVE_FUTURE_DATA */ && networkState === 2 /* NETWORK_LOADING */;
  const api = useMemo(
    () => ({
      ref: audioRef,
      duration,
      error,
      isPlaying,
      isBuffering,
      activeItem,
      playbackRate,
      isItemActive,
      setActiveItem,
      play,
      pause,
      seek,
      setPlaybackRate
    }),
    [
      audioRef,
      duration,
      error,
      isPlaying,
      isBuffering,
      activeItem,
      playbackRate,
      isItemActive,
      setActiveItem,
      play,
      pause,
      seek,
      setPlaybackRate
    ]
  );
  return <AudioPlayerContext.Provider value={api}>
      <AudioPlayerTimeContext.Provider value={time}>
        <audio ref={audioRef} className="hidden" crossOrigin="anonymous" />
        {children}
      </AudioPlayerTimeContext.Provider>
    </AudioPlayerContext.Provider>;
}
const AudioPlayerProgress = ({
  ...otherProps
}) => {
  const player = useAudioPlayer();
  const time = useAudioPlayerTime();
  const wasPlayingRef = useRef(false);
  return <SliderPrimitive.Root
    {...otherProps}
    value={[time]}
    onValueChange={(vals) => {
      player.seek(vals[0]);
      otherProps.onValueChange?.(vals);
    }}
    min={0}
    max={player.duration ?? 0}
    step={otherProps.step || 0.25}
    onPointerDown={(e) => {
      wasPlayingRef.current = player.isPlaying;
      player.pause();
      otherProps.onPointerDown?.(e);
    }}
    onPointerUp={(e) => {
      if (wasPlayingRef.current) {
        player.play();
      }
      otherProps.onPointerUp?.(e);
    }}
    className={cn(
      "group/player relative flex h-4 touch-none items-center select-none data-[disabled]:opacity-50 data-[orientation=vertical]:h-full data-[orientation=vertical]:min-h-44 data-[orientation=vertical]:w-auto data-[orientation=vertical]:flex-col",
      otherProps.className
    )}
    onKeyDown={(e) => {
      if (e.key === " ") {
        e.preventDefault();
        if (!player.isPlaying) {
          player.play();
        } else {
          player.pause();
        }
      }
      otherProps.onKeyDown?.(e);
    }}
    disabled={player.duration === void 0 || !Number.isFinite(player.duration) || Number.isNaN(player.duration)}
  >
      <SliderPrimitive.Track className="bg-muted relative h-[4px] w-full grow overflow-hidden rounded-full">
        <SliderPrimitive.Range className="bg-primary absolute h-full" />
      </SliderPrimitive.Track>
      <SliderPrimitive.Thumb
    className="relative flex h-0 w-0 items-center justify-center opacity-0 group-hover/player:opacity-100 focus-visible:opacity-100 focus-visible:outline-none disabled:pointer-events-none disabled:opacity-50"
    data-slot="slider-thumb"
  >
        <div className="bg-foreground absolute size-3 rounded-full" />
      </SliderPrimitive.Thumb>
    </SliderPrimitive.Root>;
};
const AudioPlayerTime = ({
  className,
  ...otherProps
}) => {
  const time = useAudioPlayerTime();
  return <span
    {...otherProps}
    className={cn("text-muted-foreground text-sm tabular-nums", className)}
  >
      {formatTime(time)}
    </span>;
};
const AudioPlayerDuration = ({
  className,
  ...otherProps
}) => {
  const player = useAudioPlayer();
  return <span
    {...otherProps}
    className={cn("text-muted-foreground text-sm tabular-nums", className)}
  >
      {player.duration !== null && player.duration !== void 0 && !Number.isNaN(player.duration) ? formatTime(player.duration) : "--:--"}
    </span>;
};
function Spinner({ className }) {
  return <div
    className={cn(
      "border-muted border-t-foreground size-3.5 animate-spin rounded-full border-2",
      className
    )}
    role="status"
    aria-label="Loading"
  >
      <span className="sr-only">Loading...</span>
    </div>;
}
const PlayButton = ({
  playing,
  onPlayingChange,
  className,
  onClick,
  loading,
  ...otherProps
}) => {
  return <Button
    {...otherProps}
    onClick={(e) => {
      onPlayingChange(!playing);
      onClick?.(e);
    }}
    className={cn("relative", className)}
    aria-label={playing ? "Pause" : "Play"}
    type="button"
  >
      {playing ? <PauseIcon
    className={cn("size-4", loading && "opacity-0")}
    aria-hidden="true"
  /> : <PlayIcon
    className={cn("size-4", loading && "opacity-0")}
    aria-hidden="true"
  />}
      {loading && <div className="absolute inset-0 flex items-center justify-center rounded-[inherit] backdrop-blur-sm">
          <Spinner />
        </div>}
    </Button>;
};
function AudioPlayerButton({
  item,
  ...otherProps
}) {
  const player = useAudioPlayer();
  if (!item) {
    return <PlayButton
      {...otherProps}
      playing={player.isPlaying}
      onPlayingChange={(shouldPlay) => {
        if (shouldPlay) {
          player.play();
        } else {
          player.pause();
        }
      }}
      loading={player.isBuffering && player.isPlaying}
    />;
  }
  return <PlayButton
    {...otherProps}
    playing={player.isItemActive(item.id) && player.isPlaying}
    onPlayingChange={(shouldPlay) => {
      if (shouldPlay) {
        player.play(item);
      } else {
        player.pause();
      }
    }}
    loading={player.isItemActive(item.id) && player.isBuffering && player.isPlaying}
  />;
}
function useAnimationFrame(callback) {
  const requestRef = useRef(null);
  const previousTimeRef = useRef(null);
  const callbackRef = useRef(callback);
  useEffect(() => {
    callbackRef.current = callback;
  }, [callback]);
  useEffect(() => {
    const animate = (time) => {
      if (previousTimeRef.current !== null) {
        const delta = time - previousTimeRef.current;
        callbackRef.current(delta);
      }
      previousTimeRef.current = time;
      requestRef.current = requestAnimationFrame(animate);
    };
    requestRef.current = requestAnimationFrame(animate);
    return () => {
      if (requestRef.current) cancelAnimationFrame(requestRef.current);
      previousTimeRef.current = null;
    };
  }, []);
}
const PLAYBACK_SPEEDS = [0.25, 0.5, 0.75, 1, 1.25, 1.5, 1.75, 2];
function AudioPlayerSpeed({
  speeds = PLAYBACK_SPEEDS,
  className,
  variant = "ghost",
  size = "icon",
  ...props
}) {
  const player = useAudioPlayer();
  const currentSpeed = player.playbackRate;
  return <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
    variant={variant}
    size={size}
    className={cn(className)}
    aria-label="Playback speed"
    {...props}
  >
          <Settings className="size-4" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="min-w-[120px]">
        {speeds.map((speed) => <DropdownMenuItem
    key={speed}
    onClick={() => player.setPlaybackRate(speed)}
    className="flex items-center justify-between"
  >
            <span className={speed === 1 ? "" : "font-mono"}>
              {speed === 1 ? "Normal" : `${speed}x`}
            </span>
            {currentSpeed === speed && <Check className="size-4" />}
          </DropdownMenuItem>)}
      </DropdownMenuContent>
    </DropdownMenu>;
}
function AudioPlayerSpeedButtonGroup({
  speeds = [0.5, 1, 1.5, 2],
  className,
  ...props
}) {
  const player = useAudioPlayer();
  const currentSpeed = player.playbackRate;
  return <div
    className={cn("flex items-center gap-1", className)}
    role="group"
    aria-label="Playback speed controls"
    {...props}
  >
      {speeds.map((speed) => <Button
    key={speed}
    variant={currentSpeed === speed ? "default" : "outline"}
    size="sm"
    onClick={() => player.setPlaybackRate(speed)}
    className="min-w-[50px] font-mono text-xs"
  >
          {speed}x
        </Button>)}
    </div>;
}
const exampleTracks = [
  {
    id: "0",
    name: "II - 00",
    url: "https://storage.googleapis.com/eleven-public-cdn/audio/ui-elevenlabs-io/00.mp3"
  },
  {
    id: "1",
    name: "II - 01",
    url: "https://storage.googleapis.com/eleven-public-cdn/audio/ui-elevenlabs-io/01.mp3"
  },
  {
    id: "2",
    name: "II - 02",
    url: "https://storage.googleapis.com/eleven-public-cdn/audio/ui-elevenlabs-io/02.mp3"
  },
  {
    id: "3",
    name: "II - 03",
    url: "https://storage.googleapis.com/eleven-public-cdn/audio/ui-elevenlabs-io/03.mp3"
  },
  {
    id: "4",
    name: "II - 04",
    url: "https://storage.googleapis.com/eleven-public-cdn/audio/ui-elevenlabs-io/04.mp3"
  },
  {
    id: "5",
    name: "II - 05",
    url: "https://storage.googleapis.com/eleven-public-cdn/audio/ui-elevenlabs-io/05.mp3"
  },
  {
    id: "6",
    name: "II - 06",
    url: "https://storage.googleapis.com/eleven-public-cdn/audio/ui-elevenlabs-io/06.mp3"
  },
  {
    id: "7",
    name: "II - 07",
    url: "https://storage.googleapis.com/eleven-public-cdn/audio/ui-elevenlabs-io/07.mp3"
  },
  {
    id: "8",
    name: "II - 08",
    url: "https://storage.googleapis.com/eleven-public-cdn/audio/ui-elevenlabs-io/08.mp3"
  },
  {
    id: "9",
    name: "II - 09",
    url: "https://storage.googleapis.com/eleven-public-cdn/audio/ui-elevenlabs-io/09.mp3"
  }
];
export {
  AudioPlayerButton,
  AudioPlayerDuration,
  AudioPlayerProgress,
  AudioPlayerProvider,
  AudioPlayerSpeed,
  AudioPlayerSpeedButtonGroup,
  AudioPlayerTime,
  exampleTracks,
  useAudioPlayer,
  useAudioPlayerTime
};
