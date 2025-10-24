# app.py
import os, re, uuid, shutil, tempfile, threading
from pathlib import Path
from flask import Flask, render_template, request, jsonify, send_file, abort
from pytube import YouTube
from pydub import AudioSegment
from bs4 import BeautifulSoup
import requests

app = Flask(__name__)

TMP_DIR = Path(tempfile.gettempdir()) / "yt_dl"
TMP_DIR.mkdir(parents=True, exist_ok=True)

def has_ffmpeg():
    return shutil.which("ffmpeg") is not None

def cleanup_later(path, delay=60):
    def _del():
        try:
            if path.exists():
                path.unlink()
        except Exception:
            pass
    t = threading.Timer(delay, _del)
    t.daemon = True
    t.start()

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/search", methods=["POST"])
def search_videos():
    """Search YouTube without API by scraping HTML results."""
    data = request.get_json() or {}
    query = data.get("query", "").strip()
    if not query:
        return jsonify({"error": "Empty search"}), 400

    # fetch YouTube search results page
    url = f"https://www.youtube.com/results?search_query={requests.utils.quote(query)}"
    html = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}).text

    # extract initial data with regex
    video_ids = re.findall(r"\"videoId\":\"([a-zA-Z0-9_-]{11})\"", html)
    titles = re.findall(r"\"title\":{\"runs\":\[{\"text\":\"(.*?)\"\}\]", html)
    thumbs = re.findall(r"\"thumbnail\":{\"thumbnails\":\[{\"url\":\"(.*?)\"\}", html)

    # assemble up to 8 results
    results = []
    for i, vid in enumerate(video_ids[:8]):
        title = titles[i] if i < len(titles) else "Unknown Title"
        thumb = thumbs[i] if i < len(thumbs) else ""
        results.append({
            "id": vid,
            "title": title,
            "thumbnail": thumb,
            "url": f"https://www.youtube.com/watch?v={vid}"
        })

    return jsonify(results)

@app.route("/download", methods=["POST"])
def download_video():
    data = request.get_json() or {}
    url = data.get("url")
    fmt = data.get("format", "mp4")
    if not url:
        return jsonify({"error": "No URL"}), 400

    try:
        yt = YouTube(url)
    except Exception as e:
        return jsonify({"error": str(e)}), 400

    safe = "".join(c for c in yt.title if c.isalnum() or c in " _-").strip()[:120]
    uid = uuid.uuid4().hex
    base = f"{safe}-{uid}"

    if fmt == "mp4":
        stream = yt.streams.filter(progressive=True, file_extension="mp4").order_by("resolution").desc().first()
        out = TMP_DIR / f"{base}.mp4"
        stream.download(output_path=str(TMP_DIR), filename=out.name)
        cleanup_later(out)
        return jsonify({"ok": True, "file": f"/file/{out.name}", "name": f"{safe}.mp4"})
    else:
        stream = yt.streams.filter(only_audio=True).order_by("abr").desc().first()
        orig = TMP_DIR / f"{base}.{stream.subtype}"
        stream.download(output_path=str(TMP_DIR), filename=orig.name)
        if has_ffmpeg():
            target = TMP_DIR / f"{base}.mp3"
            audio = AudioSegment.from_file(orig)
            audio.export(target, format="mp3", bitrate="192k")
            cleanup_later(orig)
            cleanup_later(target)
            return jsonify({"ok": True, "file": f"/file/{target.name}", "name": f"{safe}.mp3"})
        else:
            cleanup_later(orig)
            return jsonify({"ok": True, "file": f"/file/{orig.name}", "name": f"{safe}.{stream.subtype}"})

@app.route("/file/<name>")
def serve_file(name):
    path = TMP_DIR / Path(name).name
    if not path.exists():
        abort(404)
    return send_file(str(path), as_attachment=True, download_name=name)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
