import subprocess
import requests

def fix_stream_url(url: str) -> str:
    """
    Gelen bağlantıdaki .jpg uzantılarını veya sahte resim uzantılarını
    otomatik olarak .m3u8 yapar.
    """
    if not url:
        return url
    
    # .jpg uzantısını .m3u8 yap
    if ".jpg" in url:
        url = url.replace(".jpg", ".m3u8")
        
    return url

def run_ffmpeg_stream(m3u8_url: str, rtmp_target: str, start_sec: int = 0):
    """
    .m3u8 yapılan adresi FFmpeg ile 403 engeline takılmadan RTMP'ye basar.
    """
    # 1. Bağlantı içindeki .jpg olan yeri .m3u8 yap
    clean_m3u8_url = fix_stream_url(m3u8_url)
    
    print(f"🎯 Düzenlenen Akış Adresi: {clean_m3u8_url}")

    # 2. FFmpeg Komut Yapılandırması
    # Vidmody 403 vermesin diye -headers parametresi eklenmiştir
    ffmpeg_cmd = [
        'ffmpeg',
        '-y',
        '-headers', 'Referer: https://vidmody.com/\r\nUser-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64)\r\n',
        '-ss', str(start_sec),
        '-i', clean_m3u8_url,
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
        rtmp_target
    ]

    print("▶ FFmpeg başlatıldı, yayın iletiliyor...")
    
    # Process çalıştırma
    process = subprocess.Popen(
        ffmpeg_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True
    )
    
    return process


# --- KULLANIM ÖRNEĞİ ---
if __name__ == "__main__":
    # yt-dlp veya playlist'ten gelen sorunlu URL
    raw_url = "https://vidmody.com/mm/tt17490712/ccmain1080/index-v1-a1.jpg"
    rtmp_dest = "rtmp://ssh101.bozztv.com:1935/ssh101/maxtv"
    
    # Fonksiyon otomatik .jpg -> .m3u8 çevirisi yapacaktır
    run_ffmpeg_stream(m3u8_url=raw_url, rtmp_target=rtmp_dest, start_sec=0)
