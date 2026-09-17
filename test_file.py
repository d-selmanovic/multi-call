"""Two-way speech translation file test.

Streams an audio file through Soniox real-time STT (two-way translation) and
synthesizes each direction's translation with TTS, writing one WAV per target
language. Prints latency measurements (STT first token -> TTS first audio).

Usage:
    uv run python test_file.py --audio_path input.wav --lang_a de --lang_b bs
"""

import argparse
import asyncio
import base64
import json
import os
import struct
import time
import wave

import websockets
from dotenv import load_dotenv

load_dotenv(override=True)

SONIOX_API_KEY = os.environ["SONIOX_API_KEY"]
STT_URL = os.environ.get("SONIOX_STT_URL", "wss://stt-rt.soniox.com/transcribe-websocket")
TTS_URL = os.environ.get("SONIOX_TTS_URL", "wss://tts-rt.soniox.com/tts-websocket")

# Chunk size for real-time pacing of file audio (0.1 s of 16-bit mono).
CHUNK_BYTES = 16000 * 2 // 10


def stt_config(lang_a: str, lang_b: str) -> dict:
    return {
        "api_key": SONIOX_API_KEY,
        "model": "stt-rt-v5",
        "audio_format": "auto",
        "language_hints": [lang_a, lang_b],
        "enable_language_identification": True,
        "enable_endpoint_detection": True,
        "max_endpoint_delay_ms": 500,
        "translation": {"type": "two_way", "language_a": lang_a, "language_b": lang_b},
    }


def tts_config(stream_id: str, lang: str, voice: str) -> dict:
    return {
        "api_key": SONIOX_API_KEY,
        "stream_id": stream_id,
        "model": "tts-rt-v2",
        "voice": voice,
        "language": lang,
        "audio_format": "pcm_s16le",
        "sample_rate": 24000,
    }


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audio_path", required=True)
    parser.add_argument("--lang_a", default="de")
    parser.add_argument("--lang_b", default="bs")
    parser.add_argument("--voice_a", default="Daniel")
    parser.add_argument("--voice_b", default="Maya")
    parser.add_argument("--output", default="translation")
    args = parser.parse_args()

    audio_out = {args.lang_a: bytearray(), args.lang_b: bytearray()}
    timings = {"audio_sent_at": None, "first_token_at": None, "first_tts_at": None}
    counter = 0
    current = {"stream_id": None, "lang": None}

    def note(key: str) -> None:
        if timings[key] is None:
            timings[key] = time.time()
            print(f"[{time.strftime('%H:%M:%S')}] {key}")

    holder = {"ws": None}  # TTS socket, reconnectable

    async def send_text(lang: str, text: str, end: bool) -> None:
        nonlocal counter
        if current["stream_id"] is None or (not end and lang != current["lang"]):
            counter += 1
            current.update(stream_id=f"u-{counter}-{lang}", lang=lang)
            await holder["ws"].send(json.dumps(tts_config(current["stream_id"], lang, getattr(args, f"voice_{'a' if lang == args.lang_a else 'b'}"))))
        try:
            await holder["ws"].send(json.dumps({"stream_id": current["stream_id"], "text": text, "text_end": end}))
        except websockets.ConnectionClosed:
            # Server timed out our idle TTS socket — reconnect and retry once.
            holder["ws"] = await websockets.connect(TTS_URL, open_timeout=10)
            tts_tasks.append(asyncio.create_task(recv_tts()))
            await holder["ws"].send(json.dumps(tts_config(current["stream_id"], lang, getattr(args, f"voice_{'a' if lang == args.lang_a else 'b'}"))))
            await holder["ws"].send(json.dumps({"stream_id": current["stream_id"], "text": text, "text_end": end}))
        if end:
            current.update(stream_id=None, lang=None)

    async def recv_tts() -> None:
        ws = holder["ws"]
        try:
            while True:
                data = json.loads(await ws.recv())
                if audio_b64 := data.get("audio"):
                    lang = data["stream_id"].rsplit("-", 1)[-1]
                    audio_out[lang].extend(base64.b64decode(audio_b64))
                    note("first_tts_at")
        except websockets.ConnectionClosedOK:
            pass

    async def keepalive() -> None:
        while True:
            await asyncio.sleep(20)
            try:
                await holder["ws"].send(json.dumps({"keep_alive": True}))
            except websockets.ConnectionClosed:
                return

    async with websockets.connect(STT_URL) as stt_ws:
        holder["ws"] = await websockets.connect(TTS_URL, open_timeout=10)
        await stt_ws.send(json.dumps(stt_config(args.lang_a, args.lang_b)))
        tts_tasks = [asyncio.create_task(recv_tts()), asyncio.create_task(keepalive())]

        async def stream_file() -> None:
            with open(args.audio_path, "rb") as fh:
                while chunk := fh.read(CHUNK_BYTES):
                    await stt_ws.send(chunk)
                    note("audio_sent_at")
                    await asyncio.sleep(0.1)
            await stt_ws.send("")

        sender = asyncio.create_task(stream_file())

        while True:
            data = json.loads(await stt_ws.recv())
            if data.get("error_code"):
                print(f"Error: {data['error_code']} - {data['error_message']}")
                break
            if any(t.get("translation_status") == "translation" for t in data.get("tokens", [])):
                note("first_token_at")
            for token in data.get("tokens", []):
                if token.get("translation_status") == "translation" and token.get("text"):
                    await send_text(token["language"], token["text"], end=False)
            if data.get("finished"):
                break
        await sender

        # Close the final TTS stream, drain remaining audio, then close the socket.
        await send_text(args.lang_a, "", end=True)
        await asyncio.sleep(3)
        await holder["ws"].close()
        await asyncio.gather(*tts_tasks, return_exceptions=True)

    for lang, pcm in audio_out.items():
        if not pcm:
            continue
        path = f"{args.output}_to_{lang}.wav"
        with wave.open(path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(24000)
            wf.writeframes(bytes(pcm))
        print(f"wrote {path} ({len(pcm) / 48000:.1f}s)")

    if timings["first_token_at"] and timings["audio_sent_at"]:
        print(f"STT/translation first token: {timings['first_token_at'] - timings['audio_sent_at']:.2f}s after audio start")
    if timings["first_tts_at"] and timings["first_token_at"]:
        print(f"TTS time-to-first-audio:     {timings['first_tts_at'] - timings['first_token_at']:.2f}s")


if __name__ == "__main__":
    asyncio.run(main())
