import os, json, asyncio, base64, time, socket, websockets, httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv

load_dotenv(override=True)

import functools
print = functools.partial(print, flush=True)

SONIOX_API_KEY = os.environ["SONIOX_API_KEY"]
STT_URL = os.environ.get("SONIOX_STT_URL", "wss://stt-rt.soniox.com/transcribe-websocket")
TTS_URL = os.environ.get("SONIOX_TTS_URL", "wss://tts-rt.soniox.com/tts-websocket")

app = FastAPI()

# --- Tracing: JSON-lines pipeline log for debugging -----------------------------
TRACE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", "trace.log")
os.makedirs(os.path.dirname(TRACE_FILE), exist_ok=True)


def trace(room: str, party: str, event: str, **kw) -> None:
    entry = {
        "t": round(time.time(), 3),
        "time": time.strftime("%H:%M:%S"),
        "room": room,
        "party": party,
        "event": event,
        **kw,
    }
    try:
        with open(TRACE_FILE, "a") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass


def get_stt_config(lang_a: str, lang_b: str, diarize: bool) -> dict:
    return {
        "api_key": SONIOX_API_KEY,
        "model": "stt-rt-v5",
        "audio_format": "auto",
        "language_hints": [lang_a, lang_b],
        "enable_language_identification": True,
        "enable_speaker_diarization": diarize,
        "enable_endpoint_detection": True,
        "max_endpoint_delay_ms": 500,
        "translation": {
            "type": "two_way",
            "language_a": lang_a,
            "language_b": lang_b,
        },
    }


def get_tts_config(stream_id: str, voice: str, lang: str) -> dict:
    return {
        "api_key": SONIOX_API_KEY,
        "stream_id": stream_id,
        "model": "tts-rt-v2",
        "voice": voice,
        "language": lang,
        "audio_format": "pcm_s16le",
        "sample_rate": 24000,
    }


@app.websocket("/ws/translate")
async def translation_websocket(
    browser_ws: WebSocket,
    lang_a: str = "de",
    lang_b: str = "bs",
    voice_a: str = "Daniel",
    voice_b: str = "Maya",
    tts: bool = True,
    diarize: bool = False,
    audio_url: str | None = None,
    audio_duration: float | None = None,
) -> None:
    """Two-way live translation. Translation into lang_a is spoken with voice_a,
    into lang_b with voice_b. Binary frames to the browser are prefixed with
    one byte: 0 = audio in lang_a, 1 = audio in lang_b.
    If audio_url + audio_duration are set, the backend fetches and streams the
    file instead of the browser mic (browser plays it locally for follow-along)."""
    await browser_ws.accept()
    stt_ws = None
    tts_ws = None
    voices = {lang_a: voice_a, lang_b: voice_b}
    # (kind, lang, text): kind = "text" | "end" | None (sentinel to stop)
    tts_queue: asyncio.Queue = asyncio.Queue()
    state = {
        "current_stream_id": None,  # tts_sender writes
        "stream_lang": None,
        "stream_used": False,
        "stt_done": False,
    }
    try:
        stt_ws = await websockets.connect(STT_URL)
        await stt_ws.send(json.dumps(get_stt_config(lang_a, lang_b, diarize)))

        if audio_url and audio_duration:
            input_coro = stream_url_to_stt(
                audio_url=audio_url,
                duration=audio_duration,
                stt_ws=stt_ws,
                browser_ws=browser_ws,
            )
        else:
            input_coro = pipe_browser_audio_to_stt(browser_ws, stt_ws)

        if tts:
            tts_ws = await websockets.connect(TTS_URL)
            # Pre-warm a stream per direction so the first token skips setup.
            # The pre-warmed streams stay idle; tts_sender opens fresh utterance
            # streams, which still benefit from the warm connection.
            for lang in (lang_a, lang_b):
                try:
                    await tts_ws.send(json.dumps(get_tts_config(f"prewarm-{lang}", voices[lang], lang)))
                except websockets.WebSocketException:
                    pass

        async with asyncio.TaskGroup() as tg:
            tg.create_task(input_coro)
            tg.create_task(handle_stt(stt_ws, browser_ws, tts_queue if tts else None, state))
            if tts:
                tg.create_task(tts_sender(tts_queue, tts_ws, voices, state))
                tg.create_task(pipe_tts_to_browser(tts_ws, browser_ws, lang_a, state))
                tg.create_task(tts_keepalive(tts_ws))

    except* WebSocketDisconnect:
        pass
    finally:
        for ws in (stt_ws, tts_ws):
            if ws is not None:
                await ws.close()


