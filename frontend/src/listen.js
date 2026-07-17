// Record from the mic and auto-stop when the user stops talking (silence
// detection via Web Audio). Resolves with an audio Blob (or null if no speech).
// This powers hands-free conversation mode.
//
// Callbacks (both optional):
//   onLevel(vol)       — live mic volume (raw 0..255 average, ~12x/sec) so the
//                        UI can show that the mic is actually hearing something.
//   onDiagnostic(d)    — WHY a listen produced nothing: {type: "denied" |
//                        "no-mic" | "pending" | "unsupported" | "no-speech" |
//                        "error", ...}. A silent failure looks like a hang to
//                        the user, so every dead-end reports a reason.
export function listenForSpeech({
  maxMs = 15000,
  silenceMs = 1000,
  startTimeoutMs = 8000,
  threshold = 18,
  shouldStop,
  onLevel,
  onDiagnostic,
} = {}) {
  return new Promise((resolve) => {
    let resolved = false;
    const done = (v) => {
      if (!resolved) {
        resolved = true;
        resolve(v);
      }
    };
    const diag = (d) => {
      try {
        onDiagnostic && onDiagnostic(d);
      } catch {
        /* never let UI callbacks kill the recorder */
      }
    };

    // Insecure context (LAN IP instead of localhost) leaves mediaDevices undefined.
    if (!navigator.mediaDevices?.getUserMedia) {
      diag({ type: "unsupported" });
      return done(null);
    }

    // If the permission prompt is shown and never answered, getUserMedia stays
    // pending forever — which looks exactly like a frozen app. Give up loudly.
    let gotStream = false;
    const watchdog = setTimeout(() => {
      if (!gotStream) {
        diag({ type: "pending" });
        done(null);
      }
    }, 12000);

    navigator.mediaDevices
      .getUserMedia({
        audio: {
          echoCancellation: true, // cancel audio coming from the speakers
          noiseSuppression: true,
          autoGainControl: true,
        },
      })
      .then((stream) => {
        gotStream = true;
        clearTimeout(watchdog);
        if (resolved) {
          // Watchdog already gave up (permission granted too late) — don't leak the mic.
          stream.getTracks().forEach((t) => t.stop());
          return;
        }

        let rec;
        try {
          rec = new MediaRecorder(stream);
        } catch {
          stream.getTracks().forEach((t) => t.stop());
          diag({ type: "error", message: "recorder unavailable" });
          return done(null);
        }

        const chunks = [];
        rec.ondataavailable = (e) => e.data.size && chunks.push(e.data);

        const AC = window.AudioContext || window.webkitAudioContext;
        const ac = new AC();
        // Autoplay policy can start the context suspended; a suspended context
        // reports pure silence, which would make us "listen" to nothing forever.
        if (ac.state === "suspended") ac.resume().catch(() => {});
        const source = ac.createMediaStreamSource(stream);
        const analyser = ac.createAnalyser();
        analyser.fftSize = 512;
        source.connect(analyser);
        const buf = new Uint8Array(analyser.frequencyBinCount);

        let spoke = false;
        let silenceStart = 0;
        let stopped = false;
        let peak = 0;
        const t0 = performance.now();

        const safeStop = () => {
          try {
            if (rec.state !== "inactive") rec.stop();
          } catch {
            /* ignore */
          }
        };

        rec.onstop = () => {
          stopped = true;
          stream.getTracks().forEach((t) => t.stop());
          ac.close().catch(() => {});
          if (!spoke) diag({ type: "no-speech", peak: Math.round(peak), threshold });
          done(spoke ? new Blob(chunks, { type: "audio/webm" }) : null);
        };

        rec.start();

        const tick = () => {
          if (stopped) return;
          if (shouldStop && shouldStop()) return safeStop();

          analyser.getByteFrequencyData(buf);
          let sum = 0;
          for (let i = 0; i < buf.length; i++) sum += buf[i];
          const vol = sum / buf.length;
          const now = performance.now();
          if (vol > peak) peak = vol;
          try {
            onLevel && onLevel(Math.round(vol));
          } catch {
            /* ignore */
          }

          if (vol > threshold) {
            spoke = true;
            silenceStart = 0;
          } else if (spoke) {
            if (!silenceStart) silenceStart = now;
            else if (now - silenceStart > silenceMs) return safeStop();
          }

          if (!spoke && now - t0 > startTimeoutMs) return safeStop();
          if (now - t0 > maxMs) return safeStop();

          setTimeout(tick, 80);
        };
        setTimeout(tick, 80);
      })
      .catch((err) => {
        gotStream = true; // settled — stop the watchdog path
        clearTimeout(watchdog);
        const name = err?.name || "";
        if (name === "NotAllowedError" || name === "SecurityError") {
          diag({ type: "denied" });
        } else if (name === "NotFoundError" || name === "OverconstrainedError") {
          diag({ type: "no-mic" });
        } else {
          diag({ type: "error", message: String(err?.message || err) });
        }
        done(null);
      });
  });
}
