"""One translated call: two parties, SDK STT (two_way) + SDK TTS per party.

Pipeline per Partei X (Sprache lang_x, Peersprache lang_y):
  RTP von X -> SDK Realtime STT (two_way lang_x<->lang_y)
      Übersetzungs-Tokens (in lang_y) -> TTS-Stream (Stimme fuer lang_y)
      TTS audio (pcm_mulaw 8k) -> RTP an Partei Y

Umsetzung der Production-Learnings aus Phase 1:
- ein TTS-Stream pro Äußerung; text_end bei Endpoint ODER nach 4 s Token-Pause
- TTS audio direkt als pcm_mulaw 8 kHz -> kein Transcoding ins Telefonnetz
- STT: SDK sendet Keepalive automatisch bei pause(); wir senden Audio nur
  bei Sprache (RTP fließt aber kontinuierlich -> Session bleibt aktiv)
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from uuid import uuid4

from soniox import AsyncSonioxClient
from soniox.types import RealtimeSTTConfig, RealtimeTTSConfig, TranslationConfig

from .rtp import RtpEndpoint, pcm_s16le_to_mulaw

FLUSH_AFTER_S = 4.0  # Token-Pause beendet die Äußerung (Soniox-Stream-Timeout ~5s)


@dataclass
class Party:
    name: str                     # "a" | "b"
    lang: str                     # eigene Sprache
    rtp: RtpEndpoint              # Asterisk-Bein dieser Partei
    peer: "Party | None" = None


@dataclass
class SessionConfig:
    lang_a: str = "de"
    lang_b: str = "bs"
    voice_a: str = "Daniel"       # Stimme für deutsche Ausgabe
    voice_b: str = "Maya"         # Stimme für bosnische Ausgabe


class CallSession:
    """Verwaltet beide Parteien eines übersetzten Anrufs."""

    def __init__(self, config: SessionConfig, client: AsyncSonioxClient | None = None):
        self.cfg = config
        self.client = client or AsyncSonioxClient()
        self._own_client = client is None
        self.parties: dict[str, Party] = {}
        self._tasks: list[asyncio.Task] = []
        self._closed = False

    def add_party(self, name: str, rtp: RtpEndpoint) -> Party:
        lang = self.cfg.lang_a if name == "a" else self.cfg.lang_b
        p = Party(name=name, lang=lang, rtp=rtp)
        self.parties[name] = p
        if len(self.parties) == 2:
            self.parties["a"].peer = self.parties["b"]
            self.parties["b"].peer = self.parties["a"]
        return p

    async def start(self) -> None:
        if len(self.parties) != 2:
            raise RuntimeError("Beide Parteien müssen per add_party() registriert sein.")
        for party in self.parties.values():
            await party.rtp.start()
            self._tasks.append(asyncio.create_task(self._run_party(party)))

    # ------------------------------------------------------------------ STT

    def _stt_config(self, party: Party) -> RealtimeSTTConfig:
        peer_lang = party.peer.lang
        return RealtimeSTTConfig(
            model="stt-rt-v5",
            audio_format="pcm_mulaw",
            sample_rate=8000,
            num_channels=1,
            language_hints=[party.lang, peer_lang],
            enable_language_identification=True,
            enable_endpoint_detection=True,
            max_endpoint_delay_ms=500,
            translation=TranslationConfig(
                type="two_way",
                language_a=party.lang,
                language_b=peer_lang,
            ),
        )

    async def _run_party(self, party: Party) -> None:
        """STT-Eingabe dieser Partei -> Übersetzung -> TTS an den Peer."""
        assert party.peer is not None
        stt = self.client.realtime.stt
        async with stt.connect(config=self._stt_config(party)) as session:
            sender = asyncio.create_task(self._feed_stt(party, session))
            try:
                async for event in session.receive_events():
                    if event.error_code:
                        print(f"[{party.name}] STT error: {event.error_code}")
                        continue
                    for token in event.tokens:
                        if token.translation_status == "translation" and token.text:
                            await self._to_tts(party, token.text)
            finally:
                sender.cancel()

    async def _feed_stt(self, party: Party, session) -> None:
        """RTP (mu-law) in die STT-Session; mu-law wird als Rohbytes direkt
        weitergereicht (audio_format=pcm_mulaw)."""
        try:
            while not self._closed:
                mulaw = await party.rtp.read_pcm()
                session.send_bytes(mulaw)
        except asyncio.CancelledError:
            pass

    # ------------------------------------------------------------------ TTS

    async def _to_tts(self, party: Party, text: str) -> None:
        """Übersetztes Token in einen TTS-Stream an den Peer (ein Stream pro
        Äußerung; 4-s-Pause-Flush gegen Soniox request_timeout)."""
        peer = party.peer
        assert peer is not None
        voice = self.cfg.voice_a if peer.lang == self.cfg.lang_a else self.cfg.voice_b
        key = f"{party.name}_tts"
        state = getattr(self, f"_tts_{key}", None)
        now = time.monotonic()
        if state is None or now - state["last"] > FLUSH_AFTER_S:
            await self._close_tts_stream(key)
            state = {"stream": None, "last": now}
            setattr(self, f"_tts_{key}", state)

        tts = self.client.realtime.tts
        if state["stream"] is None:
            stream = await tts.connect(
                config=RealtimeTTSConfig(
                    stream_id=f"{key}-{uuid4()}",
                    model="tts-rt-v2",
                    language=peer.lang,
                    voice=voice,
                    audio_format="pcm_mulaw",
                    sample_rate=8000,
                )
            )
            state["stream"] = stream
            state["task"] = asyncio.create_task(self._drain_tts(peer, stream))
        state["last"] = now
        await state["stream"].send_text_chunk(text, text_end=False)

    async def _drain_tts(self, peer: Party, stream) -> None:
        try:
            async for chunk in stream.receive_audio_chunks():
                peer.rtp.feed_pcm_mulaw(chunk)  # mu-law direkt ins RTP
        except Exception as e:  # Stream-Fehler toeten nicht die Session
            print(f"TTS stream error ({peer.name}): {e}")

    async def _close_tts_stream(self, key: str) -> None:
        state = getattr(self, f"_tts_{key}", None)
        if state and state.get("stream") is not None:
            try:
                await state["stream"].finish()
            except Exception:
                pass
            state["stream"] = None

    # ------------------------------------------------------------------ life

    async def close(self) -> None:
        self._closed = True
        for key in ("a_tts", "b_tts"):
            await self._close_tts_stream(key)
        for t in self._tasks:
            t.cancel()
        for p in self.parties.values():
            await p.rtp.close()
        if self._own_client:
            await self.client.aclose()
