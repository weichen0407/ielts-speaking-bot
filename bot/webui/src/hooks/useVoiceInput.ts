import { useCallback, useEffect, useRef, useState } from "react";
import { DeepgramClient } from "@deepgram/sdk";
import { useWhisperLiveKit } from "./useWhisperLiveKit";
import { getVoiceSettings, subscribeVoiceSettings } from "./useVoiceSettings";

const DEEPGRAM_API_KEY = import.meta.env.VITE_DEEPGRAM_API_KEY as string;

/** Voice input provider type */
export type VoiceProvider = "deepgram" | "whisperlivekit";

/** Configuration for voice input */
export interface VoiceInputConfig {
  /** Provider to use: "deepgram" (cloud) or "whisperlivekit" (local) */
  provider?: VoiceProvider;
  /** WhisperLiveKit WebSocket URL (for whisperlivekit provider) */
  whisperLiveKitUrl?: string;
  /** Language code for WhisperLiveKit */
  whisperLiveKitLanguage?: string;
}

export interface UseVoiceInputApi {
  /** Live transcript text from the provider. */
  transcript: string;
  /** True while recording is active. */
  isRecording: boolean;
  /** True while final audio is being processed. */
  isProcessing: boolean;
  /** Error message if something went wrong, null otherwise. */
  error: string | null;
  /** Provider or server status text. */
  status: string;
  /** Timestamp when recording started, in milliseconds. */
  recordingStartedAt: number | null;
  /** Start recording from microphone. */
  startRecording: () => Promise<void>;
  /** Stop recording. */
  stopRecording: () => void;
  /** Clear the transcript (called when message is sent). */
  clearTranscript: () => void;
  /** Current provider in use */
  provider: VoiceProvider;
}

function getGlobalProvider(): VoiceProvider | null {
  const envProvider = import.meta.env.VITE_VOICE_PROVIDER as string | undefined;
  if (envProvider === "whisperlivekit" || envProvider === "deepgram") return envProvider;
  if (typeof window === "undefined") return null;
  const globalProvider = (window as unknown as { __NANOBOT_VOICE_PROVIDER?: string }).__NANOBOT_VOICE_PROVIDER;
  return globalProvider === "whisperlivekit" || globalProvider === "deepgram" ? globalProvider : null;
}

function getGlobalWlkUrl(): string | null {
  if (typeof window === "undefined") return null;
  return (window as unknown as { __NANOBOT_WLK_URL?: string }).__NANOBOT_WLK_URL ?? null;
}

function getGlobalWlkLanguage(): string | null {
  if (typeof window === "undefined") return null;
  return (window as unknown as { __NANOBOT_WLK_LANGUAGE?: string }).__NANOBOT_WLK_LANGUAGE ?? null;
}

