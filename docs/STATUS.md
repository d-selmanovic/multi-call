# Projektstatus: Live-Übersetzung Bosnisch ↔ Deutsch

Stand: 2026-09-19, früh. Repo: https://github.com/d-selmanovic/multi-call

## 1. Ziel

Zwei Personen telefonieren in unterschiedlichen Sprachen (Bosnisch ↔ Deutsch).
Jede hört **nur die Übersetzung** in ihrer Sprache, keine Originalstimme.
Heutiger Stand: Demo auf zwei Macs (Browser), morgen Präsentation (25 Min).
Langfristig: Telefonie über Asterisk/sipgate (Phasen 2–5, siehe ROADMAP.md).

## 2. Technische Architektur (jetzt)

```
Gerät 1 (Gastgeber)                              Gerät 2
Browser ──localhost──> Server G1 <════ LAN ════> Server G2 <──localhost── Browser
 (Mic/Ton ok)        (alle STT/TTS/          (nur Tunnel)      (Mic/Ton ok)
                      Übersetzung)
```

- **Party-Modus** (`/ws/party`): jede Partei = eigener STT-Stream (one-way
  Übersetzung in die Peersprache) + eigener TTS-Stream mit eigener Stimme.
- **LAN-Proxy** (`/ws/proxy`): Browser bleiben auf `localhost` (Browser geben
  Mikro/Ton nur auf sicheren Kontexten frei; `http://<LAN-IP>` ist UNSICHER →
  Mic gesperrt). Der Server von Gerät 2 baut einen Tunnel zum Server von Gerät 1.
- **Soniox EU-Endpoints**, ein API-Key für alles:
  - STT: `wss://stt-rt.eu.soniox.com/transcribe-websocket` (Modell `stt-rt-v5`,
    Config inkl. `"translation": {"type":"one_way","target_language":...}`)
  - TTS: `wss://tts-rt.eu.soniox.com/tts-websocket` (Modell `tts-rt-v2`,
    `pcm_s16le` 24 kHz; für Telefonie später `pcm_mulaw` 8 kHz möglich)
- **Rollen**: Partei A = Deutsch (Stimme `Daniel`), Partei B = Bosnisch
  (Stimme `Maya`). Später austauschbar gegen Voice-Cloning-IDs.
- **Tracing**: `logs/trace.log` (JSON-Lines) + `GET /trace`; Frontend zeigt
  „gesendet X KB · empfangen Y s Audio".

## 3. Was funktioniert (verifiziert)

- Übersetzung beide Richtungen (de→bs, bs→de) mit dem EU-Key, Text + TTS-Audio
  (mehrfach per automatisierter Zwei-Client-Simulation, Trace: `tts_audio_out`).
- TTS-Reconnect nach Soniox-Idle-Timeout (1001/408), Keepalive 5 s.
- STT-408-Reconnect, Frontend-Filter für `<end>`-Tokens, Textanzeige-Fix
  (non-finale Tokens werden ersetzt, nicht angehängt).
- AudioContext-Fix (im Klick anlegen → Autoplay-Sperre umgangen).
- LAN-Proxy-Endpunkt + Selbsttest erfolgreich.

## 4. Das aktuelle Problem

**Letzter Live-Test:** beide Geräte transkribierten nur sich selbst, kein Ton
beim Peer. Ursachenkette (alle gefunden, alle bis auf eine behoben):

1. Beide Browser liefen auf ihrem **eigenen localhost-Server** → zwei getrennte
   „Räume". → **Gelöst** durch Direkt-URLs / später Proxy-Modus.
2. Direkt-URL `http://<LAN-IP>` → **Browser sperrt Mikrofon** (unsicherer
   Kontext). → **Gelöst** durch Proxy-Modus (Browser localhost, Server tunneln).
3. **TTS-Verbindung wurde nach ~10 s Idle von Soniox gekillt** (1001 Timeout),
   20 s-Keepalive zu langsam, kein Reconnect → Übersetzung ja, Ton nein.
   → **Gelöst** (Keepalive 5 s + Reconnect).
4. Offen: Der Proxy-Flow wurde mit **echten Geräten noch nicht durchgetestet** –
   Gerät 2 braucht das neue EinKlick-Skript (holt per `git pull` den
   Proxy-Code). Steht unmittelbar bevor.

## 5. Was wir alles versucht/gefixt haben (Chronologie)

