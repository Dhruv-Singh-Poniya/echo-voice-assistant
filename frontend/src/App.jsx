import { useEffect, useRef, useState } from "react";
import { listenForSpeech } from "./listen.js";
import {
  getHealth,
  sendVoice,
  sendText,
  getDueReminders,
  resetConversation,
} from "./api.js";

const ACTION_LABELS = {
  add_todo: "▸ TODO.ADD",
  list_todos: "▸ TODO.LIST",
  complete_todo: "▸ TODO.DONE",
  add_note: "▸ NOTE.SAVE",
  list_notes: "▸ NOTE.LIST",
  set_reminder: "▸ TIMER.SET",
  list_reminders: "▸ TIMER.LIST",
  calculate: "▸ MATH.CALC",
  get_datetime: "▸ SYS.CLOCK",
  open_application: "▸ APP.LAUNCH",
  open_url: "▸ WEB.OPEN",
  get_system_info: "▸ SYS.INFO",
  run_command: "▸ SHELL.EXEC",
  web_search: "▸ NET.SEARCH",
};

const STATE_LABEL = {
  idle: "STANDBY",
  listening: "LISTENING",
  thinking: "PROCESSING",
  speaking: "RESPONDING",
};

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function Reactor({ state, onClick, disabled }) {
  const ticks = Array.from({ length: 60 });
  return (
    <button
      className={`reactor ${state}`}
      onClick={onClick}
      disabled={disabled}
      aria-label="Activate microphone"
    >
      <svg viewBox="0 0 300 300" className="reactor-svg" aria-hidden="true">
        <g className="r-ticks">
          {ticks.map((_, i) => (
            <line
              key={i}
              x1="150" y1="14" x2="150" y2={i % 5 === 0 ? "26" : "21"}
              transform={`rotate(${i * 6} 150 150)`}
              className={i % 5 === 0 ? "tick major" : "tick"}
            />
          ))}
        </g>
        <circle className="r-dashed" cx="150" cy="150" r="118" />
        <circle className="r-seg" cx="150" cy="150" r="98" />
        <circle className="r-seg2" cx="150" cy="150" r="82" />
        <g className="reticle">
          <line x1="150" y1="60" x2="150" y2="72" />
          <line x1="150" y1="228" x2="150" y2="240" />
          <line x1="60" y1="150" x2="72" y2="150" />
          <line x1="228" y1="150" x2="240" y2="150" />
        </g>
        <circle className="core-glow" cx="150" cy="150" r="58" />
        <circle className="core" cx="150" cy="150" r="52" />
        <circle className="core-in" cx="150" cy="150" r="22" />
      </svg>
      <div className="reactor-center">
        {state === "speaking" ? (
          <div className="wave"><i /><i /><i /><i /><i /></div>
        ) : (
          <span className="reactor-icon">{state === "listening" ? "◼" : "◉"}</span>
        )}
        <span className="reactor-state">{STATE_LABEL[state]}</span>
      </div>
    </button>
  );
}

