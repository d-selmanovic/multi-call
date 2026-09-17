# Architektur

Ziel: **Live-Telefonübersetzung** – Person A ruft eine deutsche Nummer an und spricht
Bosnisch/Kroatisch, Person B (deutsch) nimmt auf einem normalen Telefon ab. Beide hören
ausschließlich die Übersetzung in ihrer Sprache, in möglichst der Stimme des Gesprächspartners
(Voice Cloning, siehe unten). Keine App nötig – normale Anrufe auf Mobil-/Festnetznummern.

## Gesamt-Architektur (Zielbild Telefonie)

```
Anrufer A (bs/hr) ──SIP/RTP──> Asterisk ──RTP G.711 ulaw 8k──> Translate-Bridge (EU)
                                                                  ├─ STT two_way ──> Soniox EU
Empfänger B (de)  <──SIP/RTP── Asterisk <──RTP G.711 ulaw 8k──  └─ TTS <─────────────
```

- Pro Anruf **zwei** Asterisk-`externalMedia`-Channels (je Partei ein RTP-Bein, Mix-Minus
  gegen Echo), per ARI an die Bridge gestreamt.
- Bridge routet anhand des Token-`language`-Feldes: de→bs (TTS-Stimme für Bosnisch) und
  bs/hr→de (TTS-Stimme für Deutsch).
- **Kein Originalton** erreicht die Gegenstelle – Full Replacement, keine Doppelstimmen.
- Telefonie-Codecs: TTS kann `pcm_mulaw`/`pcm_alaw` direkt in 8 kHz → G.711 ohne Transcoding.
- Soniox **EU-Endpoints** (`stt-rt.eu.soniox.com`, `tts-rt.eu.soniox.com`), Key ist EU-gebunden.

## Was diese Repo ist: Demo/Prototyp (Phase 1)

FastAPI-Backend (`main.py`) + Vanilla-JS-Frontend (`frontend/`), direkt auf den Soniox
WebSocket-APIs (kein SDK). Zwei Modi, beide mit derselben Kern-Pipeline:

### Modus 1: Single-Client (`/ws/translate`)

Ein Browser = beide Gesprächspartner (z. B. ein Mikrofon im Raum). STT mit
`translation: {type: "two_way", language_a, language_b}`. Übersetzungs-Tokens werden anhand
ihres `language`-Feldes einer von zwei TTS-Stimmen zugeordnet. Zusätzlich: Datei-Modus
(`audio_url`, Follow-along mit 0 %-Ducking) und optionale Diarization.

### Modus 2: Party/Room-Modus (`/ws/party`) – die Telefonie-Vorbereitung

Zwei Geräte = zwei Parteien (z. B. zwei Räume). Jede Partei hat **eigenen** STT- und
TTS-Pfad (eigenes Mikro, eigene Session) – dieselbe Architektur wie im Anruf:
Partei A (de) spricht → STT one-way nach bs → TTS → **nur** an B. Umgekehrt für B.
Der erste Beitritt (Partei A) definiert Sprachen/Stimmen des Raums.

```
Gerät A: Mic ──> STT(one_way → bs) ──> TTS(Stimme_b) ──> Gerät B (nur Übersetzung)
Gerät B: Mic ──> STT(one_way → de) ──> TTS(Stimme_a) ──> Gerät A (nur Übersetzung)
```

## Kern-Pipeline (beide Modi)

Pro Verbindung laufen Coroutinen parallel (`asyncio.TaskGroup`):

| Task | Aufgabe |
|---|---|
| `pipe_browser_audio_to_stt` / `stream_url_to_stt` | Mikro-Bytes bzw. Datei im Echtzeittakt an STT |
| `handle_stt` | STT-Ergebnisse an Browser; Übersetzungs-Tokens → TTS-Queue; `finished`/Fehler |
| `tts_sender` | Pro Äußerung ein TTS-Stream; `text_end` bei Endpoint **oder nach 4 s Token-Pause** |
| `pipe_tts_to_browser` | Base64-Audio dekodiert an Browser/Peer |
| `tts_keepalive` | `keep_alive` alle 20 s (idle TTS-Verbindungen) |

## Wichtige Soniox-Erkenntnisse (gültig Stand 2026-09-17)

1. **EU-Endpoints** erfordern EU Data Residency im Console-Account. Global-Endpoints liefern
   mit EU-Key 401.
2. **TTS 408-Timeout:** Soniox beendet TTS-Streams nach ~5 s ohne Audio-Aktivität
   (`408 Request timeout`). → Sender schließt Streams nach 4 s ohne Token mit `text_end`.
   Eine Sprechpause beendet damit die Äußerung. Ohne diesen Flush stirbt das Bein.
3. **TTS-Streaming:** Audio kann vor `text_end` fließen, startet in der Praxis aber oft erst
   am Äußerungsende – TTFA typisch ~0,2–2 s nach `text_end`. Einflussfaktoren: Sprache/Stimme.
4. **End-of-Audio-Marker** an STT muss eine leere **Text**-Nachricht sein (`ws.send("")`),
   nicht ein leeres Binär-Frame.
5. **Voice Cloning:** `voice`-Feld akzeptiert geklonte Voice-IDs; Stimmen sind mehrsprachig
   (eigene Stimme spricht fremde Sprache). Konsole → Text-to-speech → Your voices.
6. **Sprachpaare frei wählbar:** Übersetzung funktioniert zwischen beliebigen Paaren der
   60+ Sprachen (u. a. `bs`, `hr`, `de`, `tr`, `es`, `en`). Sprachpaar = reine Konfiguration.

## Latenz-Erkenntnisse (Messung test_file.py, EU-Endpoints)

- Erster Übersetzungstoken: ~4–5 s nach Audio-Start (Satz-ende-abhängig)
- TTS-Time-to-First-Audio: ~0,2–2 s
- Backend-Pipeline selbst: <5 ms (Queue-basiert)

## Stimmen-Konzept

- `voice_a` = Stimme, mit der Aussagen **auf Deutsch** gesprochen werden (Ziel: Klon der
  deutsch sprechenden Partei)
- `voice_b` = Stimme für Aussagen **auf Bosnisch/Kroatisch** (Ziel: Klon der bs/hr-Partei)
- Ohne Klon: beliebige Shared Voices (Console → Voices, z. B. Daniel, Maya)
- Regel: **Die Stimme gehört der Person, die spricht** – übersetzt in die Sprache des Zuhörers.

## Bezug zur offiziellen Soniox-Demo

Struktur angelehnt an `soniox_examples/apps/soniox-speech-to-speech-translation-demo`,
aber: two-way translation statt one-way, Routing nach Token-`language` auf zwei Stimmen,
Party-Modus mit getrennten Beinen, EU-Endpoints, 408-Flush, TTS-Reconnect, CLI-Latenztest.
Details: siehe Git-History und `docs/ROADMAP.md`.
