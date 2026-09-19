#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import subprocess
import sys
import time
import os
import re
import json
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import requests
from collections import deque

try:
    import yt_dlp
except ImportError:
    print("📦 'yt-dlp' kütüphanesi eksik, otomatik yükleniyor...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "yt-dlp"])
    import yt_dlp

# ===================== AYARLAR =====================
RTMP_URL = "rtmp://ssh101.bozztv.com:1935/ssh101"
STREAM_KEY = os.getenv("STREAM_KEY") or "maxtv"
RTMP_SERVER = f"{RTMP_URL}/{STREAM_KEY}"

M3U_URL = os.getenv("M3U_URL") or "https://raw.githubusercontent.com/ino8090/0101/refs/heads/main/yerli.m3u"
LOGO_URL = os.getenv("LOGO_URL") or "https://raw.githubusercontent.com/ino8090/0101/refs/heads/main/file_000000007be48210a068edefa7260629.png"

STATE_FILE_NAME = os.getenv("STATE_FILE_NAME", "state_fixtv.json")
STREAM_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
STREAM_REFERER = "https://vidmody.com/"

PROXY_PORT = 8888
CURRENT_TARGET_URL = ""

# ===================== PROXY SERVER =====================
class M3u8ProxyHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return  # Proxy loglarını gizle

    def do_GET(self):
        global CURRENT_TARGET_URL
        if not CURRENT_TARGET_URL:
            self.send_error(404)
            return

        headers = {
            'User-Agent': STREAM_USER_AGENT,
            'Referer': STREAM_REFERER,
            'Origin': 'https://vidmody.com'
        }

        # İstenen URL proxy üzerinden mi geliyor yoksa direkt hedef mi?
        parsed_path = urlparse(self.path)
        params = parse_qs(parsed_path.query)
        
        if "remote_url" in params:
            target = params["remote_url"][0]
        else:
            # Göreli (relative) yollar için base url birleştirme
            base_domain = "/".join(CURRENT_TARGET_URL.split("/")[:-1])
            target = f"{base_domain}{self.path}"

        # Hedefteki .m3u8 olarak istenen şey aslında .jpg olabilir, orijinal adrese çeviriyoruz
        if target.endswith(".m3u8") and not target.endswith("index-v1-a1.m3u8"):
            target_attempt = target.replace(".m3u8", ".jpg")
        else:
            target_attempt = target

        try:
            resp = requests.get(target_attempt, headers=headers, timeout=10)
            if resp.status_code != 200:
                resp = requests.get(target, headers=headers, timeout=10)

            content = resp.content

            # Eğer yanıt bir M3U8 metni ise içindeki TÜM .jpg uzantılarını .m3u8 yap
            if b"#EXTM3U" in content or target.endswith(".m3u8"):
                text_content = resp.text
                text_content = text_content.replace(".jpg", ".m3u8")
                content = text_content.encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'application/vnd.apple.mpegurl')
            else:
                self.send_response(resp.status_code)
                self.send_header('Content-Type', resp.headers.get('Content-Type', 'video/MP2T'))

            self.send_header('Content-Length', str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        except Exception as e:
            self.send_error(500, str(e))

def start_proxy_server():
    server = HTTPServer(('127.0.0.1', PROXY_PORT), M3u8ProxyHandler)
    server.serve_forever()

# Proxy sunucusunu arka planda başlat
proxy_thread = threading.Thread(target=start_proxy_server, daemon=True)
proxy_thread.start()

# ===================== YARDIMCI FONKSİYONLAR =====================
def get_local_state():
    if os.path.exists(STATE_FILE_NAME):
        try:
            with open(STATE_FILE_NAME, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("last_index", 0), data.get("last_seconds", 0)
        except Exception:
            pass
    return 0, 0

def update_local_state(index, seconds):
    try:
        data = {"last_index": int(index), "last_seconds": int(seconds)}
        with open(STATE_FILE_NAME, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def extract_real_m3u8(url):
    print(f"🔍 yt-dlp ile gerçek .m3u8 adresi ayrıştırılıyor: {url}")
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'user_agent': STREAM_USER_AGENT,
        'referer': STREAM_REFERER,
    }

    extracted_url = url
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if 'url' in info:
                extracted_url = info['url']
            elif 'formats' in info and len(info['formats']) > 0:
                extracted_url = info['formats'][-1]['url']
    except Exception as e:
        print(f"⚠️ yt-dlp hatası: {e}")

    return extracted_url

def get_m3u_playlist(m3u_url):
    try:
        resp = requests.get(m3u_url, timeout=15)
        if resp.status_code == 200:
            playlist = []
            pending_title = None
            for raw_line in resp.text.splitlines():
                line = raw_line.strip()
                if not line:
                    continue
                if line.startswith('#EXTINF'):
                    match = re.search(r',(.+)$', line)
                    pending_title = match.group(1).strip() if match else None
                elif not line.startswith('#') and line.startswith('http'):
                    title = pending_title or "Canlı Yayın"
                    playlist.append({"url": line, "title": title})
                    pending_title = None
            return playlist
    except Exception as e:
        print(f"⚠️ M3U okuma hatası: {e}")
    return []

# ===================== ANA DÖNGÜ =====================
def start_stream():
    global CURRENT_TARGET_URL
    current_index, last_seconds = get_local_state()

    while True:
        playlist = get_m3u_playlist(M3U_URL)
        if not playlist:
            time.sleep(10)
            continue

        if current_index >= len(playlist):
            current_index = 0
            last_seconds = 0

        item = playlist[current_index]
        raw_url = item["url"]
        title = item["title"]

        # 1. Gerçek M3U8 adresini çöz
        real_m3u8 = extract_real_m3u8(raw_url)
        CURRENT_TARGET_URL = real_m3u8

        # 2. FFmpeg'e Proxy URL'sini ver (Tüm .jpg -> .m3u8 dönüşümü yerelde anında yapılır)
        proxy_stream_url = f"http://127.0.0.1:{PROXY_PORT}/playlist.m3u8?remote_url={real_m3u8}"

        print(f"🎯 Yayın Başlatılıyor: {title}")
        print(f"🚀 Proxy Üzerinden İletiliyor: {proxy_stream_url}")

        command = [
            'ffmpeg',
            '-y',
            '-ss', str(last_seconds),
            '-i', proxy_stream_url,
            '-c:v', 'libx264',
            '-preset', 'veryfast',
            '-b:v', '2500k',
            '-maxrate', '2500k',
            '-bufsize', '5000k',
            '-r', '25',
            '-g', '50',
            '-c:a', 'aac',
            '-b:a', '128k',
            '-ar', '44100',
            '-f', 'flv',
            RTMP_SERVER
        ]

        process = subprocess.Popen(command, stderr=subprocess.PIPE, universal_newlines=True)

        while True:
            line = process.stderr.readline()
            if not line and process.poll() is not None:
                break

        if process.returncode == 0:
            current_index += 1
            last_seconds = 0
            update_local_state(current_index, 0)
        else:
            print("⚠️ Yayın koptu, tekrar deneniyor...")
            time.sleep(5)

if __name__ == "__main__":
    start_stream()
