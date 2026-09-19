# HANDOFF — Live-Übersetzung Bosnisch ↔ Deutsch (Soniox)

Stand: 2026-09-19 · Repo: https://github.com/d-selmanovic/multi-call · Präsentation: heute (25 Min)

## 1. Produktvision

Zwei Personen telefonieren normal (Festnetz/Mobil/Softphone) über eine deutsche Nummer,
sprechen aber unterschiedliche Sprachen (z. B. Bosnisch/Kroatisch ↔ Deutsch). Eine
Übersetzungsschicht zwischen den Audio-Beinen übersetzt in Echtzeit, latenzarm, ohne
dass die Gesprächspartner etwas Besonderes bemerken. Langfristig: Asterisk/sipgate-Anbindung,
Voice-Cloning (Sprecher klingt wie man selbst), frei konfigurierbare Sprachpaare pro Nummer.

**Aktueller Stand (Phase 1):** Zwei-Mac-Browser-Demo. Zwei Geräte, je ein Browser,
bidirektionale Live-Übersetzung mit TTS-Ausgabe. Phase 2 (SDK-Bridge für RTP/Telefonie)
existiert als Skeleton.

## 2. Architektur

```
Mac 1 (Gerät 1, Partei B = Bosnisch)          Mac 2 (Gerät 2, Partei A = Deutsch)
┌─────────────────────────────┐              ┌─────────────────────────────┐
│ Browser (localhost:8000)    │              │ Browser (localhost:8000)    │
│  getUserMedia → PCM         │              │  getUserMedia → PCM         │
│  AudioContext (Ton-Out)     │              │  AudioContext (Ton-Out)     │
└──────┬──────────────────────┘              └──────┬──────────────────────┘
       │ WS /ws/party (oder /ws/proxy via LAN)      │
┌──────▼──────────────────────┐              ┌──────▼──────────────────────┐
│ FastAPI main.py (Port 8000) │◄────LAN──────►│ FastAPI main.py (Port 8000) │
│  STT-Stream (stt-rt-v5)     │              │  STT-Stream (stt-rt-v5)     │
│  one_way → Peer-Sprache     │              │  one_way → Peer-Sprache     │
│  TTS-Stream (tts-rt-v2)     │              │  TTS-Stream (tts-rt-v2)     │
└──────┬──────────────────────┘              └──────┬──────────────────────┘
       │ wss://stt-rt.eu.soniox.com                │ wss://tts-rt.eu.soniox.com
       ▼                                           ▼
              Soniox (EU Data Residency)
```

Wichtig: Jede Partei führt **eigenen** STT- und TTS-Stream. Übersetzung läuft serverseitig
(Partei-Config legt Sprachen fest, erste Einwahl = Partei A). Die Gegenseite hört ausschließlich
die Übersetzung (Full Replacement, kein Originalton).

### Endpunkte (main.py)
- `WS /ws/translate` — Single-Client-Modus (ein Mikrofon, beide Sprachspalten)
- `WS /ws/party` — Party-Modus (party=a/b, room=…)
- `WS /ws/proxy` — LAN-Proxy: Gerät-2-Server tunnelt zu Gerät-1-Server; Browser bleibt auf localhost
- `GET /health`, `/trace`, `/discover`, `/discover/check-host` — Status, Trace-Log, Auto-Discovery

### Party-Zuordnung
- Partei A = Deutsch (TTS-Stimme Daniel), Partei B = Bosnisch (TTS-Stimme Maya)
- Beide Parteien: STT `stt-rt-v5`, Übersetzung `one_way` in die Peersprache, TTS `tts-rt-v2` (`pcm_s16le`, 24 kHz)

## 3. Soniox-Konfiguration (EU)

| Komponente | Endpunkt | Modell |
|---|---|---|
| STT WebSocket | `wss://stt-rt.eu.soniox.com/transcribe-websocket` | `stt-rt-v5` |
| TTS WebSocket | `wss://tts-rt.eu.soniox.com/tts-websocket` | `tts-rt-v2` |

