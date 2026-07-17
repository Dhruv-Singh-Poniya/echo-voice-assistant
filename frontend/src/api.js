// Thin wrapper around the backend API. All paths are same-origin thanks to
// the Vite dev proxy (see vite.config.js).

const SESSION_ID = "web-session";

export async function getHealth() {
  const res = await fetch("/api/health");
  return res.json();
}

export async function sendVoice(audioBlob) {
  const form = new FormData();
  form.append("session_id", SESSION_ID);
  form.append("audio", audioBlob, "recording.webm");
  const res = await fetch("/api/voice", { method: "POST", body: form });
  if (!res.ok) throw new Error((await res.text()) || "Voice request failed");
  return res.json();
}

export async function sendText(text) {
  const res = await fetch("/api/text", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: SESSION_ID, text, speak: true }),
  });
  if (!res.ok) throw new Error((await res.text()) || "Text request failed");
  return res.json();
}

// STT only — returns the transcript fast so the UI can acknowledge the
// command while the (slower) agent + TTS work happens via sendText.
export async function transcribeVoice(audioBlob) {
  const form = new FormData();
  form.append("session_id", SESSION_ID);
  form.append("audio", audioBlob, "recording.webm");
  const res = await fetch("/api/transcribe", { method: "POST", body: form });
  if (!res.ok) throw new Error((await res.text()) || "Transcription failed");
  return res.json();
}

// Short spoken "Got it." in the assistant's voice, served from cache.
export async function getAck() {
  const res = await fetch("/api/ack");
  return res.json();
}

export async function getDueReminders() {
  const res = await fetch("/api/reminders/due");
  return res.json();
}

export async function getNowPlaying() {
  const res = await fetch("/api/now-playing");
  return res.json();
}

export async function resetConversation() {
  await fetch("/api/reset", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: SESSION_ID }),
  });
}
