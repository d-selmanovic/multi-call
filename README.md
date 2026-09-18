# Soniox Live-Übersetzung Demo (Deutsch ↔ Bosnisch/Kroatisch)

Echtzeit-Sprachübersetzung auf Basis der Soniox STT- und TTS-WebSocket-APIs (ohne SDK).
FastAPI-Backend + Vanilla-JS-Frontend. **Phase 1** des Projekts „Live-Telefonübersetzung".

- Architektur & Soniox-Erkenntnisse: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
- Alle Einstellungen & Sprachpaare: [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md)
- Phasenplan inkl. Telefonie: [`docs/ROADMAP.md`](docs/ROADMAP.md)
- **Aktueller Stand & Setup:** [`docs/STATUS.md`](docs/STATUS.md)

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

## Setup

`.env` aus `.env.example` kopieren und `SONIOX_API_KEY` eintragen. Voreinstellung sind die
**EU-Endpunkte** (Voraussetzung: EU Data Residency im Soniox-Console-Account aktiviert,
sonst globale Endpunkte in `.env.example` verwenden).

```bash
uv sync
uv run uvicorn main:app --host 0.0.0.0 --port 8000
```

## Zwei-Geräte-Test (der entscheidende Modus)

**Warum Proxy-Modus:** Browser geben Mikrofon/Wiedergabe nur auf „sicheren Kontexten" frei –
`http://localhost` ist sicher, `http://<LAN-IP>` nicht. Deshalb bleibt jeder Browser auf seinem
lokalen Server, und der Server von Gerät 2 baut einen Tunnel zum Gastgeber (Gerät 1):

```
Gerät 1: Browser → localhost-Server (Gastgeber: STT/TTS/Übersetzung)
Gerät 2: Browser → localhost-Server → Tunnel (/ws/proxy) → Server Gerät 1
```

1. **Gerät 1:** `http://localhost:8000/?party=b&room=test` → Start → Mikro erlauben
   (Partei B = Bosnisch)
2. **Gerät 2:** `http://localhost:8000/?proxy=<IP-von-Gerät-1>&party=a&room=test` → Start →
   Mikro erlauben (Partei A = Deutsch)
3. Beide zeigen „verbunden als Partei …" – dann sprechen. Jede Seite hört **nur die
   Übersetzung** in ihrer Sprache, kein Originalton.

Für Gerät 2 liegt ein EinKlick-Skript bereit (siehe `docs/STATUS.md`): startet Server,
holt per `git pull` Updates und öffnet den Browser mit der richtigen Proxy-URL.

## Soniox-Timeouts & Keepalive (wichtig, aus der Doku)

| Ebene | Limit | Unsere Maßnahme |
|---|---|---|
| STT-Verbindung | >20 s ohne Audio/Keepalive → Timeout | `{"type":"keepalive"}` alle 5 s |
| TTS-Verbindung | ~10 s ohne Config → geschlossen (Keepalive authentifiziert **nicht**) | Prewarm-Config beim Verbinden, dann `{"keep_alive": true}` alle 5 s |
| TTS-Stream | ~5 s ohne Text → `request_timeout` | `text_end` nach 4 s Token-Pause (Sprechpause = Äußerungsende) |
| TTS-Verbindung | ~3 min ohne Audioerzeugung → geschlossen | Auto-Reconnect (Holder-Pattern) |

Details: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). Hinweis: Soniox berechnet die
**volle Stream-Dauer**, nicht nur verarbeitete Audiozeit.

## Debugging / Tracing

- Backend-Trace: `logs/trace.log` (JSON-Lines: `party_connected`, `mic_audio`, `stt_tokens`,
  `tts_stream_open`, `tts_audio_out`, Fehler, Reconnects) oder `GET /trace`
- Frontend: oben stehen Live-Zähler „gesendet X KB · empfangen Y s Audio"
- Server-Log: `/tmp/soniox-demo.log`

## Weitere Mod

i

### Single-Client (ein Mikrofon, beide Sprachen)
`http://localhost:8000` – zwei Sprachspalten, two-way-Übersetzung, Stimmen wählbar,
optionale Diarization, Datei-Modus mit 0 %-Ducking.

### CLI-Test mit Latenzmessung
```bash
uv run python test_file.py --audio_path tests/test_de.wav --lang_a de --lang_b bs
```

### Native macOS-App
`app/` enthält eine Electron-Hülle, die das Backend startet und die UI im nativen Fenster
öffnet. Build: `cd app && npm install && npm run dist` (dmg, unsigned → Rechtsklick → Öffnen).
Achtung: productName muss ASCII sein (Umlaut im Executable crasht Electron auf macOS 26).
