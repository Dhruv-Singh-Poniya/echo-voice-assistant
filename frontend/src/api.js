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

export async function getDueReminders() {
  const res = await fetch("/api/reminders/due");
  return res.json();
}

export async function resetConversation() {
  await fetch("/api/reset", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: SESSION_ID }),
  });
}
