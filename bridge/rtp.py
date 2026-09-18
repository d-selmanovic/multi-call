"""Minimal RTP endpoint for G.711 mu-law (PCMU/8000) telephony audio.

One RtpEndpoint represents one direction pair of a call leg:
- receiving: Asterisk -> bridge (jitter buffer, yields PCM chunks)
- sending:   bridge -> Asterisk (packetizes PCM into 20 ms RTP packets)

SSRC/sequencing are self-managed; this is intentionally small and targets a
direct Asterisk externalMedia peer on a trusted LAN/VPN, not general internet.
"""

from __future__ import annotations

import asyncio
import random
import socket
import struct
import time
from collections import deque

PT_PCMU = 0
PAYLOAD_MS = 20
SAMPLE_RATE = 8000
BYTES_PER_PACKET = 160 * 1  # 8 kHz * 20 ms * 8-bit mulaw


class RtpEndpoint:
    """UDP RTP endpoint bound locally; sends to a fixed Asterisk peer."""

    def __init__(self, listen_port: int, peer_ip: str, peer_port: int):
        self.peer = (peer_ip, peer_port)
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.bind(("0.0.0.0", listen_port))
        self._sock.setblocking(False)
        self._seq = random.randint(0, 0xFFFF)
        self._ssrc = random.randint(0, 0xFFFFFFFF)
        self._ts = random.randint(0, 0xFFFFFFFF)
        self._queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=200)
        self._closed = False
        self._recv_task: asyncio.Task | None = None

    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        self._recv_task = asyncio.create_task(self._recv_loop(loop))

    async def _recv_loop(self, loop) -> None:
        # De-jitter: buffer ~60 ms, drain oldest on overflow.
        buf: deque[bytes] = deque(maxlen=12)
        while not self._closed:
            try:
                data, _ = await loop.sock_recvfrom(self._sock, 2048)
            except OSError:
                break
            if len(data) < 12:
                continue
            _, _, _, _, pt, _ = struct.unpack("!BBH H B B", data[:12]) if False else (0, 0, 0, 0, data[1] & 0x7F, 0)
            payload = data[12:]
            if pt != PT_PCMU:
                continue
            buf.append(payload)
            if len(buf) >= 3:  # ~60 ms
                chunk = b"".join(buf)
                buf.clear()
                try:
                    self._queue.put_nowait(chunk)
                except asyncio.QueueFull:
                    _ = self._queue.get_nowait()
                    self._queue.put_nowait(chunk)

    async def read_pcm(self) -> bytes:
        """RTP payloads (mu-law) as they arrive; caller converts if needed."""
        return await self._queue.get()

    def feed_pcm_mulaw(self, pcm_mulaw: bytes) -> None:
        """Packetize mu-law PCM and send to Asterisk at real-time pace."""
        for off in range(0, len(pcm_mulaw), BYTES_PER_PACKET):
            pkt = pcm_mulaw[off:off + BYTES_PER_PACKET]
            if len(pkt) < BYTES_PER_PACKET:
                pkt = pkt + b"\xff" * (BYTES_PER_PACKET - len(pkt))  # silence pad
            header = struct.pack("!BBHII", 0x80, PT_PCMU, self._seq, self._ts, self._ssrc)
            self._sock.sendto(header + pkt, self.peer)
            self._seq = (self._seq + 1) & 0xFFFF
            self._ts = (self._ts + BYTES_PER_PACKET) & 0xFFFFFFFF

    async def close(self) -> None:
        self._closed = True
        if self._recv_task:
            self._recv_task.cancel()
        self._sock.close()


_BIAS = 0x84
_CLIP = 32635

# G.711 mu-law encoding table (segment endpoints)
_SEG_END = (0x1F, 0x3F, 0x7F, 0xFF, 0x1FF, 0x3FF, 0x7FF, 0xFFF)


def _search(val: int) -> int:
    for i, end in enumerate(_SEG_END):
        if val <= end:
            return i
    return 8


def pcm_s16le_to_mulaw(pcm: bytes) -> bytes:
    """16-bit signed LE PCM -> 8-bit mu-law (audioop.lin2ulaw replacement,
    audioop was removed in Python 3.13)."""
    out = bytearray()
    for (sample,) in struct.iter_unpack("<h", pcm[: len(pcm) - (len(pcm) % 2)]):
        sign = 0x80 if sample < 0 else 0x00
        s = -sample - 1 if sample < 0 else sample
        if s > _CLIP:
            s = _CLIP
        s += _BIAS
        seg = _search(s >> 2)
        if seg >= 8:
            out.append(0x7F ^ sign)
        else:
            uval = (seg << 4) | ((s >> (seg + 1)) & 0x0F)
            out.append((~uval) & 0xFF | sign)
    return bytes(out)
