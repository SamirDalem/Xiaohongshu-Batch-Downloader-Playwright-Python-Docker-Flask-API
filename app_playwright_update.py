# app_playwright_update_fixed.py
from flask import Flask, request, jsonify
import os
import uuid
import re
import requests
import json
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

app = Flask(__name__)

# --- Configuration ---
DEBUG_OUT = Path("./debug")
DOWNLOAD_OUT = Path("./downloads")
SEEKIN_URL = "https://www.seekin.ai/xiaohongshu-video-downloader/"
USER_AGENT_MOBILE = "Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Mobile/15E148 Safari/604.1"
USER_AGENT_DESKTOP = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115 Safari/537.36"
TIMEOUT_SEC = 40

DEBUG_OUT.mkdir(parents=True, exist_ok=True)
DOWNLOAD_OUT.mkdir(parents=True, exist_ok=True)

VIDEO_EXT_RE = re.compile(r"\.(mp4|webm|m3u8|ts)(?:\?|$)", flags=re.I)
SANITIZE_FILENAME_RE = re.compile(r'[^A-Za-z0-9 \-_\.\(\)\[\]]+')
JS_TITLE_RE = re.compile(r"""title\s*:\s*(['"])(.*?)\1""", flags=re.IGNORECASE | re.DOTALL)


# --- Helpers ---
def sanitize_filename(s: str, fallback: str = "video"):
    if not s:
        return fallback
    s = s.strip()
    s = SANITIZE_FILENAME_RE.sub("_", s)
    s = re.sub(r"_+", "_", s)
    return s[:180].rstrip("_")


def unique_path_for(path: Path) -> Path:
    base, ext, parent = path.stem, path.suffix, path.parent
    candidate, i = path, 1
    while candidate.exists():
        candidate = parent / f"{base}-{i}{ext}"
        i += 1
    return candidate


def extract_title_from_text(text: str):
    if not text:
        return None
    m = JS_TITLE_RE.search(text)
    if m:
        return m.group(2).strip()
    return None


def try_head_size(url: str, timeout: int = 6):
    headers = {"User-Agent": USER_AGENT_DESKTOP, "Referer": "https://www.xiaohongshu.com/"}
    try:
        r = requests.head(url, headers=headers, timeout=timeout, allow_redirects=True)
        cl = r.headers.get("Content-Length")
        if cl and cl.isdigit():
            return int(cl)
    except Exception:
        pass
    try:
        headers_range = headers.copy()
        headers_range["Range"] = "bytes=0-0"
        r = requests.get(url, headers=headers_range, timeout=timeout, stream=True, allow_redirects=True)
        cr = r.headers.get("Content-Range")
        if cr and "/" in cr:
            total = cr.split("/")[-1]
            if total.isdigit():
                return int(total)
        cl2 = r.headers.get("Content-Length")
        if cl2 and cl2.isdigit() and int(cl2) > 1:
            return int(cl2)
    except Exception:
        pass
    return None


def download_stream(url: str, out_path: Path):
    headers = {"User-Agent": USER_AGENT_DESKTOP, "Referer": "https://www.xiaohongshu.com/"}
    try:
        with requests.get(url, headers=headers, stream=True, timeout=0, allow_redirects=True) as r:
            r.raise_for_status()
            with out_path.open("wb") as fh:
                for chunk in r.iter_content(chunk_size=1 << 14):
                    if chunk:
                        fh.write(chunk)
        return True, None
    except Exception as e:
        return False, str(e)


