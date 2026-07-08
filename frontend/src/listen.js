// Record from the mic and auto-stop when the user stops talking (silence
// detection via Web Audio). Resolves with an audio Blob (or null if no speech).
// This powers hands-free conversation mode.
export function listenForSpeech({
  maxMs = 15000,
  silenceMs = 1000,
  startTimeoutMs = 8000,
  threshold = 18,
  shouldStop,
} = {}) {
  return new Promise((resolve) => {
    let resolved = false;
    const done = (v) => {
      if (!resolved) {
        resolved = true;
        resolve(v);
      }
    };

    navigator.mediaDevices
      .getUserMedia({
        audio: {
          echoCancellation: true, // cancel audio coming from the speakers
          noiseSuppression: true,
          autoGainControl: true,
        },
      })
      .then((stream) => {
        let rec;
        try {
          rec = new MediaRecorder(stream);
        } catch {
          stream.getTracks().forEach((t) => t.stop());
          return done(null);
        }

        const chunks = [];
        rec.ondataavailable = (e) => e.data.size && chunks.push(e.data);

        const AC = window.AudioContext || window.webkitAudioContext;
        const ac = new AC();
        const source = ac.createMediaStreamSource(stream);
        const analyser = ac.createAnalyser();
        analyser.fftSize = 512;
        source.connect(analyser);
        const buf = new Uint8Array(analyser.frequencyBinCount);

        let spoke = false;
        let silenceStart = 0;
        let stopped = false;
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
      .catch(() => done(null));
  });
}
