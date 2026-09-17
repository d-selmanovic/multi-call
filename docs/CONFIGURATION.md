# Konfiguration

## 1. Umgebungsvariablen (`.env`, aus `.env.example` kopieren)

| Variable | Bedeutung | Standard |
|---|---|---|
| `SONIOX_API_KEY` | API-Key (Console → Projects). EU-Keys funktionieren nur an EU-Endpoints. | – |
| `SONIOX_STT_URL` | STT-WebSocket-Endpoint | `wss://stt-rt.eu.soniox.com/transcribe-websocket` |
| `SONIOX_TTS_URL` | TTS-WebSocket-Endpoint | `wss://tts-rt.eu.soniox.com/tts-websocket` |

EU-Endpoints setzen EU Data Residency im Console-Account voraus (eimalig aktivieren).
Für globale Keys die auskommentierten globalen URLs in `.env.example` verwenden.

## 2. Laufzeit-Parameter

### UI (Single-Modus und Party-Modus)
- **Sprache A / Sprache B** (`lang_a`, `lang_b`): beliebige ISO-Codes aus den 60+
  Soniox-Sprachen (`de`, `bs`, `hr`, `tr`, `es`, `en`, …). Jede Paar-Kombination ist zulässig.
- **Stimme A / Stimme B** (`voice_a`, `voice_b`): Soniox Voice-Name oder Voice-ID
  (auch geklonte Voices). Stimme A spricht Aussagen auf Sprache A, Stimme B auf Sprache B.
- **Übersetzung anhören** (`tts`): gesprochene Übersetzung an/aus (Text bleibt).
- **Sprecher erkennen** (`diarize`): Speaker-Labels `[0]`/`[1]` (Single-Modus, Standard aus).
- **Audiodatei-URL**: Datei-Testmodus statt Mikrofon (0 %-Ducking = Full Replacement).

### URL-Parameter (Single-Modus)
`/ws/translate?lang_a=de&lang_b=bs&voice_a=Daniel&voice_b=Maya&tts=true&diarize=false[&audio_url=…&audio_duration=…]`

### URL-Parameter (Party-Modus)
Seite mit `?party=a|b&room=<name>` öffnen. Partei A (erste Einwahl) definiert
`lang_a/lang_b/voice_a/voice_b` für den Raum; Partei B erbt.

## 3. Sprachpaare wechseln (heute vs. morgen)

Das Sprachpaar ist reine Konfiguration – kein Code-Eingriff nötig:

- **Demo/Tests:** UI-Dropdowns oder URL-Parameter ändern (z. B. `lang_b=tr` für Türkisch,
  `lang_b=es` für Spanisch). Übersetzung funktioniert zwischen beliebigen Paaren.
- **Telefonie (später):** geplante Varianten siehe `docs/ROADMAP.md`, Abschnitt
  „Sprachpaar-Auswahl im Telefoniebetrieb".

## 4. STT/TTS-Modelle (in `main.py`)

| Parameter | Wert | Anmerkung |
|---|---|---|
| STT-Modell | `stt-rt-v5` | robust auf Telefonie-Audio, schnelles Endpointing |
| TTS-Modell | `tts-rt-v2` | mehrsprachige Stimmen, `pcm_mulaw`/8 kHz für Telefonie möglich |
| Endpointing | `enable_endpoint_detection: true`, `max_endpoint_delay_ms: 500` | beendet Äußerung schnell → geringe Latenz |
| Token-Pause-Flush | 4 s | beugt Soniox-408 vor; Sprechpause beendet Äußerung |
| TTS-Audio (Demo) | `pcm_s16le`, 24 kHz | Browser-Wiedergabe |
| TTS-Audio (Telefonie, geplant) | `pcm_mulaw`, 8 kHz | direktes G.711-RTP, kein Transcoding |

## 5. Voice Cloning einrichten

1. Soniox-Console → Text-to-speech → **Your voices** → Sprachprobe hochladen (kurze,
   ruhige Aufnahme der Zielperson).
2. Voice-ID kopieren und als `voice_a` bzw. `voice_b` eintragen.
3. Effekt: Die Übersetzung wird in der Stimme der sprechenden Person vorgetragen –
   auch in deren fremder Sprache (Stimmen sind mehrsprachig).

## 6. Sicherheit

- `.env` steht in `.gitignore` und ist mit `chmod 600` abgelegt (Key nie committen).
- Keys nicht in Chat/Logs/Tickets kopieren.