- **Ein API-Key** für STT + TTS + Translation (keine separate Translation-API). Key ist EU-gebunden;
  globale Endpunkte → 401.
- `.env` (gitignored, chmod 600) in `/Applications/soniox-translate-demo`:
  `SONIOX_API_KEY`, `SONIOX_STT_URL`, `SONIOX_TTS_URL`. `.env.example` ist im Repo.

## 4. Soniox-Timeouts und eingebaute Gegenmaßnahmen (kritisch!)

| Problem | Soniox-Verhalten | Unsere Lösung |
|---|---|---|
| STT-Idle-Timeout | WS wird bei >20 s ohne Traffic geschlossen | `{"type":"keepalive"}` alle 5 s |
| TTS-Verbindung stirbt ohne Config | frische TTS-WS ohne Config stirbt nach ~10 s | Prewarm: Config sofort beim Connect + bei Reconnect |
| TTS-Keepalive authentifiziert nicht | Keepalive ersetzt nicht die Config-Nachricht | Config immer zuerst, dann `{"keep_alive": true}` alle 5 s |
| TTS-Stream-Timeout | Stream stirbt nach ~5 s ohne Text (408 request_timeout) | Flush nach 4 s Token-Pause mit `text_end:true` → Sprechpause beendet Äußerung |
| TTS-Verbindung ohne Arbeit | wird nach ~3 Minuten ohne echte Audioproduktion geschlossen | akzeptiert; Reconnect via Holder-Pattern (`tts_holder`/`stt_holder`) |

STT-Endpoint-Ende wird als **leere Text-Nachricht** `ws.send("")` signalisiert (nicht `b""`).

## 5. Betrieb / How to run

### Server starten (Gerät 1)
```bash
cd /Applications/soniox-translate-demo
uv run uvicorn main:app --host 0.0.0.0 --port 8000
# oder headless:
nohup uv run uvicorn main:app --host 0.0.0.0 --port 8000 >/tmp/soniox-demo.log 2>&1 &
```
Log: `/tmp/soniox-demo.log` · Trace: `logs/trace.log`, abrufbar via `GET /trace`.

### Zwei-Geräte-Test (Proxy-Flow — Standard)
1. **Gerät 1** (IP 192.168.31.165): Server läuft (s. o.). Browser:
   `http://localhost:8000/?party=b&room=test` → Start → Mikro erlauben.
2. **Gerät 2**: EinKlick-Skript aus `~/Downloads/Geraet2-NEU-2026-09-18.zip`
   (macht git clone/pull, `uv sync`, startet Server, öffnet Browser):
   `http://localhost:8000/?proxy=192.168.31.165&party=a&room=test` → Start.
   Gerät-2-Browser bleibt auf localhost; dessen Server tunnelt zum Gerät-1-Server.

### Single-Client-Test (ein Gerät, beide Sprachen)
`http://localhost:8000` — Sprachen/Stimmen wählen, Start, abwechselnd deutsch und bosnisch sprechen.
„Übersetzung anhören" spielt jede Richtung mit gewählter Stimme vor. Optional: Audiodatei-URL
(Ducking 0 %) oder Diarization.

### CLI-Test mit Latenzmessung (ohne Browser)
```bash
uv run python test_file.py --audio_path tests/test_de.wav --lang_a de --lang_b bs
```
Erzeugt `translation_to_de.wav` / `translation_to_bs.wav` + Zeit bis erstem Übersetzungstoken
und TTS-Time-to-First-Audio. `tests/test_*.wav` = per Soniox-TTS generierte Sprachproben.

### Electron-App
`app/` enthält Electron-Hülle (productName **ASCII** — „LiveTranslate"; Umlaut crashte Electron 44
auf macOS 26, Anzeigename via CFBundleDisplayName). App startet Backend selbst, lädt UI von Platte
→ Fixes ohne dmg-Neubau. Build: `cd app && npm install && npm run dist` (unsigned → Rechtsklick → Öffnen).

