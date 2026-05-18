import { useCallback, useEffect, useRef, useState } from "react";
import { DeepgramClient } from "@deepgram/sdk";

const DEEPGRAM_API_KEY = import.meta.env.VITE_DEEPGRAM_API_KEY as string;

export interface UseVoiceInputApi {
  /** Live transcript text from Deepgram. */
  transcript: string;
  /** True while recording is active. */
  isRecording: boolean;
  /** Error message if something went wrong, null otherwise. */
  error: string | null;
  /** Start recording from microphone. */
  startRecording: () => Promise<void>;
  /** Stop recording. */
  stopRecording: () => void;
  /** Clear the transcript (called when message is sent). */
  clearTranscript: () => void;
}

export function useVoiceInput(): UseVoiceInputApi {
  const [transcript, setTranscript] = useState("");
  const [isRecording, setIsRecording] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const connectionRef = useRef<any>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);

  const stopRecording = useCallback(() => {
    // Stop MediaRecorder first to prevent new data events
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== "inactive") {
      mediaRecorderRef.current.stop();
    }
    mediaRecorderRef.current = null;

    // Stop media stream tracks
    if (mediaStreamRef.current) {
      mediaStreamRef.current.getTracks().forEach((track) => track.stop());
      mediaStreamRef.current = null;
    }

    // Close Deepgram connection
    if (connectionRef.current) {
      try {
        connectionRef.current.close();
      } catch {
        // Ignore close errors
      }
      connectionRef.current = null;
    }

    setIsRecording(false);
  }, []);

  const startRecording = useCallback(async () => {
    console.log("[Deepgram] startRecording called");
    setError(null);
    // Don't clear transcript - we accumulate

    try {
      // Get microphone access
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      mediaStreamRef.current = stream;

      // Create Deepgram client
      const deepgram = new DeepgramClient({ apiKey: DEEPGRAM_API_KEY });

      // Connect to Deepgram streaming endpoint
      const connection = await deepgram.listen.v1.connect({
        model: "nova-3",
        language: "en-US",
        smart_format: "true",
        interim_results: "true",
        Authorization: `Token ${DEEPGRAM_API_KEY}`,
      });
      connectionRef.current = connection;

      let accumulatedTranscript = "";

      // Handle transcript messages
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
        console.log("[Deepgram] Connection closed");
        setIsRecording(false);
      });

      // Initiate the WebSocket connection and wait for it to open
      connection.connect();
      await connection.waitForOpen();
      console.log("[Deepgram] Connection ready");

      // Set up MediaRecorder and start recording
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

      mediaRecorder.start(100); // Collect data every 100ms
      setIsRecording(true);
    } catch (err) {
      console.error("[Deepgram] Failed to start recording:", err);
      setError("Failed to access microphone");
      stopRecording();
    }
  }, [stopRecording]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      stopRecording();
    };
  }, [stopRecording]);

  const clearTranscript = useCallback(() => {
    setTranscript("");
  }, []);

  return { transcript, isRecording, error, startRecording, stopRecording, clearTranscript };
}