async def pipe_browser_audio_to_stt(browser_ws: WebSocket, stt_ws) -> None:
    while True:
        data = await browser_ws.receive_bytes()
        await stt_ws.send(data)


async def stream_url_to_stt(
    audio_url: str, duration: float, stt_ws, browser_ws: WebSocket
) -> None:
    """Fetch an audio file and feed it to STT at real-time pace so STT sees it
    as if it were being spoken live. The browser plays the source file locally."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            async with client.stream("GET", audio_url, follow_redirects=True) as resp:
                resp.raise_for_status()
                content_length = int(resp.headers.get("content-length", 0))
                byte_rate = content_length / duration if content_length else 16000
                bytes_per_tick = max(1, int(byte_rate * 0.1))

                buffer = bytearray()
                next_tick = asyncio.get_running_loop().time()
                async for chunk in resp.aiter_bytes():
                    buffer.extend(chunk)
                    while len(buffer) >= bytes_per_tick:
                        await stt_ws.send(bytes(buffer[:bytes_per_tick]))
                        del buffer[:bytes_per_tick]
                        next_tick += 0.1
                        delay = next_tick - asyncio.get_running_loop().time()
                        if delay > 0:
                            await asyncio.sleep(delay)
                if buffer:
                    await stt_ws.send(bytes(buffer))
                # Empty text message signals end-of-audio to the server.
                await stt_ws.send("")
        except httpx.HTTPError as e:
            await browser_ws.send_json(
                {"error_code": "fetch_failed", "error_message": str(e)}
            )


async def handle_stt(stt_ws, browser_ws, tts_queue, state: dict) -> None:
    text_pushed = False
    try:
        while True:
            data = json.loads(await stt_ws.recv())
            # Attach receive timestamp so the browser can measure latency.
            data["_rx_ms"] = round(time.time() * 1000)
            await browser_ws.send_json(data)

            if data.get("error_code") is not None:
                print(f"Error: {data['error_code']} - {data['error_message']}")
                break

            if tts_queue is not None:
                for token in data.get("tokens", []):
                    text = token.get("text")
                    if not text:
                        continue
                    if token.get("translation_status") == "translation":
                        await tts_queue.put(("text", token.get("language"), text))
                        text_pushed = True
            if data.get("finished"):
                break
    except (WebSocketDisconnect, RuntimeError, websockets.ConnectionClosedOK):
        pass
    except websockets.ConnectionClosedError as e:
        print(f"Error {e}")
    finally:
        if tts_queue is not None:
            await tts_queue.put(("end", None, None))
            await tts_queue.put(None)
        state["stt_done"] = True
        if not text_pushed:
            try:
                await browser_ws.send_json({"session_done": True})
            except Exception:
                pass


async def tts_sender(tts_queue: asyncio.Queue, tts_ws, voices: dict, state: dict) -> None:
    counter = 0
    try:
        while True:
            data = await tts_queue.get()
            if data is None:
                break
            kind, lang, text = data

            if kind == "text":
                if state["current_stream_id"] is None:
                    counter += 1
                    sid = f"utter-{counter}-{lang}"
                    await tts_ws.send(json.dumps(get_tts_config(sid, voices[lang], lang)))
                    state["current_stream_id"] = sid
                    state["stream_lang"] = lang
                    state["stream_used"] = False
                # One stream per utterance: if the language flipped mid-utterance,
                # close the old stream and open a fresh one for the new language.
                elif lang != state["stream_lang"]:
                    await tts_ws.send(json.dumps({
                        "stream_id": state["current_stream_id"], "text": "", "text_end": True,
                    }))
                    counter += 1
                    sid = f"utter-{counter}-{lang}"
                    await tts_ws.send(json.dumps(get_tts_config(sid, voices[lang], lang)))
                    state["current_stream_id"] = sid
                    state["stream_lang"] = lang
                    state["stream_used"] = False
                await tts_ws.send(json.dumps({
                    "stream_id": state["current_stream_id"], "text": text, "text_end": False,
                }))
                state["stream_used"] = True

            elif kind == "end":
                if state["current_stream_id"] is not None and state["stream_used"]:
                    await tts_ws.send(json.dumps({
                        "stream_id": state["current_stream_id"], "text": "", "text_end": True,
                    }))
                state["current_stream_id"] = None
                state["stream_lang"] = None
                state["stream_used"] = False
    except websockets.ConnectionClosedOK:
        pass
    except websockets.ConnectionClosedError as e:
        print(f"TTS WS closed: {e}")


async def pipe_tts_to_browser(tts_ws, browser_ws, lang_a: str, state: dict) -> None:
    dir_byte = {f"prewarm-{lang_a}": b"\x00"}
    try:
        while True:
            data = json.loads(await tts_ws.recv())

            if data.get("error_code") is not None:
                print(f"Error in {data.get('stream_id')}: {data['error_code']} - {data['error_message']}")

            audio_b64 = data.get("audio")
            if audio_b64:
                sid = data.get("stream_id", "")
                # Prewarm-<lang> streams and utter-*-<lang> streams share the suffix.
                lang = sid.rsplit("-", 1)[-1]
                prefix = b"\x00" if lang == lang_a else b"\x01"
                if sid not in dir_byte:
                    dir_byte[sid] = prefix
                await browser_ws.send_bytes(dir_byte[sid] + base64.b64decode(audio_b64))

            if data.get("terminated"):
                if state["current_stream_id"] is None or data["stream_id"] != state["current_stream_id"]:
                    pass
                if state["stt_done"] and state["current_stream_id"] is None:
                    try:
                        await browser_ws.send_json({"session_done": True})
                    except Exception:
                        pass
                    await tts_ws.close()
                    break
    except (WebSocketDisconnect, RuntimeError, websockets.ConnectionClosedOK):
        pass
    except websockets.ConnectionClosedError as e:
        print(f"Error {e}")


async def tts_keepalive(tts_ws):
    try:
        while True:
            await asyncio.sleep(20)
            await tts_ws.send(json.dumps({"keep_alive": True}))
    except websockets.ConnectionClosedOK:
        pass
    except websockets.ConnectionClosedError as e:
        print(f"TTS WS closed: {e}")


# ---------------------------------------------------------------------------
# Two-device room mode: each browser is one conversation party.
# Person A (room 1) speaks lang_a and hears lang_b translated; person B
# (room 2) speaks lang_b and hears lang_a translated. Mirrors the telephony
# architecture: every party has its own STT/TTS leg.
# ---------------------------------------------------------------------------

rooms: dict[str, dict] = {}


def get_stt_config_oneway(hints: list[str], target: str) -> dict:
    return {
        "api_key": SONIOX_API_KEY,
        "model": "stt-rt-v5",
        "audio_format": "auto",
        "language_hints": hints,
        "enable_language_identification": True,
        "enable_endpoint_detection": True,
        "max_endpoint_delay_ms": 500,
        "translation": {"type": "one_way", "target_language": target},
    }


@app.websocket("/ws/party")
async def party_websocket(
    browser_ws: WebSocket,
    room: str,
    party: str = "a",
    lang_a: str = "de",
    lang_b: str = "bs",
    voice_a: str = "Daniel",
    voice_b: str = "Maya",
    tts: bool = True,
) -> None:
    """One party of a two-party translation room. Party 'a' defines the room
    config on first join; party 'b' inherits it. Binary frames to a party's
    browser are raw PCM of the OTHER party's translated speech."""
    await browser_ws.accept()
    r = rooms.setdefault(room, {"parties": {}, "config": None})
    if r["config"] is None:
        r["config"] = {"lang_a": lang_a, "lang_b": lang_b, "voice_a": voice_a, "voice_b": voice_b}
    cfg = r["config"]
    peer = "b" if party == "a" else "a"
    my_lang = cfg["lang_a"] if party == "a" else cfg["lang_b"]
    peer_lang = cfg["lang_b"] if party == "a" else cfg["lang_a"]
    peer_voice = cfg["voice_a"] if peer_lang == cfg["lang_a"] else cfg["voice_b"]

    r["parties"][party] = {"ws": browser_ws}
    trace(room, party, "party_connected", my_lang=my_lang, peer_lang=peer_lang, peer_voice=peer_voice)
    tts_queue: asyncio.Queue = asyncio.Queue()
    state = {"current_stream_id": None, "stream_used": False, "stt_done": False}
    stt_holder: dict = {"ws": None}  # current STT connection, swapped on reconnect

    stt_ws = None
    tts_ws = None
    try:
        stt_ws = await websockets.connect(STT_URL)
        stt_holder["ws"] = stt_ws
        await stt_ws.send(json.dumps(get_stt_config_oneway([my_lang, peer_lang], peer_lang)))
        if tts:
            tts_ws = await websockets.connect(TTS_URL)

        async def send_to_peer_bytes(data: bytes) -> None:
            peer_ws = r["parties"].get(peer, {}).get("ws")
            if peer_ws is not None:
                try:
                    await peer_ws.send_bytes(data)
                except Exception:
                    pass

        async def send_to_peer_json(data: dict) -> None:
            peer_ws = r["parties"].get(peer, {}).get("ws")
            if peer_ws is not None:
                try:
                    await peer_ws.send_json(data)
                except Exception:
                    pass

        async def handle_stt_party() -> None:
            nonlocal stt_ws
            try:
                while True:
                    data = json.loads(await stt_ws.recv())
                    data["_rx_ms"] = round(time.time() * 1000)
                    if data.get("error_code") is not None:
                        print(f"[party {party}] STT error: {data['error_code']} - {data.get('error_message')}")
                        trace(room, party, "stt_error", code=data["error_code"], msg=data.get("error_message"))
                        if data["error_code"] == 408:
                            # Idle timeout (e.g. background throttling stalled the
                            # mic stream): reconnect STT and keep the call alive.
                            try:
                                await stt_ws.close()
                            except Exception:
                                pass
                            new_ws = await websockets.connect(STT_URL)
                            await new_ws.send(json.dumps(
                                get_stt_config_oneway([my_lang, peer_lang], peer_lang)
                            ))
                            stt_holder["ws"] = new_ws
                            stt_ws = new_ws
                            trace(room, party, "stt_reconnected")
                            await browser_ws.send_json({
                                "info": "stt_reconnected",
                                "message": "Verbindung wurde automatisch erneuert",
                            })
                            continue
                        # Unrecoverable: forward to browser and give up.
                        try:
                            await browser_ws.send_json(data)
                        except Exception:
                            pass
                        break
                    # Own browser shows what it said (original tokens included).
                    try:
                        await browser_ws.send_json(data)
                    except Exception:
                        break
                    n_orig = 0
                    n_trans = 0
                    for token in data.get("tokens", []):
                        if token.get("text") and token["text"] != "<end>":
                            if token.get("translation_status") == "translation":
                                n_trans += 1
                            else:
                                n_orig += 1
                        if token.get("translation_status") == "translation" and token.get("text"):
                            await tts_queue.put(("text", token["text"]))
                            # Let the peer read the translation as text too.
                            await send_to_peer_json(
                                {"peer_text": token["text"], "peer_lang": peer_lang}
                            )
                    if n_orig or n_trans:
                        trace(room, party, "stt_tokens", original=n_orig, translation=n_trans)
                    if data.get("finished"):
                        trace(room, party, "stt_finished")
                        break
            except websockets.ConnectionClosedOK:
                pass
            finally:
                await tts_queue.put(("end", None))
                await tts_queue.put(None)
                state["stt_done"] = True

        async def tts_sender_party() -> None:
            counter = 0
            try:
                while True:
                    try:
                        item = await asyncio.wait_for(tts_queue.get(), timeout=4.0)
                    except asyncio.TimeoutError:
                        # No translation tokens for 4s: flush the open stream with
                        # text_end. Soniox kills streams idle >~5s (408), and a
                        # pause means the utterance is over anyway.
                        if state["current_stream_id"] is not None and state["stream_used"]:
                            await tts_ws.send(json.dumps(
                                {"stream_id": state["current_stream_id"], "text": "", "text_end": True}
                            ))
                        state["current_stream_id"] = None
                        state["stream_used"] = False
                        continue
                    if item is None:
                        break
                    kind, text = item
                    if kind == "text":
                        if state["current_stream_id"] is None:
                            counter += 1
                            sid = f"utter-{counter}"
                            await tts_ws.send(json.dumps(get_tts_config(sid, peer_voice, peer_lang)))
                            trace(room, party, "tts_stream_open", stream_id=sid)
                            state["current_stream_id"] = sid
                        await tts_ws.send(json.dumps(
                            {"stream_id": state["current_stream_id"], "text": text, "text_end": False}
                        ))
                        state["stream_used"] = True
                    elif kind == "end":
                        if state["current_stream_id"] is not None and state["stream_used"]:
                            await tts_ws.send(json.dumps(
                                {"stream_id": state["current_stream_id"], "text": "", "text_end": True}
                            ))
                        state["current_stream_id"] = None
                        state["stream_used"] = False
            except websockets.ConnectionClosed as e:
                print(f"[party {party}] tts sender conn closed: {e}")

        async def pipe_tts_audio_party() -> None:
            try:
                while True:
                    data = json.loads(await tts_ws.recv())
                    if data.get("audio"):
                        await send_to_peer_bytes(base64.b64decode(data["audio"]))
                    if data.get("terminated") and state["stt_done"] and state["current_stream_id"] is None:
                        break
            except websockets.ConnectionClosedOK:
                pass
            except websockets.ConnectionClosedError as e:
                print(f"[party {party}] tts conn error: {e}")

        async def pipe_mic_to_stt_party() -> None:
            # Reads the CURRENT stt connection from stt_holder so a 408-reconnect
            # doesn't kill this task; buffers mic bytes during the swap.
            mic_bytes = 0
            mic_chunks = 0
            while True:
                data = await browser_ws.receive_bytes()
                mic_chunks += 1
                mic_bytes += len(data)
                if mic_chunks % 40 == 1:  # ~every 10s of audio
                    trace(room, party, "mic_audio", chunks=mic_chunks, bytes=mic_bytes)
                for _ in range(25):  # ~5s of retries while reconnecting
                    try:
                        await stt_holder["ws"].send(data)
                        break
                    except websockets.ConnectionClosed:
                        await asyncio.sleep(0.2)
                else:
                    trace(room, party, "mic_stall", chunks=mic_chunks)
                    raise RuntimeError("STT nicht erreichbar")

        async with asyncio.TaskGroup() as tg:
            tg.create_task(pipe_mic_to_stt_party())
            tg.create_task(handle_stt_party())
            if tts:
                tg.create_task(tts_sender_party())
                tg.create_task(pipe_tts_audio_party())
                tg.create_task(tts_keepalive(tts_ws))

    except* WebSocketDisconnect:
        pass
    finally:
        trace(room, party, "party_disconnected")
        r["parties"].pop(party, None)
        for ws in (stt_ws, tts_ws):
            if ws is not None:
                await ws.close()
        if not r["parties"]:
            rooms.pop(room, None)