## 6. Verifikationsstand

**Verifiziert:**
- Beide Übersetzungsrichtungen (Text + TTS-Audio) via automatisierter Zwei-Client-Simulation
- STT-Keepalive (40 s Stille, kein 408)
- TTS stabil nach Prewarm; Proxy-Endpunkt; EU-Endpunkte/Key

**Nicht verifiziert mit echten Geräten:**
- Der vollständige Proxy-Flow zwischen Mac 1 und Mac 2 (letzter Versuch scheiterte an altem Code
  auf Gerät 2; neues zip liegt seitdem bereit)

### Trace-Auswertung
```bash
python3 -c "import json,sys; [print(json.loads(l)) for l in open('logs/trace.log')]"
```
Relevante Events: `party_connected`, `mic_audio`, `stt_tokens`, `stt_error`/`stt_reconnected`,
`tts_stream_open`, `tts_audio_out`. Achtung: `tts_audio_no_peer` = andere Seite nicht im selben Raum.

## 7. Bekannte Fallstricke (Debugging)

1. **Browser-Fenster nicht minimieren** — macOS drosselt Hintergrund-Tabs → STT-408.
2. **Mikro auf beiden Macs frei halten** (orange Punkte in Menüleiste; z. B. „Transkriptor" hatte es belegt).
3. `print` im Server ist block-gepuffert → Trace-Datei nutzen, nicht stdout.
4. Immer `uv run …` verwenden (sonst `ModuleNotFoundError: soniox`).
5. Browser auf `http://<LAN-IP>` sperrt Mikrofon (unsicherer Kontext) → Proxy-Flow: Browser = localhost, LAN läuft serverseitig.
6. Bei Fehler „localhost öffnet sich nicht": Server läuft nicht → Log prüfen.

## 8. Verzeichnisstruktur

```
main.py                  FastAPI-Server (alle WS-Endpunkte, Keepalive, Holder/Reconnect)
frontend/                Vanilla-JS-UI (AudioContext im Start-Klick!)
bridge/                  Phase 2: SDK-Bridge (RTP + CallSession, Skeleton)
docs/                    ARCHITECTURE, CONFIGURATION, ROADMAP, STATUS, SONIOX-DOCS, HANDOFF (diese Datei)
app/                     Electron-App
test_file.py             CLI-Latenztest
tests/                   deutsche/bosnische Sprachproben
start.command            macOS-Doppelklick-Start (Server)
```

## 9. Roadmap (Phase 2/3 — nächste Schritte)

1. **Phase 3 — Asterisk-ARI**: Stasis-App, die pro Anruf zwei `bridge/rtp.RtpEndpoint`s öffnet
   und `bridge.CallSession` nutzt. Voraussetzungen prüfen: `asterisk -rx "ari show status"`,
   Version ≥ 16, `externalMedia` verfügbar. RTP-G.711-Encoder ist eigenimplementiert (kein `audioop`).
   Frage klären: wie kommt Dograh heute an sein Audio?
2. **Voice-Cloning**: eigene Stimme in Soniox Console („Your voices") klonen, Voice-ID als
   `voice_a`/`voice_b` eintragen — der Anrufer hört sich selbst in der Zielsprache.
3. **Freie Sprachpaare pro Nummer** (CONFIGURATION.md dokumentiert die Mechanik bereits).
4. **Registerformalität**: sipgate/trunk-Setup für deutsche Nummern.

## 10. Präsentations-Fallbacks

1. Offizielle Soniox-Demo: https://github.com/soniox/soniox_examples
   (App `soniox-speech-to-speech-translation-demo`).
2. `test_file.py` als Latenz-/Qualitätsbeweis ohne Live-Setup.
3. Trace-Log + `GET /trace` als technischer Beweis des Pipeline-Laufs.
