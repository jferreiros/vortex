import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState
} from "react";
function composeSegments(alignment, options = {}) {
  const {
    characters,
    characterStartTimesSeconds: starts,
    characterEndTimesSeconds: ends
  } = alignment;
  const segments = [];
  const words = [];
  let wordBuffer = "";
  let whitespaceBuffer = "";
  let wordStart = 0;
  let wordEnd = 0;
  let segmentIndex = 0;
  let wordIndex = 0;
  let insideAudioTag = false;
  const hideAudioTags = options.hideAudioTags ?? false;
  const flushWhitespace = () => {
    if (!whitespaceBuffer) return;
    segments.push({
      kind: "gap",
      segmentIndex: segmentIndex++,
      text: whitespaceBuffer
    });
    whitespaceBuffer = "";
  };
  const flushWord = () => {
    if (!wordBuffer) return;
    const word = {
      kind: "word",
      segmentIndex: segmentIndex++,
      wordIndex: wordIndex++,
      text: wordBuffer,
      startTime: wordStart,
      endTime: wordEnd
    };
    segments.push(word);
    words.push(word);
    wordBuffer = "";
  };
  for (let i = 0; i < characters.length; i++) {
    const char = characters[i];
    const start = starts[i] ?? 0;
    const end = ends[i] ?? start;
    if (hideAudioTags) {
      if (char === "[") {
        flushWord();
        whitespaceBuffer = "";
        insideAudioTag = true;
        continue;
      }
      if (insideAudioTag) {
        if (char === "]") insideAudioTag = false;
        continue;
      }
    }
    if (/\s/.test(char)) {
      flushWord();
      whitespaceBuffer += char;
      continue;
    }
    if (whitespaceBuffer) {
      flushWhitespace();
    }
    if (!wordBuffer) {
      wordBuffer = char;
      wordStart = start;
      wordEnd = end;
    } else {
      wordBuffer += char;
      wordEnd = end;
    }
  }
  flushWord();
  flushWhitespace();
  return { segments, words };
}
function useTranscriptViewer({
  alignment,
  hideAudioTags = true,
  segmentComposer,
  onPlay,
  onPause,
  onTimeUpdate,
  onEnded,
  onDurationChange
}) {
  const audioRef = useRef(null);
  const rafRef = useRef(null);
  const handleTimeUpdateRef = useRef(() => {
  });
  const onDurationChangeRef = useRef(() => {
  });
  const [isPlaying, setIsPlaying] = useState(false);
  const [isScrubbing, setIsScrubbing] = useState(false);
  const [duration, setDuration] = useState(0);
  const [currentTime, setCurrentTime] = useState(0);
  const { segments, words } = useMemo(() => {
    if (segmentComposer) {
      return segmentComposer(alignment);
    }
    return composeSegments(alignment, { hideAudioTags });
  }, [segmentComposer, alignment, hideAudioTags]);
  const guessedDuration = useMemo(() => {
    const ends = alignment?.characterEndTimesSeconds;
    if (Array.isArray(ends) && ends.length) {
      const last = ends[ends.length - 1];
      return Number.isFinite(last) ? last : 0;
    }
    if (words.length) {
      const lastWord = words[words.length - 1];
      return Number.isFinite(lastWord.endTime) ? lastWord.endTime : 0;
    }
    return 0;
  }, [alignment, words]);
  const [currentWordIndex, setCurrentWordIndex] = useState(
    () => words.length ? 0 : -1
  );
  useEffect(() => {
    setCurrentTime(0);
    setDuration(guessedDuration);
    setIsPlaying(false);
    setCurrentWordIndex(words.length ? 0 : -1);
  }, [words.length, alignment, guessedDuration]);
  const findWordIndex = useCallback(
    (time) => {
      if (!words.length) return -1;
      let lo = 0;
      let hi = words.length - 1;
      let answer = -1;
      while (lo <= hi) {
        const mid = Math.floor((lo + hi) / 2);
        const word = words[mid];
        if (time >= word.startTime && time < word.endTime) {
          answer = mid;
          break;
        }
        if (time < word.startTime) {
          hi = mid - 1;
        } else {
          lo = mid + 1;
        }
      }
      return answer;
    },
    [words]
  );
  const handleTimeUpdate = useCallback(
    (currentTime2) => {
      if (!words.length) return;
      const currentWord2 = currentWordIndex >= 0 && currentWordIndex < words.length ? words[currentWordIndex] : void 0;
      if (!currentWord2) {
        const found2 = findWordIndex(currentTime2);
        if (found2 !== -1) setCurrentWordIndex(found2);
        return;
      }
      let next = currentWordIndex;
      if (currentTime2 >= currentWord2.endTime && currentWordIndex + 1 < words.length) {
        while (next + 1 < words.length && currentTime2 >= words[next + 1].startTime) {
          next++;
        }
        if (currentTime2 < words[next].endTime) {
          setCurrentWordIndex(next);
          return;
        }
        setCurrentWordIndex(next);
        return;
      }
      if (currentTime2 < currentWord2.startTime) {
        const found2 = findWordIndex(currentTime2);
        if (found2 !== -1) setCurrentWordIndex(found2);
        return;
      }
      const found = findWordIndex(currentTime2);
      if (found !== -1 && found !== currentWordIndex) {
        setCurrentWordIndex(found);
      }
    },
    [findWordIndex, currentWordIndex, words]
  );
  useEffect(() => {
    handleTimeUpdateRef.current = handleTimeUpdate;
  }, [handleTimeUpdate]);
  useEffect(() => {
    onDurationChangeRef.current = onDurationChange ?? (() => {
    });
  }, [onDurationChange]);
  const stopRaf = useCallback(() => {
    if (rafRef.current != null) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    }
  }, []);
  const startRaf = useCallback(() => {
    if (rafRef.current != null) return;
    const tick = () => {
      const node = audioRef.current;
      if (!node) {
        rafRef.current = null;
        return;
      }
      const time = node.currentTime;
      setCurrentTime(time);
      handleTimeUpdateRef.current(time);
      if (Number.isFinite(node.duration) && node.duration > 0) {
        setDuration((prev) => {
          if (!prev) {
            onDurationChangeRef.current(node.duration);
            return node.duration;
          }
          return prev;
        });
      }
      rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);
  }, [audioRef]);
  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;
    const syncPlayback = () => setIsPlaying(!audio.paused);
    const syncTime = () => setCurrentTime(audio.currentTime);
    const syncDuration = () => setDuration(Number.isFinite(audio.duration) ? audio.duration : 0);
    const handlePlay = () => {
      syncPlayback();
      startRaf();
      onPlay?.();
    };
    const handlePause = () => {
      syncPlayback();
      syncTime();
      stopRaf();
      onPause?.();
    };
    const handleEnded = () => {
      syncPlayback();
      syncTime();
      stopRaf();
      onEnded?.();
    };
    const handleTimeUpdate2 = () => {
      syncTime();
      onTimeUpdate?.(audio.currentTime);
    };
    const handleSeeked = () => {
      syncTime();
      handleTimeUpdateRef.current(audio.currentTime);
    };
    const handleDuration = () => {
      syncDuration();
      onDurationChange?.(audio.duration);
    };
    syncPlayback();
    syncTime();
    syncDuration();
    if (!audio.paused) {
      startRaf();
    } else {
      stopRaf();
    }
    audio.addEventListener("play", handlePlay);
    audio.addEventListener("pause", handlePause);
    audio.addEventListener("ended", handleEnded);
    audio.addEventListener("timeupdate", handleTimeUpdate2);
    audio.addEventListener("seeked", handleSeeked);
    audio.addEventListener("durationchange", handleDuration);
    audio.addEventListener("loadedmetadata", handleDuration);
    return () => {
      stopRaf();
      audio.removeEventListener("play", handlePlay);
      audio.removeEventListener("pause", handlePause);
      audio.removeEventListener("ended", handleEnded);
      audio.removeEventListener("timeupdate", handleTimeUpdate2);
      audio.removeEventListener("seeked", handleSeeked);
      audio.removeEventListener("durationchange", handleDuration);
      audio.removeEventListener("loadedmetadata", handleDuration);
    };
  }, [
    audioRef,
    startRaf,
    stopRaf,
    onPlay,
    onPause,
    onEnded,
    onTimeUpdate,
    onDurationChange
  ]);
  const seekToTime = useCallback(
    (time) => {
      const node = audioRef.current;
      if (!node) return;
      setCurrentTime(time);
      node.currentTime = time;
      handleTimeUpdateRef.current(time);
    },
    [audioRef]
  );
  const seekToWord = useCallback(
    (word) => {
      const target = typeof word === "number" ? words[word] : word;
      if (!target) return;
      seekToTime(target.startTime);
    },
    [seekToTime, words]
  );
  const play = useCallback(() => {
    const audio = audioRef.current;
    if (!audio) return;
    if (audio.paused) {
      void audio.play();
    }
  }, [audioRef]);
  const pause = useCallback(() => {
    const audio = audioRef.current;
    if (audio && !audio.paused) {
      audio.pause();
    }
  }, [audioRef]);
  const startScrubbing = useCallback(() => {
    setIsScrubbing(true);
    stopRaf();
  }, [stopRaf]);
  const endScrubbing = useCallback(() => {
    setIsScrubbing(false);
    const node = audioRef.current;
    if (node && !node.paused) {
      startRaf();
    }
  }, [audioRef, startRaf]);
  const currentWord = currentWordIndex >= 0 && currentWordIndex < words.length ? words[currentWordIndex] : null;
  const currentSegmentIndex = currentWord?.segmentIndex ?? -1;
  const spokenSegments = useMemo(() => {
    if (!segments.length || currentSegmentIndex <= 0) return [];
    return segments.slice(0, currentSegmentIndex);
  }, [segments, currentSegmentIndex]);
  const unspokenSegments = useMemo(() => {
    if (!segments.length) return [];
    if (currentSegmentIndex === -1) return segments;
    if (currentSegmentIndex + 1 >= segments.length) return [];
    return segments.slice(currentSegmentIndex + 1);
  }, [segments, currentSegmentIndex]);
  return {
    segments,
    words,
    spokenSegments,
    unspokenSegments,
    currentWord,
    currentSegmentIndex,
    currentWordIndex,
    seekToTime,
    seekToWord,
    audioRef,
    isPlaying,
    isScrubbing,
    duration,
    currentTime,
    play,
    pause,
    startScrubbing,
    endScrubbing
  };
}
export {
  useTranscriptViewer
};
