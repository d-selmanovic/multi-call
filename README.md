# Soniox Live-Übersetzung Demo (Deutsch ↔ Bosnisch/Kroatisch)

Echtzeit-Sprachübersetzung auf Basis der Soniox STT- und TTS-WebSocket-APIs (ohne SDK).
FastAPI-Backend + Vanilla-JS-Frontend. **Phase 1** des Projekts „Live-Telefonübersetzung"
(siehe `docs/ROADMAP.md`).

- Architektur & Soniox-Erkenntnisse: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
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

## Testmodi

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