export function useVoiceInput(config?: VoiceInputConfig): UseVoiceInputApi {
  const [voiceSettings, setVoiceSettingsState] = useState(() => getVoiceSettings());
  const [transcript, setTranscript] = useState("");
  const [isRecording, setIsRecording] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);
  const [status, setStatus] = useState("");
  const [recordingStartedAt, setRecordingStartedAt] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => subscribeVoiceSettings(setVoiceSettingsState), []);

  const provider = config?.provider ?? getGlobalProvider() ?? voiceSettings.provider;
  const wlkUrl = config?.whisperLiveKitUrl ?? getGlobalWlkUrl() ?? voiceSettings.whisperlivekitUrl;
  const wlkLanguage = config?.whisperLiveKitLanguage ?? getGlobalWlkLanguage() ?? voiceSettings.whisperlivekitLanguage;

  // Deepgram refs
  const connectionRef = useRef<any>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);

  // WhisperLiveKit hook
  const wlk = useWhisperLiveKit({
    wsUrl: wlkUrl,
    language: wlkLanguage,
  });

  // Sync WhisperLiveKit state to the provider-agnostic API
  useEffect(() => {
    if (provider === "whisperlivekit") setTranscript(wlk.transcript);
  }, [wlk.transcript, provider]);

  useEffect(() => {
    if (provider === "whisperlivekit") setError(wlk.error);
  }, [wlk.error, provider]);

  useEffect(() => {
    if (provider !== "whisperlivekit") return;
    setIsRecording(wlk.isRecording);
    setIsProcessing(wlk.isProcessing);
    setStatus(wlk.status);
    setRecordingStartedAt(wlk.recordingStartedAt);
  }, [wlk.isRecording, wlk.isProcessing, wlk.recordingStartedAt, wlk.status, provider]);

  const stopWlkRecording = wlk.stopRecording;
  const startWlkRecording = wlk.startRecording;
  const clearWlkTranscript = wlk.clearTranscript;

  const stopRecording = useCallback(() => {
    if (provider === "whisperlivekit") {
      stopWlkRecording();
      return;
    }

    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== "inactive") {
      mediaRecorderRef.current.stop();
    }
    mediaRecorderRef.current = null;

    if (mediaStreamRef.current) {
      mediaStreamRef.current.getTracks().forEach((track) => track.stop());
      mediaStreamRef.current = null;
    }

    if (connectionRef.current) {
      try {
        connectionRef.current.close();
      } catch {
        // Ignore close errors
      }
      connectionRef.current = null;
    }

    setIsRecording(false);
    setIsProcessing(false);
    setStatus("");
    setRecordingStartedAt(null);
  }, [provider, stopWlkRecording]);

  const startRecording = useCallback(async () => {
    if (provider === "whisperlivekit") {
      setError(null);
      await startWlkRecording();
      return;
    }

    setError(null);
    setStatus("Connecting to Deepgram...");

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      mediaStreamRef.current = stream;

      const deepgram = new DeepgramClient({ apiKey: DEEPGRAM_API_KEY });

      const connection = await deepgram.listen.v1.connect({
        model: "nova-3",
        language: "en-US",
        smart_format: "true",
        interim_results: "true",
        Authorization: `Token ${DEEPGRAM_API_KEY}`,
      });
      connectionRef.current = connection;

      let accumulatedTranscript = "";

      connection.on("message", (msg: any) => {
        if (msg.type === "Results") {
          const text = msg.channel?.alternatives?.[0]?.transcript ?? "";
          if (text) {
            const isFinal = msg.is_final ?? false;
            if (isFinal) {
              accumulatedTranscript += (accumulatedTranscript ? " " : "") + text;
              setTranscript(accumulatedTranscript);
            }
          }
        }
      });

      connection.on("error", (err: any) => {
        console.error("[Deepgram] Connection error:", err);
        setError("Connection error occurred");
        stopRecording();
      });

      connection.on("close", () => {
        setIsRecording(false);
        setStatus("");
        setRecordingStartedAt(null);
      });

      connection.connect();
      await connection.waitForOpen();

      const mimeType = MediaRecorder.isTypeSupported("audio/webm")
        ? "audio/webm"
        : MediaRecorder.isTypeSupported("audio/ogg")
          ? "audio/ogg"
          : "audio/wav";

      const mediaRecorder = new MediaRecorder(stream, { mimeType });
      mediaRecorderRef.current = mediaRecorder;

      mediaRecorder.ondataavailable = (e) => {
        if (e.data && e.data.size > 0 && connectionRef.current) {
          try {
            connectionRef.current.sendMedia(e.data);
          } catch (err) {
            console.error("[Deepgram] sendMedia error:", err);
          }
        }
      };

      mediaRecorder.start(100);
      setIsRecording(true);
      setIsProcessing(false);
      setStatus("Listening...");
      setRecordingStartedAt(Date.now());
    } catch (err) {
      console.error("[Deepgram] Failed to start recording:", err);
      setError("Failed to access microphone");
      stopRecording();
      throw err;
    }
  }, [provider, startWlkRecording, stopRecording]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      stopRecording();
    };
  }, [stopRecording]);

  const clearTranscript = useCallback(() => {
    setTranscript("");
    clearWlkTranscript();
  }, [clearWlkTranscript]);

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
    provider,
  };
}
