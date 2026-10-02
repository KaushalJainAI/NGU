import { useCallback, useRef, useState } from "react";
import { assistantAPI } from "@/lib/api/assistant";
import { toWav16kMono } from "@/lib/audio";

/**
 * Voice input via MediaRecorder + self-hosted transcription (AP11: "say your
 * shopping list" — one utterance becomes one cart proposal, confirmed once).
 *
 * Replaces the old browser Web Speech API (unreliable, Chrome/Edge-only, weak on
 * Hindi/Hinglish). Records audio in-browser, converts it to 16 kHz mono WAV, and
 * POSTs it to /assistant/transcribe/, which transcribes it server-side (Voxtral
 * over OpenRouter, or a self-hosted whisper.cpp container — the backend picks;
 * nothing here is provider-specific). The resulting text is handed
 * back via `onTranscript`, then flows through the normal chat path as if typed.
 *
 * Works in every browser with getUserMedia + MediaRecorder (incl. Firefox/Safari).
 *
 * AP11 behaviour:
 * - Silence auto-stop: a WebAudio level meter watches the mic and ends the
 *   recording after ~1.5 s of quiet, so one tap starts and speaking pace stops.
 *   A 30 s hard cap bounds uploads on noisy lines.
 * - Failures are VISIBLE via `error` (mic denied / transcription failed /
 *   nothing heard) — never swallowed. The widget toasts them.
 */

const isSupported = (): boolean =>
  typeof navigator !== "undefined" &&
  !!navigator.mediaDevices?.getUserMedia &&
  typeof MediaRecorder !== "undefined";

const SILENCE_MS = 1500;
const MAX_MS = 30_000;
// RMS below this counts as quiet (tuned for speech vs room noise).
const QUIET_RMS = 0.015;

export type VoiceError = "mic-denied" | "transcribe-failed" | "nothing-heard" | null;

interface UseVoiceInput {
  supported: boolean;
  recording: boolean;
  transcribing: boolean;
  error: VoiceError;
  clearError: () => void;
  start: () => Promise<void>;
  stop: () => void;
}

export function useVoiceInput(
  onTranscript: (text: string) => void,
  getLanguage: () => string
): UseVoiceInput {
  const [recording, setRecording] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const [error, setError] = useState<VoiceError>(null);

  // Keep the latest callbacks in refs so start/stop can stay stable (avoids
  // re-subscribing the widget's external-open effect on every render).
  const onTranscriptRef = useRef(onTranscript);
  const getLanguageRef = useRef(getLanguage);
  onTranscriptRef.current = onTranscript;
  getLanguageRef.current = getLanguage;

  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const streamRef = useRef<MediaStream | null>(null);
  const stoppedRef = useRef(false);
  // Owned by start(); torn down with the stream.
  const audioCtxRef = useRef<AudioContext | null>(null);
  const meterTimerRef = useRef<number | null>(null);

  const clearError = useCallback(() => setError(null), []);

  const releaseStream = useCallback(() => {
    if (meterTimerRef.current !== null) {
      window.clearInterval(meterTimerRef.current);
      meterTimerRef.current = null;
    }
    if (audioCtxRef.current) {
      audioCtxRef.current.close().catch(() => undefined);
      audioCtxRef.current = null;
    }
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    recorderRef.current = null;
    chunksRef.current = [];
  }, []);

  // Runs EXACTLY once per utterance, from recorder.onstop. Stopping the
  // recorder (manual tap or silence timer) only ends capture; this does the
  // transcription. `stoppedRef` guards the stop path, not this function.
  const transcribeNow = useCallback(async () => {
    const mime = recorderRef.current?.mimeType || "audio/webm";
    const blob = new Blob(chunksRef.current, { type: mime });
    releaseStream();
    setRecording(false);
    if (!blob.size) {
      setError("nothing-heard");
      return;
    }
    setTranscribing(true);
    try {
      const wav = await toWav16kMono(blob);
      const { transcript } = await assistantAPI.transcribe(wav, getLanguageRef.current());
      if (transcript) onTranscriptRef.current(transcript);
      else setError("nothing-heard");
    } catch {
      setError("transcribe-failed");
    } finally {
      setTranscribing(false);
    }
  }, [releaseStream]);

  // Idempotent stop: first call ends capture (onstop transcribes); later calls
  // (silence timer racing a tap) are no-ops.
  const finish = useCallback(() => {
    if (stoppedRef.current) return;
    stoppedRef.current = true;
    const rec = recorderRef.current;
    if (rec && rec.state !== "inactive") rec.stop();
    else void transcribeNow();
  }, [transcribeNow]);

  const start = useCallback(async () => {
    if (recorderRef.current) return; // already recording
    setError(null);
    stoppedRef.current = false;
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      setRecording(false);
      setError("mic-denied");
      return;
    }
    streamRef.current = stream;
    const recorder = new MediaRecorder(stream);
    chunksRef.current = [];

    recorder.ondataavailable = (e) => {
      if (e.data.size) chunksRef.current.push(e.data);
    };
    recorder.onstop = () => {
      void transcribeNow();
    };

    recorder.start(250);
    recorderRef.current = recorder;
    setRecording(true);

    // Silence watchdog: stop ~1.5 s after speech ends; hard cap at 30 s.
    try {
      const Ctx = window.AudioContext ??
        (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
      if (Ctx) {
        const ctx = new Ctx();
        audioCtxRef.current = ctx;
        const src = ctx.createMediaStreamSource(stream);
        const analyser = ctx.createAnalyser();
        analyser.fftSize = 1024;
        src.connect(analyser);
        const buf = new Float32Array(analyser.fftSize);
        let quietSince: number | null = null;
        const startedAt = Date.now();
        meterTimerRef.current = window.setInterval(() => {
          analyser.getFloatTimeDomainData(buf);
          let sum = 0;
          for (let i = 0; i < buf.length; i++) sum += buf[i] * buf[i];
          const rms = Math.sqrt(sum / buf.length);
          const now = Date.now();
          if (rms < QUIET_RMS) {
            if (quietSince === null) quietSince = now;
            else if (now - quietSince >= SILENCE_MS) void finish();
          } else {
            quietSince = null;
          }
          if (now - startedAt >= MAX_MS) void finish();
        }, 200);
      }
    } catch {
      // No WebAudio (very old browser): manual stop still works.
    }
  }, [finish, releaseStream]);

  const stop = useCallback(() => {
    void finish();
  }, [finish]);

  return { supported: isSupported(), recording, transcribing, error, clearError, start, stop };
}