# ---------------------------------------------------------------------------
# Auto-discovery: find other demo servers on the LAN and negotiate roles.
# Rule: whoever finds a peer becomes client (party=b), the found one is host
# (party=a). Hosts re-check shortly after start to resolve simultaneous starts
# (higher own IP demotes to client).
# ---------------------------------------------------------------------------


def _own_ip() -> str | None:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("192.0.2.1", 80))  # no traffic sent; just picks the interface
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


async def _scan_subnet(port: int, timeout: float = 0.6) -> list[str]:
    ip = _own_ip()
    if not ip or not ip.startswith(("10.", "192.168.", "172.")):
        return []
    subnet = ip.rsplit(".", 1)[0]

    async def probe(host: str) -> str | None:
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port), timeout=timeout
            )
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass
            return host
        except (OSError, asyncio.TimeoutError):
            return None

    results = await asyncio.gather(*[probe(f"{subnet}.{i}") for i in range(1, 255)])
    return sorted(h for h in results if h)


async def _demo_peers(port: int = 8000) -> tuple[str | None, list[str]]:
    """Returns (own_ip, [peer ips running this demo])."""
    own = _own_ip()
    peers = []
    for host in await _scan_subnet(port):
        if host == own:
            continue
        try:
            async with httpx.AsyncClient(timeout=1.5) as client:
                r = await client.get(f"http://{host}:{port}/health")
                if r.status_code == 200 and r.json().get("app") == "soniox-translate-demo":
                    peers.append(host)
        except (httpx.HTTPError, ValueError):
            continue
    return own, peers


@app.get("/health")
async def health():
    return {"app": "soniox-translate-demo"}


@app.get("/discover")
async def discover(port: int = 8000):
    """Scan the LAN for other demo servers. Frontend: if peers found -> connect
    to first peer as party=b; else become host (party=a)."""
    own, peers = await _demo_peers(port)
    return JSONResponse({"own_ip": own, "peers": peers, "peer": peers[0] if peers else None})


@app.get("/discover/check-host")
async def check_host(port: int = 8000):
    """Called by a host a few seconds after start: if another host appeared and
    has a lower IP, we demote (return peer to join). Else stay host."""
    own, peers = await _demo_peers(port)
    if peers and own and own > peers[0]:
        return JSONResponse({"stay_host": False, "peer": peers[0]})
    return JSONResponse({"stay_host": True, "peer": None})


@app.get("/trace")
async def trace_log(lines: int = 200):
    """Last N trace lines (JSON) for debugging."""
    try:
        with open(TRACE_FILE) as fh:
            all_lines = fh.readlines()
        return [json.loads(l) for l in all_lines[-lines:]]
    except OSError:
        return []


app.mount("/", StaticFiles(directory="frontend", html=True), name="static")
