# AGENTS.md

## Projekt

Echtzeit-Sprachübersetzung Deutsch ↔ Bosnisch/Kroatisch auf Basis der
Soniox STT/TTS-WebSocket-APIs (ohne SDK). FastAPI-Backend (`main.py`) +
Vanilla-JS-Frontend (`frontend/`). Phase 1 von „Live-Telefonübersetzung",
Langfristziel Telefonie über Asterisk/sipgate (siehe `docs/ROADMAP.md`).

Aktueller Stand und offene Punkte: **`docs/STATUS.md`** – vor größeren
Änderungen immer zuerst lesen und danach aktualisieren.

## Befehle

```bash
uv sync                                       # Dependencies
uv run uvicorn main:app --reload --port 8000  # Dev-Server
uv run python test_file.py --audio_path tests/test_de.wav --lang_a de --lang_b bs  # CLI-Latenztest
cd app && npm install && npm run dist         # Electron-dmg bauen
```

Repo: https://github.com/d-selmanovic/multi-call (Branch `main`).

## Feste Regeln

- **Nur EU-Endpunkte** (`stt-rt.eu.soniox.com`, `tts-rt.eu.soniox.com`); der
  API-Key funktioniert einmal für STT+TTS+Translation. EU Data Residency im
  Soniox-Account muss aktiviert sein.
- **Electron: kein Umlaut im `productName`** (der „Ü"-Bug → SIGTRAP-Crash;
  heute ASCII `LiveTranslate`).
- **Secure Context nie verletzen:** Browser geben Mikro/Ton nur auf sicheren
  Kontexten frei. Zwei-Geräte-Standard ist deshalb der **Proxy-Modus**
  (`/ws/proxy`, Browser auf `localhost`), nicht Direkt-URLs per LAN-IP.
- **Soniox beendet TTS-Streams nach ~5 s Idle** → 5-s-Keepalive + Reconnect
  (Holder-Pattern), `text_end` nach 4 s ohne Tokens. Details:
  `docs/ARCHITECTURE.md`.
- AudioContext und `getUserMedia` immer im User-Klick anlegen (Autoplay-/Mic-
  Sperren).

## Wichtige Dateien

- `main.py` – Endpunkte: `/ws/translate` (Single), `/ws/party`, `/ws/proxy`,
  `/discover`, `/health`, `/trace`
- `frontend/app.js` – Party-/Proxy-Modus, Audio-Handling, Zähler
- `docs/` – ARCHITECTURE, CONFIGURATION, ROADMAP, SONIOX-DOCS, STATUS, HANDOFF
- `logs/trace.log` + `GET /trace` – Tracing, erste Anlaufstelle bei Diagnose

## Issue Tracker

GitHub Issues im Repo `d-selmanovic/multi-call` (kein Linear verfügbar).
Bevorzugt Issues für offene Punkte aus `docs/STATUS.md` Abschnitt
„Nächste Schritte" anlegen/aktualisieren.
