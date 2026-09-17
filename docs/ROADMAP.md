# Roadmap

Stand: 2026-09-17. Status: **Phase 1 abgeschlossen und getestet.**

## Phase 1 – Demo/Test-App ✅

FastAPI + Vanilla JS, Soniox STT (two-way + one-way) + TTS, EU-Endpoints.

Umfang:
- Single-Client-Modus (`/ws/translate`): two-way translation, zwei TTS-Stimmen mit
  Routing nach Token-`language`, Datei-Modus (0 %-Ducking), optionale Diarization.
- Party/Room-Modus (`/ws/party`): zwei Geräte, je eigener STT/TTS-Pfad (Telefonie-Architektur),
  Gegenstelle hört nur Übersetzung.
- **Auto-Discovery** (`/discover`): Start-Button scannt das LAN, Rollen (Gastgeber/Partei A
  vs. Client/Partei B) werden automatisch vergeben; Gleichzeitigkeits-Fenster per IP-Vergleich.
- **Native macOS-App** (`app/`, Electron, ohne Deskifier): startet das Backend mit,
  öffnet UI im eigenen Fenster; dmg-Build via electron-builder. Hebt die Deskifier-
  Einschränkungen auf (kein fester URL, kein Internet-Zwang, kein Wasserzeichen).
  Hinweis: Dateisystem-Erlaubnisse (Deskifier-Filesystem-Allowlist) hätten diese
  Einschränkungen NICHT aufgehoben – sie sind architekturell, keine Berechtigungsfrage.
- CLI-Test `test_file.py` mit Latenzmessung; Test-Fixtures in `tests/`.
- Getestet: beide Richtungen de↔bs vollständig (Text + Audio), EU-Endpoints, 408-Flush,
  Discovery (eigene IP + LAN-Erreichbarkeit), App-Start.

Bekannte Einschränkungen (Demo-Scope):
- TTFA oft erst am Äußerungsende (Soniox-TTS-Verhalten, siehe ARCHITECTURE.md)
- UI schlicht, kein Auth, nur 1 Raum pro Namen pro Serverinstanz

## Phase 2 – Translate-Bridge (RTP-Telefonie-Core) ⬜

Python-Service auf EU-Server (direkt beim/nähe Asterisk):

- Pro Anruf zwei RTP-Sockets: G.711 ulaw, 8 kHz, 20 ms-Pakete
  (TTS: `pcm_mulaw`/`pcm_alaw` direkt; STT: `audio_format: auto` bzw. explizit ulaw)
- STT-WS (two_way oder 2× one_way) + TTS je Richtung, Queue-basiert, 4-s-Flush, Keepalive
- Jitter-/Playout-Puffer für RTP→STT; konstante Paketgröße für TTS→RTP
- Konfiguration pro Anruf: Sprachpaar, Stimmen, ggf. Klone
- Logging: Call-ID, Latenz-Metriken, Fehlerfall → Fallback ohne Übersetzung statt Abbruch

## Phase 3 – Asterisk/ARI-Anbindung ⬜

- Voraussetzung prüfen: Asterisk ≥ 16, `res_stasis`/`res_ari` aktiv,
  `externalMedia` verfügbar (siehe Checkliste unten)
- ARI-Stasis-App: Anruf auf Übersetzungsnummer → zwei externalMedia-Channels
  (je Partei, Mix-Minus), RTP an Bridge, Bridges in Asterisk verbinden
- **Rückfrage an Betrieb:** Wie bekommt Dograh heute das Gesprächsaudio?
  Falls schon externalMedia/AudioSocket genutzt wird → Mechanismus wiederverwenden.

### Checkliste Asterisk (vor Phase 3)

```bash
asterisk -rx "core show version"               # >= 16
asterisk -rx "module show like res_ari"        # geladen?
asterisk -rx "ari show status"                 # ARI aktiv?
asterisk -rx "ari show users"                  # User für Stasis-App vorhanden?
```

## Phase 4 – Öffentlicher Anschluss ⬜

- sipgate-Trunk (vorhanden): eingehende Nummer(n) → Übersetzungs-Stasis-App
- Verify: Anruf von Mobilfunk auf die deutsche Nummer, End-to-End

## Sprachpaar-Auswahl im Telefoniebetrieb (GEPLANT – nicht umgesetzt)

Das Sprachpaar ist Konfiguration (`translation.language_a/_b`); beliebige Paare der 60+
Sprachen sind zulässig. Drei Varianten für die Auswahl im laufenden Betrieb:

1. **Pro Telefonnummer (empfohlen, Variante für Umsetzung vorgesehen):**
   Jede sipgate-Nummer = festes Sprachpaar. Beispiel:
   `+49…1 = bs↔de`, `+49…2 = bs↔tr`, `+49…3 = bs↔es`.
   Umsetzung in Phase 2/3: Mapping-Tabelle (Nummer → `lang_a/lang_b/voice_a/voice_b`)
   in der Bridge-Konfig + Asterisk-Regel „DID X → Übersetzungsparameter Y".
   Aufwand: minimal (Konfiguration + Dialplan-Regel).
2. Sprachmenü nach Anrufannahme („Für Bosnisch-Deutsch 1, für Türkisch…") –
   flexibler, aber Zusatzschritt für jeden Anrufer.
3. Web-UI/Admin-Panel zum Umstellen des Paars für nächste Anrufe.

Entscheidung: Variante 1 als Default implementieren, 2/3 optional nachziehbar.

## Phase 5 – Optimierung & Härtung ⬜

- End-to-End-Latenz messen und trimmen (Ziel: nicht spürbar)
- Voice Cloning beider Parteien (Kundensstimmen einrichten)
- Echo-/Ducking-Verhalten (Sequenzierung der Sprechrichtungen)
- Monitoring/Alerts, mehrere parallele Anrufe (ggf. zweiter Soniox-Key bei Limits)
