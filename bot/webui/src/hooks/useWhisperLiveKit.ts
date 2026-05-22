/**
 * WhisperLiveKit Client Hook
 *
 * Provides real-time speech transcription using WhisperLiveKit server.
 * Audio flow: getUserMedia -> AudioWorklet -> Web Worker (resample) -> WebSocket -> WhisperLiveKit
 */

import { useCallback, useEffect, useRef, useState } from "react";

export interface UseWhisperLiveKitApi {
  /** Live transcript text from WhisperLiveKit. */
  transcript: string;
  /** True while recording is active. */
  isRecording: boolean;
  /** True while waiting for server to finish processing. */
  isProcessing: boolean;
  /** Error message if something went wrong, null otherwise. */
  error: string | null;
  /** Status message from the server. */
  status: string;
  /** Timestamp when recording started, in milliseconds. */
  recordingStartedAt: number | null;
  /** Start recording from microphone. */
  startRecording: () => Promise<void>;
  /** Stop recording. */
  stopRecording: () => void;
  /** Clear the transcript (called when message is sent). */
  clearTranscript: () => void;
  /** Audio analyser node for waveform visualization. */
  analyser: AnalyserNode | null;
  /** Audio context for waveform visualization. */
  audioContext: AudioContext | null;
}

interface WhisperLiveKitConfig {
  /** WebSocket URL for WhisperLiveKit server (default: ws://localhost:8000/asr) */
  wsUrl?: string;
  /** Language code for transcription (default: auto) */
  language?: string;
}

interface FrontData {
  type?: "config" | "ready_to_stop";
  status?: "active_transcription" | "no_audio_detected";
  useAudioWorklet?: boolean;
  lines?: Array<{
    speaker: number;
    text: string;
    start: string;
    end: string;
  }>;
  buffer_transcription?: string;
  remaining_time_transcription?: number;
}

const DEFAULT_WS_URL = "ws://localhost:8000/asr";
const RECORDING_SAMPLE_RATE = 48000;
const TARGET_SAMPLE_RATE = 16000;
const CONFIG_TIMEOUT_MS = 8000;

function appendQuery(url: string, params: Record<string, string>): string {
  const parsed = new URL(url, window.location.href);
  for (const [key, value] of Object.entries(params)) {
    parsed.searchParams.set(key, value);
  }
  return parsed.toString();
}

