/**
 * Voice settings store
 *
 * Simple global state for sharing voice settings between Settings page and
 * voice input hooks. The Settings page writes to this store when the user
 * saves voice settings, and useVoiceInput reads from it to determine the
 * active provider.
 */

import type { VoiceProvider } from "./useVoiceInput";

export interface VoiceSettings {
  provider: VoiceProvider;
  whisperlivekitUrl: string;
  whisperlivekitLanguage: string;
  whisperlivekitModel: string;
  whisperlivekitAutostart: boolean;
}

/** Default voice settings */
const DEFAULT_VOICE_SETTINGS: VoiceSettings = {
  provider: "whisperlivekit",
  whisperlivekitUrl: "ws://localhost:8000/asr",
  whisperlivekitLanguage: "auto",
  whisperlivekitModel: "base",
  whisperlivekitAutostart: true,
};

/** Global voice settings store */
let voiceSettings: VoiceSettings = { ...DEFAULT_VOICE_SETTINGS };

/** Listeners for voice settings changes */
const listeners = new Set<(settings: VoiceSettings) => void>();

/**
 * Get current voice settings
 */
export function getVoiceSettings(): VoiceSettings {
  return voiceSettings;
}

/**
 * Update voice settings and notify all listeners
 */
export function setVoiceSettings(settings: Partial<VoiceSettings>): void {
  voiceSettings = { ...voiceSettings, ...settings };
  listeners.forEach((listener) => listener(voiceSettings));
}

/**
 * Subscribe to voice settings changes
 */
export function subscribeVoiceSettings(listener: (settings: VoiceSettings) => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