# --- Seekin extraction logic ---
def extract_from_seekin(playwright, post_url: str, timeout: int = TIMEOUT_SEC):
    out = {"success": False, "title": None, "candidates": [], "debug_html": None, "debug_png": None, "error": None}
    try:
        browser = playwright.chromium.launch(headless=True, args=['--no-sandbox', '--disable-setuid-sandbox'])
        for ua in (USER_AGENT_MOBILE, USER_AGENT_DESKTOP):
            context = browser.new_context(user_agent=ua, viewport={'width': 390, 'height': 844} if ua == USER_AGENT_MOBILE else {'width': 1280, 'height': 800})
            page = context.new_page()
            page.set_default_timeout(timeout * 1000)

            def on_response(resp):
                try:
                    u = resp.url
                    if u and VIDEO_EXT_RE.search(u) and u not in out["candidates"]:
                        out["candidates"].append(u)

                    ct = resp.headers.get("content-type", "") or ""
                    if "application/json" in ct.lower():
                        try:
                            j = json.loads(resp.text())
                            data = j.get("data") or j.get("result") or j.get("payload")
                            if isinstance(data, dict):
                                title = data.get("title") or data.get("name") or data.get("desc")
                                if title and not out["title"]:
                                    out["title"] = title
                                medias = data.get("medias") or data.get("media") or data.get("urls")
                                if isinstance(medias, list):
                                    for m in medias:
                                        candidate_url = None
                                        if isinstance(m, dict):
                                            candidate_url = m.get("url") or m.get("uri") or m.get("src") or m.get("playUrl")
                                            if not candidate_url:
                                                for v in m.values():
                                                    if isinstance(v, str) and VIDEO_EXT_RE.search(v):
                                                        candidate_url = v
                                                        break
                                        elif isinstance(m, str):
                                            if VIDEO_EXT_RE.search(m):
                                                candidate_url = m
                                        if candidate_url and candidate_url not in out["candidates"]:
                                            out["candidates"].append(candidate_url)
                        except Exception:
                            tf = extract_title_from_text(resp.text())
                            if tf and not out["title"]:
                                out["title"] = tf
                    else:
                        tf = extract_title_from_text(resp.text())
                        if tf and not out["title"]:
                            out["title"] = tf
                except Exception:
                    pass

            page.on("response", on_response)

            try:
                page.goto(SEEKIN_URL, wait_until="networkidle")
            except PWTimeout:
                page.goto(SEEKIN_URL)

            try:
                inp = page.query_selector('input[type="text"], input[placeholder], textarea')
                if inp:
                    inp.fill(post_url)
                    btn = page.query_selector('button[type="submit"], button:has-text("解析"), button:has-text("Download"), button[class*="btn"]')
                    if btn:
                        try:
                            btn.click()
                        except Exception:
                            page.keyboard.press("Enter")
                    else:
                        page.keyboard.press("Enter")
                else:
                    page.goto(SEEKIN_URL + "?q=" + post_url)
            except Exception:
                pass

            waited, poll = 0.0, 0.5
            while waited < timeout:
                if out["candidates"] or out["title"]:
                    break
                page.wait_for_timeout(int(poll * 1000))
                waited += poll

            try:
                uid = uuid.uuid4().hex
                html_path = DEBUG_OUT / f"{uid}.html"
                png_path = DEBUG_OUT / f"{uid}.png"
                html_path.write_text(page.content(), encoding="utf-8")
                page.screenshot(path=str(png_path), full_page=True)
                out["debug_html"] = str(html_path.resolve())
                out["debug_png"] = str(png_path.resolve())
            except Exception:
                pass

            if out["candidates"] or out["title"]:
                out["success"] = True
                context.close()
                break

            context.close()
        browser.close()
    except Exception as e:
        out["error"] = str(e)
    return out


# --- Flask endpoint ---
@app.route("/extract", methods=["POST"])
def extract():
    payload = request.get_json(force=True, silent=True)
    if not payload or "url" not in payload:
        return jsonify({"success": False, "error": "missing url"}), 400

    url = payload["url"]
    index = payload.get("index", int(uuid.uuid4().int % 1000000))

    try:
        with sync_playwright() as p:
            res = extract_from_seekin(p, url, timeout=TIMEOUT_SEC)
    except Exception as e:
        return jsonify({"success": False, "error": "playwright_failed", "detail": str(e)}), 500

    resp = {
        "success": False,
        "postUrl": url,
        "index": index,
        "caption": res.get("title"),
        "candidates": res.get("candidates", []),
        "video_url": None,
        "saved_to": None,
        "error": res.get("error"),
        "debug_html": res.get("debug_html"),
        "debug_png": res.get("debug_png"),
    }

    candidates = res.get("candidates") or []
    if not candidates:
        return jsonify(resp), 200

    seen, normalized = set(), []
    for c in candidates:
        if c and c not in seen:
            normalized.append(c)
            seen.add(c)

    sizes = {}
    for u in normalized:
        if u.lower().endswith(".m3u8"):
            sizes[u] = None
        else:
            sizes[u] = try_head_size(u, timeout=6)

    cand_info = [{"url": u, "size_bytes": sizes.get(u)} for u in normalized]
    resp["candidates"] = cand_info

    sized_downloadables = [c for c in cand_info if c["size_bytes"] and re.search(r"\.(mp4|webm)$", c["url"], flags=re.I)]
    chosen = min(sized_downloadables, key=lambda x: x["size_bytes"]) if sized_downloadables else (cand_info[0] if cand_info else None)
    if not chosen:
        resp["error"] = "no_candidate_chosen"
        return jsonify(resp), 200

    chosen_url = chosen["url"]
    resp["video_url"] = chosen_url

    base_name = sanitize_filename(resp["caption"] or f"xhs_{index}")
    ext = Path(chosen_url.split("?")[0]).suffix or ".mp4"
    out_path = unique_path_for(DOWNLOAD_OUT / f"{index} - {base_name}{ext}")

    ok, err = download_stream(chosen_url, out_path)
    if not ok:
        resp["error"] = f"download_failed: {err}"
        return jsonify(resp), 200

    resp["saved_to"] = str(out_path.resolve())
    resp["success"] = True
    return jsonify(resp), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=6000)