1. Basis-Demo nach offizieller Soniox-Referenz, two-way → Party-Modus gebaut.
2. Soniox-408 auf TTS-Streams (~5 s ohne Text) → 4-s-Flush mit `text_end`.
3. Leeres Binär-Frame als STT-Endemarker → muss leere **Text**-Nachricht sein.
4. Prewarm-Phantom-Audio → Prewarm-Streams idle lassen.
5. Text-Wiederholungen („ent-ent-…") → non-finale Tokens pro Nachricht ersetzen.
6. `<end>`-Token in Anzeige → herausgefiltert.
7. Safari-Mikro: getUserMedia direkt im Klick (kein Auto-Click nach Redirect).
8. AudioContext im Klick anlegen (Autoplay-Sperre) – der wahrscheinliche Ton-Killer.
9. Auto-Discovery im LAN (Subnetz-Scan + Rollenvergabe + IP-Tiebreak).
10. TTS 1001-Timeout → 5 s Keepalive + Reconnect (Holder-Pattern, resiliente Pipes).
11. STT 408 → Auto-Reconnect (Holder-Pattern).
12. Discovery unzuverlässig → Direkt-URLs → Mic-Blockade → **Proxy-Modus**.
13. Electron-App gebaut (ohne Deskifier): Crash durch Umlaut im Executable-Namen
    (productName jetzt ASCII `LiveTranslate`), dmg in ~/Downloads.
14. Trace-Logging eingebaut, das alle obigen Diagnosen erst möglich machte.

Nicht das Problem (geprüft): API-Key (EU-Key funktioniert an EU-Endpoints,
ein Key für STT+TTS+Translation), falsche Base-URLs (STT/TTS haben korrekt
getrennte Hosts), Modelle (`stt-rt-v5`/`tts-rt-v2` korrekt).

## 6. Setup & Konfiguration (Detail)

### Gerät 1 (Gastgeber, z. B. 192.168.31.165)
- Repo: `/Users/activi/soniox-translate-demo` (Git, main = GitHub)
- Läufige Instanz: `/Applications/soniox-translate-demo` (Server per
  `nohup uv run uvicorn main:app --host 0.0.0.0 --port 8000`)
- `.env` (chmod 600): `SONIOX_API_KEY=snx_…` + EU-STT/TTS-URLs
- Browser-URL: `http://localhost:8000/?party=b&room=test` (Partei B = Bosnisch)
- Desktop-Doppelklick: „Live-Übersetzung Starten.command"
- App: `/Applications/LiveTranslate.app` (Electron-Hülle, lädt Backend von Platte)

### Gerät 2
- Setup per AirDrop: `~/Downloads/Geraet2-NEU-2026-09-18.zip`
  → `Geraet2-EinKlick-Start.command` (enthält Key, macht git clone/pull,
  `uv sync`, startet Server, öffnet Browser mit Proxy-URL)
- Browser öffnet automatisch:
  `http://localhost:8000/?proxy=192.168.31.165&party=a&room=test`
- Voraussetzungen: beide im selben WLAN, Fenster nicht minimieren (macOS
  drosselt Hintergrund-Tabs → STT-408), Mikro nicht von anderer App belegt.

### Wichtige Dateien (Repo)
- `main.py` – FastAPI: `/ws/translate` (Single), `/ws/party`, `/ws/proxy`,
  `/discover`, `/health`, `/trace`
- `frontend/app.js` – Party/Proxy-Modus, AudioContext-Handling, Zähler
- `app/` – Electron-Hülle (npm run dist → dmg)
- `docs/` – ARCHITECTURE, CONFIGURATION, ROADMAP, SONIOX-DOCS
- `tests/test_*.wav`, `test_file.py` – CLI-Latenztest

## 7. Nächste Schritte

1. **Jetzt:** Gerät 2 mit neuem EinKlick-Skript starten, beide Browser-URLs
   (oben), 10 s pro Richtung sprechen, Trace prüfen → Ton verifizieren.
2. Danach: STT-Keepalive (Docs: `/stt/rt/connection-keepalive`) einbauen, um
   STT-408-Reconnects ganz zu vermeiden.
3. Morgen: Präsentation (25 Min): Problem → Live-Demo → Roadmap
   (Asterisk/sipgate-Telefonie, Voice-Cloning, freie Sprachpaare pro Nummer).

## 8. Anhang: Verifikation der Zwei-Geräte-Anleitung (2026-09-19)

Die Party-Modus-Anleitung im README (`?party=a/b&room=test`, Port 8000, Partei A
definiert Sprachen/Stimmen auf erste Einwahl, jede Seite hört nur die
Übersetzung, `peer_text` als Lestext) wurde gegen den Code verifiziert
(`frontend/app.js`, `main.py:315-328`) – sie ist korrekt. Zu beachten:

- **Secure Context:** `http://<LAN-IP>` gibt kein Mikro frei → Proxy-Modus
  oder Direkt-URL nur mit HTTPS/Ausnahme. Der Proxy-Modus ist deshalb der
  empfohlene Zwei-Geräte-Standard (Browser bleiben auf `localhost`).
- **Auto-Discovery** (ohne URL-Parameter) existiert als Alternative, ist aber
  gegenüber dem Proxy-Modus zweitrangig.
