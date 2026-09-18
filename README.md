# Soniox Live-Übersetzung Demo (Deutsch ↔ Bosnisch/Kroatisch)

Echtzeit-Sprachübersetzung auf Basis der Soniox STT- und TTS-WebSocket-APIs (ohne SDK).
FastAPI-Backend + Vanilla-JS-Frontend. **Phase 1** des Projekts „Live-Telefonübersetzung"
(siehe `docs/ROADMAP.md`).

- Architektur & Soniox-Erkenntnisse: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
- Aktueller Projektstatus & Setup: [`docs/STATUS.md`](docs/STATUS.md)

## Soniox-Dokumentation

- Übersicht aller Seiten: https://soniox.com/docs/llms.txt
- Komplette Doku als eine Datei: https://soniox.com/docs/llms-full.txt
- Markdown-Version jeder Seite: `.mdx` an die URL anhängen
- MCP-Server für Coding-Assistenten: https://soniox.com/docs/api/mcp/mcp
- Für dieses Projekt wichtig: [STT WebSocket API](https://soniox.com/docs/api-reference/stt/websocket-api.mdx),
  [TTS WebSocket API](https://soniox.com/docs/api-reference/tts/websocket-api.mdx),
  [STS-Translation](https://soniox.com/docs/translation/sts-translation.mdx),
  [STT Connection Keepalive](https://soniox.com/docs/stt/rt/connection-keepalive.mdx),
  [TTS Connection Keepalive](https://soniox.com/docs/tts/rt/connection-keepalive.mdx),
  [STT Error Handling](https://soniox.com/docs/stt/rt/error-handling.mdx),
  [Voice Cloning](https://soniox.com/docs/tts/concepts/voice-cloning.mdx),
  [Data Residency (EU)](https://soniox.com/docs/data-residency.mdx),
  [Proxy-Stream-Architektur](https://soniox.com/docs/guides/proxy-stream.mdx)
- Alle Einstellungen & Sprachpaare: [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md)
- Phasenplan inkl. Telefonie: [`docs/ROADMAP.md`](docs/ROADMAP.md)

## Setup

`.env` aus `.env.example` kopieren und `SONIOX_API_KEY` eintragen. Voreinstellung sind die
**EU-Endpunkte** (Voraussetzung: EU Data Residency im Soniox-Console-Account aktiviert,
sonst globale Endpunkte in `.env.example` verwenden).

```bash
uv sync
uv run uvicorn main:app --reload --port 8000
```

Dann http://localhost:8000 öffnen.

## Auto-Discovery (Zwei Macs, keine URL-Parameter mehr)

Beide Macs: **LiveTranslate.app** öffnen (oder `start.command`), **Start** klicken.
Der Server scannt das LAN selbst: wer einen anderen Demo-Server findet, verbindet sich
automatisch als Partei B (bosnisch), der andere wird Gastgeber/Partei A (deutsch).
Gleichzeitige Starts werden per IP-Vergleich aufgelöst (niedrigere IP bleibt Gastgeber).
Endpunkte: `GET /health`, `GET /discover`, `GET /discover/check-host`.

## Native macOS-App (ohne Deskifier)

`app/` enthält eine Electron-App, die das Backend selbst startet und die UI in einem
nativen Fenster öffnet – keine URL-Konfiguration, keine Internet-Abhängigkeit, kein
Wasserzeichen. Build: `cd app && npm install && npm run dist` (dmg, unsigned →
Rechtsklick → Öffnen). Das Backend wird erwartet in
`/Applications/soniox-translate-demo` (Override per `SONIOX_DEMO_HOME`).

## Testmodi (Klassiker)

### 1. Single-Client (ein Mikrofon, beide Sprachen)
`http://localhost:8000` – Sprachen/Stimmen wählen, **Start**, sprechen (deutsch und/oder
bosnisch). Links/rechts je eine Sprachspalte; mit „Übersetzung anhören" wird jede Richtung
mit der gewählten Stimme vorgelesen. Optional: Audiodatei-URL (0 %-Ducking) oder Diarization.

### 2. Party-Modus (zwei Geräte, zwei Räume – Telefonie-Architektur)
- Gerät 1: `http://<server-ip>:8000/?party=a&room=test` (spricht/hört Deutsch)
- Gerät 2: `http://<server-ip>:8000/?party=b&room=test` (spricht/hört Bosnisch)

Beide **Start**, Mikrofon erlauben. Partei A definiert Sprachen/Stimmen (erste Einwahl).
Jede Seite hört **ausschließlich** die Übersetzung in ihrer Sprache – kein Originalton.

### 3. CLI-Test mit Latenzmessung (ohne Browser)

```bash
uv run python test_file.py --audio_path tests/test_de.wav --lang_a de --lang_b bs
```

Ausgabe: `translation_to_de.wav` / `translation_to_bs.wav` plus Zeit bis erstem
Übersetzungstoken und TTS-Time-to-First-Audio. `tests/test_*.wav` sind per Soniox-TTS
generierte deutsche/bosnische Sprachproben.

Hinweis: Mikrofonzugriff braucht einen sicheren Kontext – `http://localhost` erlaubt,
andere Hosts ggf. über HTTPS.

## Wichtigster Soniox-Hinweis

Soniox beendet TTS-Streams nach ~5 s ohne Audio-Aktivität (`408 Request timeout`). Der
Sender schließt deshalb Streams nach 4 s ohne Übersetzungstokens mit `text_end` – eine
Sprechpause beendet die Äußerung. Details: `docs/ARCHITECTURE.md`.
