const SAMPLE_RATE = 24000;

// Party mode: open this page with ?party=a&room=test (person 1, German) or
// ?party=b&room=test (person 2, Bosnian). Each device is one call party and
// hears only the translation meant for it.
const urlParams = new URLSearchParams(location.search);
const partyMode = urlParams.get("party");
const roomName = urlParams.get("room") || "demo";

const els = {
  langA: document.getElementById("langA"),
  langB: document.getElementById("langB"),
  voiceA: document.getElementById("voiceA"),
  voiceB: document.getElementById("voiceB"),
  tts: document.getElementById("tts"),
  diarize: document.getElementById("diarize"),
  audioUrl: document.getElementById("audioUrl"),
  startBtn: document.getElementById("startBtn"),
  status: document.getElementById("status"),
  latency: document.getElementById("latency"),
  colA: document.getElementById("colA"),
  colB: document.getElementById("colB"),
  titleA: document.getElementById("titleA"),
  titleB: document.getElementById("titleB"),
};

let ws = null;
let recorder = null;
let stream = null;
let audioCtx = null;
let fileAudio = null;        // HTMLAudioElement for follow-along playback
let fileGain = null;         // gain node for ducking
let duckTimer = null;
let nextPlayTime = [0, 0];   // per direction
let lastAudioSentAt = 0;
let firstAudioAt = null;

// Per column: finalized text, non-final tail, last speaker label.
const cols = [
  { final: "", nonFinal: "", speaker: null },
  { final: "", nonFinal: "", speaker: null },
];

function colIndex(lang) {
  return lang === els.langA.value ? 0 : 1;
}

function render() {
  els.titleA.textContent = els.langA.value.toUpperCase();
  els.titleB.textContent = els.langB.value.toUpperCase();
  [els.colA, els.colB].forEach((el, i) => {
    el.innerHTML = "";
    el.append(cols[i].final);
    const span = document.createElement("span");
    span.className = "nonfinal";
    span.textContent = cols[i].nonFinal;
    el.append(span);
  });
}

function duckFile() {
  if (!fileGain) return;
  // 0.0 = full replacement, matches telephony behavior: while the translation
  // speaks, the source is completely muted (no original audible at all).
  fileGain.gain.setTargetAtTime(0.0, audioCtx.currentTime, 0.05);
  clearTimeout(duckTimer);
  duckTimer = setTimeout(() => {
    if (fileGain) fileGain.gain.setTargetAtTime(1.0, audioCtx.currentTime, 0.3);
  }, 900);
}

function playPcm(dir, bytes) {
  if (!audioCtx) audioCtx = new AudioContext({ sampleRate: SAMPLE_RATE });
  const pcm = new Int16Array(bytes.buffer, bytes.byteOffset, bytes.byteLength / 2);
  const buf = audioCtx.createBuffer(1, pcm.length, SAMPLE_RATE);
  buf.copyToChannel(new Float32Array(pcm.length).map((_, i) => pcm[i] / 32768), 0);
  const src = audioCtx.createBufferSource();
  src.buffer = buf;
  src.connect(audioCtx.destination);
  const t = Math.max(audioCtx.currentTime + 0.05, nextPlayTime[dir]);
  src.start(t);
  nextPlayTime[dir] = t + buf.duration;
  duckFile(); // duck the source file while translated speech is playing
}

function reset() {
  cols.forEach((c) => {
    c.final = "";
    c.nonFinal = "";
    c.speaker = null;
  });
  nextPlayTime = [0, 0];
  firstAudioAt = null;
  els.latency.textContent = "";
  render();
}