export default function App() {
  const [messages, setMessages] = useState(() => {
    try {
      return JSON.parse(localStorage.getItem("echo_session") || "[]");
    } catch {
      return [];
    }
  });
  const [health, setHealth] = useState(null);
  const [busy, setBusy] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const [status, setStatus] = useState("");
  const [textInput, setTextInput] = useState("");
  const [reminders, setReminders] = useState([]);
  const [converse, setConverse] = useState(false);
  const [convListening, setConvListening] = useState(false);

  const audioRef = useRef(null);
  const scrollRef = useRef(null);
  const converseRef = useRef(false);
  const runningRef = useRef(false);
  const stopTurnRef = useRef(false);

  useEffect(() => {
    getHealth()
      .then(setHealth)
      .catch(() => setHealth({ ok: false, problems: ["Uplink to core failed."] }));
  }, []);

  useEffect(() => {
    const id = setInterval(async () => {
      try {
        const { due } = await getDueReminders();
        if (due?.length) setReminders((r) => [...r, ...due]);
      } catch {
        /* ignore */
      }
    }, 15000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, busy]);

  // Persist the visible chat across page refreshes.
  useEffect(() => {
    try {
      localStorage.setItem("echo_session", JSON.stringify(messages));
    } catch {
      /* storage full / disabled — ignore */
    }
  }, [messages]);

  const assistantName = health?.assistant_name || "Jarvis";
  const brandName = assistantName.toUpperCase();
  const model = health?.model || "—";
  const linkOk = health?.ok;

  // Rebrand the browser tab too.
  useEffect(() => {
    document.title = `${assistantName} — Voice Assistant`;
  }, [assistantName]);

  const orbState =
    convListening ? "listening" : busy ? "thinking" : speaking ? "speaking" : "idle";

  // Play the reply and RESOLVE when the audio finishes (so conversation mode
  // waits for Jarvis to stop talking before it listens again).
  function playReply(audioB64) {
    return new Promise((resolve) => {
      if (!audioB64) return resolve();
      const audio = new Audio("data:audio/mpeg;base64," + audioB64);
      audioRef.current = audio;
      setSpeaking(true);
      const end = () => {
        setSpeaking(false);
        resolve();
      };
      audio.onended = end;
      audio.onerror = end;
      audio.play().catch(end);
    });
  }

  function pushMessage(role, text, actions = []) {
    setMessages((m) => [...m, { role, text, actions, id: crypto.randomUUID() }]);
  }

  // Actions that start audio playing through the speakers — which would feed
  // back into the mic during hands-free mode and cause a loop.
  const MEDIA_ACTIONS = ["play_youtube", "open_url"];

  async function handleResult(result) {
    if (result.transcript) pushMessage("user", result.transcript);
    pushMessage("assistant", result.reply, result.actions);
    if (converseRef.current && (result.actions || []).some((a) => MEDIA_ACTIONS.includes(a))) {
      stopConverse();
      setStatus("hands-free paused — media is playing");
    }
    await playReply(result.audio);
  }

  // ---- One voice turn: tap once, speak, it auto-sends when you pause ----
  async function singleTurn() {
    if (busy || convListening) return;
    stopTurnRef.current = false;
    setConvListening(true);
    setStatus("listening — speak now");
    const blob = await listenForSpeech({ shouldStop: () => stopTurnRef.current });
    setConvListening(false);
    if (!blob) {
      setStatus("");
      return;
    }
    setBusy(true);
    setStatus("processing…");
    try {
      const result = await sendVoice(blob);
      setStatus("");
      await handleResult(result);
    } catch (e) {
      setStatus("");
      pushMessage("assistant", "⚠ " + e.message);
    } finally {
      setBusy(false);
    }
  }

  function onReactorClick() {
    if (busy) return;
    if (converse) {
      stopConverse();
      return;
    }
    if (convListening) {
      stopTurnRef.current = true; // tap again to stop early
      return;
    }
    singleTurn();
  }

  // ---- Hands-free conversation loop ----
  async function converseLoop() {
    if (runningRef.current) return;
    runningRef.current = true;
    try {
      while (converseRef.current) {
        setConvListening(true);
        setStatus("listening — speak now");
        const blob = await listenForSpeech({ shouldStop: () => !converseRef.current });
        setConvListening(false);
        if (!converseRef.current) break;
        if (!blob) {
          setStatus("");
          await sleep(250);
          continue;
        }
        setBusy(true);
        setStatus("processing…");
        try {
          const result = await sendVoice(blob);
          setStatus("");
          await handleResult(result);
        } catch (e) {
          setStatus("");
          pushMessage("assistant", "⚠ " + e.message);
        } finally {
          setBusy(false);
        }
        await sleep(250); // brief gap so it doesn't record its own reply tail
      }
    } finally {
      runningRef.current = false;
      setConvListening(false);
      setStatus("");
    }
  }

  function startConverse() {
    if (busy || converse) return;
    setConverse(true);
    converseRef.current = true;
    converseLoop();
  }
  function stopConverse() {
    setConverse(false);
    converseRef.current = false;
  }
  function toggleConverse() {
    converse ? stopConverse() : startConverse();
  }

  async function runText(text) {
    const t = (text || "").trim();
    if (!t || busy) return;
    setBusy(true);
    setStatus("processing…");
    try {
      const result = await sendText(t);
      setStatus("");
      await handleResult(result);
    } catch (err) {
      setStatus("");
      pushMessage("assistant", "⚠ " + err.message);
    } finally {
      setBusy(false);
    }
  }

  function submitText(e) {
    e.preventDefault();
    const text = textInput.trim();
    if (!text || busy) return;
    setTextInput("");
    runText(text);
  }

  async function handleReset() {
    await resetConversation();
    setMessages([]);
  }

  const hint =
    status ||
    (orbState === "idle"
      ? converse
        ? "◉ hands-free active — just talk"
        : "◉ tap core, type, or enable hands-free"
      : STATE_LABEL[orbState].toLowerCase());

  return (
    <div className="hud">
      <div className="grid" aria-hidden="true" />
      <div className="scan" aria-hidden="true" />
      <div className="vignette" aria-hidden="true" />

      <div className="frame">
        <span className="br tl" /><span className="br tr" /><span className="br bl" /><span className="br br-" />

        <header className="hud-top">
          <div className="wordmark">
            <span className="mono j">{brandName}</span>
            <span className={`link ${linkOk ? "ok" : "warn"}`}>
              <i /> {linkOk ? "LINK ESTABLISHED" : "AWAITING UPLINK"}
            </span>
          </div>
          <div className="telem">
            <span className="tel"><b>CORE</b> {model}</span>
            <button
              className={`ghost wake ${converse ? "on" : ""}`}
              onClick={toggleConverse}
              title="Hands-free conversation — Jarvis listens after every reply"
            >
              {converse ? "◉ HANDS-FREE" : "○ HANDS-FREE"}
            </button>
            <button className="ghost" onClick={handleReset} title="Purge conversation log">
              PURGE
            </button>
          </div>
        </header>

        {health && !health.ok && (
          <div className="alert error">
            <b>SYSTEM //</b> {health.problems?.join("  ·  ")}
          </div>
        )}
        {reminders.length > 0 && (
          <div className="alert warn">
            <span><b>ALERT //</b> {reminders.map((r) => r.text).join("  ·  ")}</span>
            <button className="ghost" onClick={() => setReminders([])}>DISMISS</button>
          </div>
        )}

        <div className="hud-body">
          <section className="stage">
            <div className="sys-strip mono" aria-hidden="true">
              {[["CORE POWER", 82], ["NEURAL LOAD", 61], ["COMMS LINK", 94]].map(([l, v]) => (
                <div className="meter" key={l}>
                  <span className="m-l">{l}</span>
                  <div className="m-bar"><i style={{ width: v + "%" }} /></div>
                  <span className="m-v">{v}%</span>
                </div>
              ))}
            </div>

            <div className="reactor-wrap">
              <Reactor state={orbState} onClick={onReactorClick} disabled={busy} />
              <div className="stage-status mono">{hint}</div>
            </div>

            <div className="readouts mono" aria-hidden="true">
              {[
                ["MODEL", (model.split(".").pop() || model).toUpperCase()],
                ["VOICE", "SYNTH ✓"],
                ["MODE", converse ? "HANDS-FREE" : "MANUAL"],
                ["ENCRYPT", "AES-256"],
                ["UPLINK", linkOk ? "SECURE" : "—"],
                ["STATE", STATE_LABEL[orbState]],
              ].map(([l, v]) => (
                <div className="ro" key={l}>
                  <span className="ro-l">{l}</span>
                  <span className="ro-v">{v}</span>
                </div>
              ))}
            </div>
          </section>

          <section className="log-panel">
            <div className="panel-head mono">
              <span>▣ CONVERSATION LOG</span>
              <span className="count">{messages.length} ENTRIES</span>
            </div>

            <div className="log" ref={scrollRef}>
              {messages.length === 0 && (
                <div className="log-empty mono">
                  <p>// {assistantName} online. Awaiting instruction.</p>
                  <p className="dim">tap the core and speak, or type below</p>
                  <p className="dim">enable HANDS-FREE for a natural back-and-forth</p>
                  <p className="dim">try: "open discord" · "what's 15% of 240?"</p>
                </div>
              )}
              {messages.map((m) => (
                <div key={m.id} className={`entry ${m.role}`}>
                  <span className="who mono">{m.role === "user" ? "YOU ▸" : `${brandName} ◂`}</span>
                  <div className="entry-body">
                    {m.actions?.length > 0 && (
                      <div className="tags mono">
                        {m.actions.map((a, i) => (
                          <span key={i} className="tag">{ACTION_LABELS[a] || a}</span>
                        ))}
                      </div>
                    )}
                    <div className="msg">{m.text}</div>
                  </div>
                </div>
              ))}
              {busy && (
                <div className="entry assistant">
                  <span className="who mono">{brandName} ◂</span>
                  <div className="entry-body"><div className="dots"><i /><i /><i /></div></div>
                </div>
              )}
            </div>

            <form className="cmd" onSubmit={submitText}>
              <span className="prompt mono">›</span>
              <input
                value={textInput}
                onChange={(e) => setTextInput(e.target.value)}
                placeholder="type a command…"
                disabled={busy}
              />
              <button type="submit" className="exec mono" disabled={busy || !textInput.trim()}>
                SEND
              </button>
            </form>
          </section>
        </div>
      </div>
    </div>
  );
}
