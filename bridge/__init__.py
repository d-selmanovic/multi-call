"""Translate-Bridge für Asterisk-Telefonie (Phase 2) – Soniox Python SDK.

Architektur pro Anruf:
  Asterisk externalMedia (RTP G.711 ulaw, 8 kHz) <-> RtpEndpoint
      -> SDK Realtime STT (two_way translation)  [je Partei ein Bein]
      -> SDK Realtime TTS (pcm_mulaw 8k) -> RtpEndpoint des Peers

Die Bridge laeuft auf einem EU-Server neben Asterisk. ARI-Anbindung
(externalMedia-Channels aufmachen, Mix-Minus-Bridges) folgt in Phase 3;
dieses Modul enthaelt die SDK-Pipeline und RTP-Beine.
"""

from .session import CallSession, SessionConfig

__all__ = ["CallSession", "SessionConfig"]