async function start() {
  reset();

  // Auto-discovery: without an explicit ?party= param, decide the role:
  // peer found on the LAN -> redirect there as party=b; else become host
  // (party=a) and re-check shortly to resolve simultaneous starts.
  if (!partyMode) {
    els.status.textContent = "suche anderen Teilnehmer im Netzwerk…";
    let peer = null;
    try {
      const res = await fetch("/discover");
      peer = (await res.json()).peer;
    } catch {
      els.status.textContent = "Fehler beim Netzwerk-Scan";
      return;
    }
    if (peer) {
      els.status.textContent = `Teilnehmer gefunden (${peer}) – verbinde…`;
      location.href = `http://${peer}:8000/?party=b&room=${roomName}&auto=1`;
      return;
    }
    els.status.textContent = "kein Teilnehmer gefunden – ich bin Gastgeber (Deutsch)";
    await startParty("a", location.host, roomName);
    // Simultaneous-start guard: if another host appeared, lower IP wins.
    setTimeout(async () => {
      try {
        const r = await fetch("/discover/check-host");
        const d = await r.json();
        if (!d.stay_host && ws) {
          els.status.textContent = `anderer Gastgeber gefunden (${d.peer}) – wechsle…`;
          setTimeout(() => (location.href = `http://${d.peer}:8000/?party=b&room=${roomName}&auto=1`), 500);
        }
      } catch { /* stay host */ }
    }, 4000);
    return;
  }

  if (urlParams.get("auto") === "1") {
    // Redirected here as party b: start immediately.
    els.status.textContent = "verbinde…";
  }
  await startParty(partyMode, location.host, roomName);
  if (urlParams.get("auto") === "1") els.startBtn.click();
}

async function startParty(party, host, room) {
  const params = new URLSearchParams({
    lang_a: els.langA.value,
    lang_b: els.langB.value,
    voice_a: els.voiceA.value || "Daniel",
    voice_b: els.voiceB.value || "Maya",
    tts: els.tts.checked,
    diarize: els.diarize.checked,
  });

  let wsUrl;
  params.set("room", room);
  params.set("party", party);
  wsUrl = `ws://${host}/ws/party?${params}`;
  ws = new WebSocket(wsUrl);
  ws.binaryType = "arraybuffer";

  ws.onopen = async () => {
    els.startBtn.textContent = "Stop";
    els.status.textContent = `verbunden als Partei ${party.toUpperCase()} (Raum ${room}) – sprich jetzt`;
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    recorder = new MediaRecorder(stream);
    recorder.ondataavailable = (e) => {
      if (e.data.size > 0 && ws.readyState === WebSocket.OPEN) ws.send(e.data);
    };
    recorder.start(250);
  };

  ws.onmessage = (e) => {
    if (e.data instanceof ArrayBuffer) {
      const view = new Uint8Array(e.data);
      // Party mode always: raw PCM, no direction prefix.
      playPcm(0, view);
      return;
    }
    const data = JSON.parse(e.data);
    if (data.session_done) {
      els.status.textContent = "Sitzung beendet";
      return;
    }
    if (data.error_code) {
      els.status.textContent = `Fehler: ${data.error_code}`;
      return;
    }
    if (data.peer_text !== undefined) {
      // The other party's speech, translated for me — show for reading along.
      cols[0].final += `\n→ ${data.peer_text}`;
      cols[0].nonFinal = "";
      render();
      return;
    }
    // Non-final tokens repeat the whole in-progress utterance in every STT
    // message – reset the tail first, then fill it with this message's version.
    cols.forEach((c) => (c.nonFinal = ""));
    for (const token of data.tokens || []) {
      const text = token.text;
      if (!text || text === "<end>") continue;
      if (partyMode && token.translation_status === "translation") continue;
      const idx = colIndex(token.language);
      if (token.speaker !== undefined && token.speaker !== cols[idx].speaker) {
        cols[idx].speaker = token.speaker;
        cols[idx].final += `\n[${token.speaker}] `;
      }
      if (token.is_final) {
        cols[idx].final += text;
      } else {
        cols[idx].nonFinal += text;
      }
    }
    render();
  };

  ws.onclose = stop;
  ws.onerror = () => (els.status.textContent = "Verbindungsfehler");
}

function stop() {
  recorder?.stop();
  stream?.getTracks().forEach((t) => t.stop());
  recorder = null;
  stream = null;
  fileAudio?.pause();
  fileAudio = null;
  fileGain = null;
  clearTimeout(duckTimer);
  ws?.close();
  ws = null;
  els.startBtn.textContent = "Start";
  els.status.textContent = "bereit";
}

els.startBtn.addEventListener("click", () => (ws ? stop() : start()));
