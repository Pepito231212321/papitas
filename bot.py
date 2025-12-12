import sys
import time
import random
import datetime
import threading
import asyncio
import websockets
import json
import os
from threading import Thread, Semaphore
from fake_useragent import UserAgent
import re
import json
import tls_client

# -------------------------
#  TU TOKEN OFICIAL
# -------------------------
CLIENT_TOKEN = "e1393935a959b4020a4491574f6490129f678acdaa92760471263db43487f823"

channel = ""
channel_id = None
stream_id = None
max_threads = 0
threads = []
thread_limit = None
active = 0
stop = False
start_time = None
lock = threading.Lock()
connections = 0
attempts = 0
pings = 0
heartbeats = 0
viewers = 0
last_check = 0


# -----------------------------
# Helpers
# -----------------------------
def clean_channel_name(name):
    if "kick.com/" in name:
        parts = name.split("kick.com/")
        channel = parts[1].split("/")[0].split("?")[0]
        return channel.lower()
    return name.lower()


# -----------------------------
#   TLS CLIENT SESSION FACTORY
# -----------------------------
def build_session():
    return tls_client.Session(
        client_identifier="chrome_131",
        random_tls_extension_order=True,
        verify=False,  # <--- cambiar a verify=False
        ja3_string="771,4865-4866-4867-49195-49196-52392-52393-49199-49200-158-159-49171-49172-49157-49158-49161-49162,23-65281-10-11-35-16-5-18-51-45,29-23-24,0"
    )



# -----------------------------
#   CHANNEL INFO
# -----------------------------
def get_channel_info(slug):
    global channel_id, stream_id

    url = f"https://kick.com/{slug}"

    s = build_session()
    s.headers.update({
        "User-Agent": UserAgent().random,
        "Accept-Language": "es-ES,es;q=0.9"
    })

    try:
        r = s.get(url, timeout=15)
        print("DEBUG STATUS:", r.status_code)
        print("DEBUG BYTES:", r.text[:140])

        if r.status_code != 200:
            return None

        match = re.search(r'__NEXT_DATA__" type="application/json">(.+?)</script>', r.text)
        if not match:
            print("NO NEXT_DATA")
            return None

        data = json.loads(match.group(1))
        channel = data["props"]["pageProps"]["data"]["channel"]

        channel_id = channel["id"]
        stream = channel.get("livestream")
        stream_id = stream["id"] if stream else None

        print(f"[OK] channel_id={channel_id}, stream_id={stream_id}")
        return channel_id

    except Exception as e:
        print("ERROR:", e)
        return None


# -----------------------------
# GET TOKEN
# -----------------------------
def get_token():
    s = build_session()

    s.headers.update({
        "User-Agent": UserAgent().random,
        "Accept": "*/*",
        "X-CLIENT-TOKEN": CLIENT_TOKEN
    })

    endpoints = [
        "https://websockets.kick.com/viewer/v1/token",
        "https://kick.com/api/websocket/token",
        "https://kick.com/api/v1/websocket/token"
    ]

    for url in endpoints:
        try:
            r = s.get(url, timeout=10)
            if r.status_code == 200:
                data = r.json()
                token = data.get("data", {}).get("token") or data.get("token")
                if token:
                    return token
        except:
            pass

    return None


# -----------------------------
# VIEWER COUNT
# -----------------------------
def get_viewer_count():
    global viewers, last_check
    if not stream_id:
        return 0

    s = build_session()
    s.headers.update({
        "User-Agent": UserAgent().random,
        "Accept": "application/json"
    })

    url = f"https://kick.com/current-viewers?ids[]={stream_id}"

    try:
        r = s.get(url, timeout=10)
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, list) and data:
                viewers = data[0].get("viewers", 0)
                last_check = time.time()
                return viewers
    except:
        pass

    return 0


# -----------------------------
# STATS DISPLAY
# -----------------------------
def show_stats():
    global stop, start_time, viewers, last_check

    print("\n\n\n")
    os.system('cls' if os.name == 'nt' else 'clear')

    while not stop:
        now = time.time()

        if now - last_check >= 5:
            get_viewer_count()

        with lock:
            elapsed = datetime.datetime.now() - start_time if start_time else 0
            duration = f"{int(elapsed.total_seconds())}s"
            ws = connections
            att = attempts
            ping = pings
            hb = heartbeats

        print("\033[3A", end="")
        print(f"\033[2K\r[x] Connections: {ws} | Attempts: {att}")
        print(f"\033[2K\r[x] Pings: {ping} | Heartbeats: {hb} | Duration: {duration} | Stream ID: {stream_id}")
        print(f"\033[2K\r[x] Viewers: {viewers} | Updated: {time.strftime('%H:%M:%S', time.localtime(last_check))}")

        time.sleep(1)


# -----------------------------
# WEBSOCKET
# -----------------------------
async def websocket_handler(token):
    global connections, pings, heartbeats, stop

    url = f"wss://websockets.kick.com/viewer/v1/connect?token={token}"

    try:
        async with websockets.connect(url) as ws:
            with lock:
                connections += 1

            handshake = {
                "type": "channel_handshake",
                "data": {"message": {"channelId": channel_id}}
            }
            await ws.send(json.dumps(handshake))
            with lock:
                heartbeats += 1

            count = 0
            while not stop and count < 10:
                count += 1
                await ws.send(json.dumps({"type": "ping"}))

                with lock:
                    pings += 1

                await asyncio.sleep(12 + random.randint(1, 5))

    except:
        pass
    finally:
        with lock:
            if connections > 0:
                connections -= 1


# -----------------------------
# THREAD START
# -----------------------------
def connect():
    global attempts

    with lock:
        attempts += 1

    token = get_token()
    if not token:
        thread_limit.release()
        return

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        loop.run_until_complete(websocket_handler(token))
    except:
        pass

    loop.close()
    thread_limit.release()


# -----------------------------
# MAIN RUN LOOP
# -----------------------------
def run(thread_count, channel_name):
    global channel, max_threads, thread_limit, start_time, channel_id

    channel = clean_channel_name(channel_name)
    max_threads = thread_count
    thread_limit = Semaphore(max_threads)

    start_time = datetime.datetime.now()
    channel_id = get_channel_info(channel)

    Thread(target=show_stats, daemon=True).start()

    while True:
        if stop:
            break

        if thread_limit.acquire():
            t = Thread(target=connect, daemon=True)
            threads.append(t)
            t.start()
            time.sleep(0.35)


# -----------------------------
# ENTRY POINT
# -----------------------------
if __name__ == "__main__":
    try:
        channel_input = os.getenv("CHANNEL")
        thread_input = os.getenv("VIEWERS")

        if not channel_input:
            print("Error: falto CHANNEL")
            sys.exit(1)

        if not thread_input:
            thread_input = 250

        thread_input = int(thread_input)

        print(f"Starting bot for channel {channel_input} with {thread_input} viewers")
        run(thread_input, channel_input)

    except KeyboardInterrupt:
        stop = True
        print("Stopping...")
        sys.exit(0)

