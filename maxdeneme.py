#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import subprocess
import sys
import time
import os
import re
import json
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
GITHUB_STEP_SUMMARY = os.getenv("GITHUB_STEP_SUMMARY")

STREAM_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
STREAM_REFERER = "https://vidmody.com/"

LOGO_OPACITY = float(os.getenv("LOGO_OPACITY", "0.4"))
TEXT_OPACITY = float(os.getenv("TEXT_OPACITY", "0.5"))
BOLD_FONT_PATH = os.getenv("BOLD_FONT_PATH", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")


def format_hms(total_seconds):
    total_seconds = int(total_seconds)
    hrs = total_seconds // 3600
    mins = (total_seconds % 3600) // 60
    secs = total_seconds % 60
    return f"{hrs:02d}:{mins:02d}:{secs:02d}"


def get_local_state():
    if os.path.exists(STATE_FILE_NAME):
        if os.path.getsize(STATE_FILE_NAME) == 0:
            return 0, 0, ""
        try:
            with open(STATE_FILE_NAME, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("last_index", 0), data.get("last_seconds", 0), data.get("last_url", "")
        except Exception:
            pass
    return 0, 0, ""


def update_local_state(index, seconds, url=""):
    try:
        data = {"last_index": int(index), "last_seconds": int(seconds), "last_url": url}
        with open(STATE_FILE_NAME, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"⚠️ Yerel state yazma hatası: {e}")


def extract_real_m3u8(url):
    """yt-dlp ile adresi çözer ve ana adresteki .gif/.jpg uzantılarını temizler."""
    if ".m3u8" in url.lower() and "vidmody.com/vs/" not in url.lower():
        return url, STREAM_USER_AGENT, STREAM_REFERER

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
        print(f"⚠️ yt-dlp ayrıştırma hatası: {e}")

    # Ana URL'deki sahte .gif / .jpg temizliği
    extracted_url = re.sub(r'\.(gif|jpg)(\?.*)?$', '.m3u8\\2', extracted_url)
    return extracted_url, STREAM_USER_AGENT, STREAM_REFERER


def create_clean_local_m3u8(remote_m3u8_url, ua, ref):
    """
    M3U8 dosyasının İÇERİĞİNİ indirip tüm .jpg segment satırlarını .m3u8 yapar.
    Oluşan yeni listeyi yerel bir dosyaya yazar.
    """
    headers = {
        'User-Agent': ua,
        'Referer': ref,
        'Origin': 'https://vidmody.com'
    }
    
    try:
        resp = requests.get(remote_m3u8_url, headers=headers, timeout=15)
        if resp.status_code == 200:
            lines = resp.text.splitlines()
            cleaned_lines = []
            
            # M3U8 içindeki tüm URL'leri inceleyip .jpg uzantılarını .m3u8 yapıyoruz
            for line in lines:
                if ".jpg" in line:
                    line = line.replace(".jpg", ".m3u8")
                cleaned_lines.append(line)
            
            local_filename = "local_playlist.m3u8"
            with open(local_filename, "w", encoding="utf-8") as f:
                f.write("\n".join(cleaned_lines))
            
            print(f"✅ M3U8 içeriğindeki .jpg segmentleri .m3u8 olarak düzeltildi -> {local_filename}")
            return local_filename
    except Exception as e:
        print(f"⚠️ M3U8 içerik temizleme hatası: {e}")
        
    return remote_m3u8_url


def get_m3u_playlist(m3u_url):
    try:
        headers = {'User-Agent': STREAM_USER_AGENT, 'Referer': STREAM_REFERER}
        response = requests.get(m3u_url, headers=headers, timeout=15)
        if response.status_code == 200:
            playlist = []
            pending_title = None
            for raw_line in response.text.splitlines():
                line = raw_line.strip()
                if not line:
                    continue
                if line.startswith('#EXTINF'):
                    match = re.search(r',(.+)$', line)
                    pending_title = match.group(1).strip() if match else None
                elif not line.startswith('#') and line.startswith('http'):
                    title = pending_title or os.path.basename(line.split('?')[0])
                    playlist.append({"url": line, "title": title})
                    pending_title = None
            return playlist
    except Exception as e:
        print(f"⚠️ M3U çekme hatası: {e}")
    return [{"url": m3u_url, "title": os.path.basename(m3u_url)}]


def download_logo():
    headers = {'User-Agent': STREAM_USER_AGENT}
    try:
        response = requests.get(LOGO_URL, headers=headers, timeout=15)
        if response.status_code == 200 and len(response.content) > 0:
            with open('logo.png', 'wb') as f:
                f.write(response.content)
    except Exception:
        pass


def write_title_file(title):
    try:
        with open('title.txt', 'w', encoding='utf-8') as f:
            f.write(title)
    except Exception:
        pass


def start_m3u_stream():
    download_logo()
    current_index, last_seconds, last_url = get_local_state()

    while True:
        playlist = get_m3u_playlist(M3U_URL)
        if not playlist:
            time.sleep(10)
            continue

        if current_index >= len(playlist):
            current_index = 0
            last_seconds = 0

        current_item = playlist[current_index]
        raw_stream_url = current_item["url"]
        film_title = current_item["title"]

        remote_m3u8_url, active_ua, active_ref = extract_real_m3u8(raw_stream_url)
        
        # M3U8 dosyasının içindeki parçaları temizleme adamı
        final_input_target = create_clean_local_m3u8(remote_m3u8_url, active_ua, active_ref)

        write_title_file(film_title)

        headers_arg = (
            f"User-Agent: {active_ua}\r\n"
            f"Referer: {active_ref}\r\n"
            "Origin: https://vidmody.com\r\n"
        )

        input_options = [
            '-headers', headers_arg,
            '-protocol_whitelist', 'file,http,https,tcp,tls,crypto',
            '-allowed_extensions', 'ALL',
            '-reconnect', '1',
            '-reconnect_at_eof', '1',
            '-reconnect_streamed', '1',
            '-reconnect_delay_max', '2',
            '-rw_timeout', '10000000'
        ]

        input_args = ['-ss', str(last_seconds)] + input_options + ['-i', final_input_target]

        has_logo1 = os.path.exists('logo.png') and os.path.getsize('logo.png') > 0
        title_drawtext = (
            f"drawtext=textfile='title.txt':reload=1:fontfile='{BOLD_FONT_PATH}':"
            f"fontcolor=white@{TEXT_OPACITY}:fontsize=30:"
            f"x=80:y=main_h-th-67"
        )

        if has_logo1:
            logo_inputs = ['-i', 'logo.png']
            filter_str = (
                '[0:v]scale=1920:1080:force_original_aspect_ratio=decrease,'
                'pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black,fps=25[main];'
                '[1:v]scale=-2:91,format=rgba,'
                f'colorchannelmixer=aa={LOGO_OPACITY}[logo1];'
                '[main][logo1]overlay=main_w-overlay_w-104:80[tmp];'
                f'[tmp]{title_drawtext}[v]'
            )
        else:
            logo_inputs = []
            filter_str = (
                '[0:v]scale=1920:1080:force_original_aspect_ratio=decrease,'
                'pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black,fps=25[main];'
                f'[main]{title_drawtext}[v]'
            )

        command = [
            'ffmpeg'
        ] + input_args + logo_inputs + [
            '-filter_complex', filter_str,
            '-map', '[v]',
            '-map', '0:a:0?',
            '-c:v', 'libx264',
            '-preset', 'veryfast',
            '-pix_fmt', 'yuv420p',
            '-r', '25',
            '-b:v', '2500k',
            '-maxrate', '2500k',
            '-bufsize', '3000k',
            '-g', '50',
            '-c:a', 'aac',
            '-b:a', '128k',
            '-ac', '2',
            '-ar', '44100',
            '-f', 'flv',
            RTMP_SERVER
        ]

        print(f"▶ FFmpeg başlatılıyor: {film_title}")
        process = subprocess.Popen(command, stderr=subprocess.PIPE, universal_newlines=True)

        stderr_tail = deque(maxlen=20)
        while True:
            line = process.stderr.readline()
            if not line and process.poll() is not None:
                break
            if line:
                stderr_tail.append(line.rstrip())

        if process.returncode == 0:
            current_index += 1
            last_seconds = 0
            update_local_state(current_index, 0, "")
        else:
            print(f"⚠️ Hata oluştu, tekrar deneniyor...")
            time.sleep(5)


if __name__ == "__main__":
    start_m3u_stream()