export function useWhisperLiveKit(config?: WhisperLiveKitConfig): UseWhisperLiveKitApi {
  const [transcript, setTranscript] = useState("");
  const [isRecording, setIsRecording] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<string>("");
  const [recordingStartedAt, setRecordingStartedAt] = useState<number | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const workletNodeRef = useRef<AudioWorkletNode | null>(null);
  const recorderWorkerRef = useRef<Worker | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const serverUseAudioWorkletRef = useRef<boolean>(true);
  const isUserClosingRef = useRef(false);
  const isWaitingForStopRef = useRef(false);
  const isRecordingRef = useRef(false);
  const accumulatedLinesRef = useRef<string[]>([]);

  const setRecordingActive = useCallback((active: boolean) => {
    isRecordingRef.current = active;
    setIsRecording(active);
    setRecordingStartedAt(active ? Date.now() : null);
  }, []);

  const cleanupAudio = useCallback(() => {
    if (mediaRecorderRef.current) {
      try {
        if (mediaRecorderRef.current.state !== "inactive") mediaRecorderRef.current.stop();
      } catch { /* ignore */ }
      mediaRecorderRef.current = null;
    }

    if (mediaStreamRef.current) {
      mediaStreamRef.current.getTracks().forEach((track) => track.stop());
      mediaStreamRef.current = null;
    }

    if (workletNodeRef.current) {
      try {
        workletNodeRef.current.port.onmessage = null;
        workletNodeRef.current.disconnect();
      } catch { /* ignore */ }
      workletNodeRef.current = null;
    }

    if (recorderWorkerRef.current) {
      recorderWorkerRef.current.terminate();
      recorderWorkerRef.current = null;
    }

    if (analyserRef.current) {
      analyserRef.current = null;
    }

    if (audioContextRef.current) {
      const ac = audioContextRef.current;
      audioContextRef.current = null;
      void ac.close().catch(() => undefined);
    }
  }, []);

  const closeSocket = useCallback(() => {
    const ws = wsRef.current;
    wsRef.current = null;
    if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
      ws.close();
    }
  }, []);

  const stopRecording = useCallback(() => {
    if (!isRecordingRef.current && !wsRef.current) return;

    isUserClosingRef.current = true;
    isWaitingForStopRef.current = true;

    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      if (serverUseAudioWorkletRef.current) {
        ws.send(new ArrayBuffer(0));
      } else {
        ws.send(new Blob([], { type: "audio/webm" }));
      }
      setStatus("Processing final audio...");
      setIsProcessing(true);
    } else {
      isWaitingForStopRef.current = false;
      setIsProcessing(false);
    }

    cleanupAudio();
    setRecordingActive(false);
  }, [cleanupAudio, setRecordingActive]);

  const wsUrl = config?.wsUrl ?? DEFAULT_WS_URL;
  const language = config?.language ?? "auto";

  const startRecording = useCallback(async () => {
    if (isRecordingRef.current) return;

    setError(null);
    setTranscript("");
    setStatus("Connecting to WhisperLiveKit...");
    setIsProcessing(false);
    accumulatedLinesRef.current = [];
    isUserClosingRef.current = false;
    isWaitingForStopRef.current = false;

    const audioContext = new AudioContext({ sampleRate: RECORDING_SAMPLE_RATE });
    audioContextRef.current = audioContext;

    try {
      const ws = new WebSocket(appendQuery(wsUrl, { language, mode: "full" }));
      wsRef.current = ws;

      await new Promise<void>((resolve, reject) => {
        let settled = false;
        const timeout = window.setTimeout(() => {
          if (settled) return;
          settled = true;
          reject(new Error("WhisperLiveKit did not send configuration"));
        }, CONFIG_TIMEOUT_MS);

        const settle = (fn: () => void) => {
          if (settled) return;
          settled = true;
          window.clearTimeout(timeout);
          fn();
        };

        ws.onopen = () => {
          setStatus("Waiting for WhisperLiveKit configuration...");
        };

        ws.onerror = () => {
          settle(() => reject(new Error("Could not connect to WhisperLiveKit")));
        };

        ws.onclose = () => {
          const wasRecording = isRecordingRef.current;
          setStatus("");
          setRecordingActive(false);
          cleanupAudio();

          if (isUserClosingRef.current && isWaitingForStopRef.current) {
            setStatus("Processing final audio...");
            return;
          }

          if (wasRecording) {
            setError("WhisperLiveKit connection closed unexpectedly");
          }
          setIsProcessing(false);
          settle(() => reject(new Error("WhisperLiveKit connection closed")));
        };

        ws.onmessage = (event) => {
          try {
            const data: FrontData = JSON.parse(event.data as string);

            if (data.type === "config") {
              serverUseAudioWorkletRef.current = data.useAudioWorklet ?? true;
              setStatus(data.useAudioWorklet
                ? "Using AudioWorklet PCM streaming"
                : "Using MediaRecorder streaming");
              settle(resolve);
              return;
            }

            if (data.type === "ready_to_stop") {
              isWaitingForStopRef.current = false;
              isUserClosingRef.current = false;
              setStatus("Finished");
              setIsProcessing(false);
              closeSocket();
              return;
            }

            if (data.status === "active_transcription") {
              const committed = data.lines?.map((line) => line.text).filter(Boolean) ?? [];
              if (committed.length > 0) {
                accumulatedLinesRef.current = committed;
                setTranscript(committed.join(" "));
              } else if (data.buffer_transcription) {
                const prefix = accumulatedLinesRef.current.join(" ");
                setTranscript([prefix, data.buffer_transcription].filter(Boolean).join(" "));
              }
              setStatus("Listening...");
            } else if (data.status === "no_audio_detected") {
              setStatus("No audio detected...");
            }
          } catch {
            setError("Received an invalid WhisperLiveKit message");
          }
        };
      });

      const openWs = wsRef.current;
      if (!openWs || openWs.readyState !== WebSocket.OPEN) throw new Error("WhisperLiveKit connection is not open");

      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      mediaStreamRef.current = stream;
      const source = audioContext.createMediaStreamSource(stream);

      // Create analyser for waveform visualization
      const analyser = audioContext.createAnalyser();
      analyser.fftSize = 256;
      analyserRef.current = analyser;
      source.connect(analyser);

      if (serverUseAudioWorkletRef.current && audioContext.audioWorklet) {
        try {
          await audioContext.audioWorklet.addModule("/web/pcm_worklet.js");
        } catch {
          serverUseAudioWorkletRef.current = false;
        }
      }

      if (serverUseAudioWorkletRef.current) {
        const workletNode = new AudioWorkletNode(audioContext, "pcm-forwarder", {
          numberOfInputs: 1,
          numberOfOutputs: 0,
          channelCount: 1,
        });
        workletNodeRef.current = workletNode;
        source.connect(workletNode);

        const worker = new Worker("/web/recorder_worker.js");
        recorderWorkerRef.current = worker;
        worker.postMessage({
          command: "init",
          config: {
            sampleRate: RECORDING_SAMPLE_RATE,
            targetSampleRate: TARGET_SAMPLE_RATE,
          },
        });

        workletNode.port.onmessage = (e) => {
          const data = e.data;
          const buffer = data instanceof ArrayBuffer ? data : data.buffer;
          worker.postMessage({ command: "record", buffer }, [buffer]);
        };

        worker.onmessage = (e) => {
          if (openWs.readyState === WebSocket.OPEN) openWs.send(e.data.buffer);
        };
      } else {
        let mimeType = "audio/webm";
        if (!MediaRecorder.isTypeSupported("audio/webm")) {
          mimeType = MediaRecorder.isTypeSupported("audio/ogg") ? "audio/ogg" : "audio/wav";
        }
        const recorder = new MediaRecorder(stream, { mimeType });
        mediaRecorderRef.current = recorder;
        recorder.ondataavailable = (e) => {
          if (e.data && e.data.size > 0 && openWs.readyState === WebSocket.OPEN) openWs.send(e.data);
        };
        recorder.onerror = () => setError("Browser audio recorder failed");
        recorder.start(100);
      }

      setRecordingActive(true);
      setIsProcessing(false);
      setStatus("Listening...");
    } catch (err) {
      cleanupAudio();
      closeSocket();
      setRecordingActive(false);
      setIsProcessing(false);
      setStatus("");
      const message = err instanceof Error ? err.message : "Failed to start recording";
      setError(message);
      throw new Error(message);
    }
  }, [cleanupAudio, closeSocket, language, setRecordingActive, wsUrl]);

  useEffect(() => {
    return () => {
      cleanupAudio();
      closeSocket();
    };
  }, [cleanupAudio, closeSocket]);

  const clearTranscript = useCallback(() => {
    setTranscript("");
    accumulatedLinesRef.current = [];
  }, []);

  return {
    transcript,
    isRecording,
    isProcessing,
    error,
    status,
    recordingStartedAt,
    startRecording,
    stopRecording,
    clearTranscript,
    analyser: analyserRef.current,
    audioContext: audioContextRef.current,
  };
}
