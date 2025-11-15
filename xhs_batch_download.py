#!/usr/bin/env python3
"""
xhs_batch_download.py
Usage:
  python xhs_batch_download.py links.json
Or:
  python xhs_batch_download.py --inline "['https://...','https://...']"
"""

import asyncio
import json
import re
import sys
import uuid
import html
from pathlib import Path
from typing import List, Dict, Optional, Tuple

import aiohttp
from aiohttp import ClientTimeout
from tqdm.asyncio import tqdm_asyncio
from playwright.async_api import async_playwright, Page, Response

# --- Configuration ---
CONCURRENCY = 4
DOWNLOAD_CONCURRENCY = 4
SEEKIN_URL = "https://www.seekin.ai/xiaohongshu-video-downloader/"
TIMEOUT_SEC = 90
DOWNLOAD_FOLDER = Path("./downloads")
DEBUG_FOLDER = Path("./debug")
RESULTS_FILE = Path("./results.json")
USER_AGENTS = {
    "mobile": "Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Mobile/15E148 Safari/604.1",
    "desktop": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115 Safari/537.36",
}

DOWNLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
DEBUG_FOLDER.mkdir(parents=True, exist_ok=True)

VIDEO_EXT_RE = re.compile(r"\.(mp4|webm|m3u8|ts)(?:\?|$)", flags=re.I)
SANITIZE_FILENAME_RE = re.compile(r'[^A-Za-z0-9 _\-\.\(\)\[\]]+')
JS_TITLE_RE = re.compile(r"""title\s*:\s*(['"])(.*?)\1""", flags=re.IGNORECASE | re.DOTALL)


# --- Helpers ---
async def head_size(session: aiohttp.ClientSession, url: str, timeout: int = 8) -> Optional[int]:
    headers = {"User-Agent": USER_AGENTS["desktop"], "Referer": "https://www.xiaohongshu.com/"}
    try:
        async with session.head(url, headers=headers, timeout=ClientTimeout(total=timeout), allow_redirects=True) as resp:
            cl = resp.headers.get("Content-Length")
            if cl and cl.isdigit(): return int(cl)
    except: pass
    try:
        hdrs = headers.copy(); hdrs["Range"] = "bytes=0-0"
        async with session.get(url, headers=hdrs, timeout=ClientTimeout(total=timeout), allow_redirects=True) as resp:
            cr = resp.headers.get("Content-Range")
            if cr and "/" in cr:
                total = cr.split("/")[-1]
                if total.isdigit(): return int(total)
            cl2 = resp.headers.get("Content-Length")
            if cl2 and cl2.isdigit() and int(cl2) > 1: return int(cl2)
    except: pass
    return None


async def download_file(session: aiohttp.ClientSession, url: str, out_path: Path) -> Tuple[bool, Optional[str]]:
    try:
        timeout = ClientTimeout(total=0)
        headers = {"User-Agent": USER_AGENTS["desktop"], "Referer": "https://www.xiaohongshu.com/"}
        async with session.get(url, headers=headers, timeout=timeout) as resp:
            resp.raise_for_status()
            with out_path.open("wb") as fh:
                async for chunk in resp.content.iter_chunked(1 << 14):
                    fh.write(chunk)
        return True, None
    except Exception as e:
        return False, str(e)


def sanitize_filename(s: str, fallback: str = "video") -> str:
    if not s: return fallback
    s = html.unescape(s).strip()
    s = SANITIZE_FILENAME_RE.sub("_", s)
    return s[:180].rstrip("_")


def extract_title_from_text(text: str) -> Optional[str]:
    if not text: return None
    m = JS_TITLE_RE.search(text)
    if m: return m.group(2).strip()
    return None


def unique_path_for(path: Path) -> Path:
    base, ext, parent = path.stem, path.suffix, path.parent
    candidate, i = path, 1
    while candidate.exists():
        candidate = parent / f"{base}-{i}{ext}"; i += 1
    return candidate


# --- Seekin extraction ---
async def try_extract_from_seekin(page: Page, post_url: str, collector: List[str], meta_out: Dict):
    async def on_response(resp: Response):
        try:
            ct = (resp.headers.get("content-type") or "").lower()
            text = await resp.text()
            if not text: return
            if "application/json" in ct or resp.url.lower().endswith(".json"):
                try: j = json.loads(text)
                except: 
                    title_fallback = extract_title_from_text(text)
                    if title_fallback and not meta_out.get("title"): meta_out["title"] = title_fallback
                    return
                data = j.get("data") or j.get("result") or j.get("payload")
                if data and isinstance(data, dict):
                    title = data.get("title") or data.get("name") or data.get("desc")
                    if title and not meta_out.get("title"): meta_out["title"] = title
                    medias = data.get("medias") or data.get("media") or data.get("urls")
                    if medias and isinstance(medias, list):
                        for m in medias:
                            candidate_url = None
                            if isinstance(m, dict):
                                candidate_url = m.get("url") or m.get("uri") or m.get("src") or m.get("playUrl")
                                if not candidate_url:
                                    for v in m.values():
                                        if isinstance(v, str) and VIDEO_EXT_RE.search(v):
                                            candidate_url = v; break
                            elif isinstance(m, str) and VIDEO_EXT_RE.search(m):
                                candidate_url = m
                            if candidate_url and candidate_url not in collector: collector.append(candidate_url)
            else:
                if VIDEO_EXT_RE.search(resp.url) and resp.url not in collector:
                    collector.append(resp.url)
        except: pass

    page.on("response", on_response)
    try: await page.goto(SEEKIN_URL, wait_until="networkidle")
    except: await page.goto(SEEKIN_URL)
    try:
        inp = await page.query_selector('input[type="text"], input[placeholder], textarea')
        if inp:
            await inp.fill(post_url)
            btn = await page.query_selector('button[type="submit"], button:has-text("解析"), button:has-text("Download"), button[class*="btn"]')
            if btn:
                try: await btn.click()
                except: await page.keyboard.press("Enter")
            else: await page.keyboard.press("Enter")
        else:
            await page.goto(SEEKIN_URL + "?q=" + post_url)
    except: pass

    waited, poll = 0.0, 0.5
    while waited < TIMEOUT_SEC:
        if collector or meta_out.get("title"): break
        await page.wait_for_timeout(int(poll*1000)); waited += poll

    if not collector:
        try:
            vids = await page.query_selector_all("video")
            for v in vids:
                src = await v.get_attribute("src")
                if src and src not in collector: collector.append(src)
                for s in await v.query_selector_all("source"):
                    s2 = await s.get_attribute("src")
                    if s2 and s2 not in collector: collector.append(s2)
        except: pass
    return collector, meta_out


# --- worker ---
async def worker(playwright, session: aiohttp.ClientSession, url: str, index: int, semaphore: asyncio.Semaphore) -> Dict:
    result = {"postUrl": url, "index": index, "found": False, "video_url": None, "error": None, "candidates": [], "caption": None, "saved_to": None}
    async with semaphore:
        browser = await playwright.chromium.launch(headless=True, args=["--no-sandbox", "--disable-setuid-sandbox"])
        try:
            for ua in (USER_AGENTS["mobile"], USER_AGENTS["desktop"]):
                context = await browser.new_context(user_agent=ua, viewport={"width":390,"height":844} if ua==USER_AGENTS["mobile"] else {"width":1280,"height":800})
                page = await context.new_page()
                try:
                    candidates, meta = [], {}
                    await try_extract_from_seekin(page, url, candidates, meta)

                    uid = uuid.uuid4().hex
                    try:
                        html_file = DEBUG_FOLDER / f"{uid}.html"
                        html_file.write_text(await page.content(), encoding="utf-8")
                        png_file = DEBUG_FOLDER / f"{uid}.png"
                        await page.screenshot(path=str(png_file), full_page=True)
                    except: pass

                    normalized = list(dict.fromkeys(candidates))
                    if meta.get("medias") and isinstance(meta["medias"], list):
                        for m in meta["medias"]:
                            if isinstance(m, str) and m not in normalized and VIDEO_EXT_RE.search(m): normalized.append(m)
                            elif isinstance(m, dict):
                                candidate_url = m.get("url") or m.get("src") or m.get("playUrl")
                                if candidate_url and candidate_url not in normalized: normalized.append(candidate_url)
                    if not normalized: await context.close(); continue

                    sizes = {}
                    async def measure(u):
                        if u.lower().endswith(".m3u8"): sizes[u] = None; return
                        try: sizes[u] = await head_size(session, u, timeout=6)
                        except: sizes[u] = None
                    await asyncio.gather(*(measure(u) for u in normalized))

                    cand_info = [{"url": u, "size_bytes": sizes.get(u)} for u in normalized]
                    result["candidates"] = cand_info

                    sized = [c for c in cand_info if c["size_bytes"] and re.search(r"\.(mp4|webm)$", c["url"], flags=re.I)]
                    chosen = min(sized, key=lambda x:x["size_bytes"]) if sized else (cand_info[0] if cand_info else None)
                    if not chosen: result["error"]="no_candidate_chosen"; await context.close(); break

                    chosen_url = chosen["url"]
                    result["video_url"] = chosen_url; result["found"]=True
                    caption = meta.get("title") or meta.get("name")
                    result["caption"] = caption

                    base_name = sanitize_filename(caption or f"xhs_{index}")
                    ext = Path(chosen_url.split("?")[0]).suffix or ".mp4"
                    out_path = unique_path_for(DOWNLOAD_FOLDER / f"{index} - {base_name}{ext}")

                    ok, err = await download_file(session, chosen_url, out_path)
                    if not ok: result["error"]=f"download_failed: {err}"
                    else: result["saved_to"]=str(out_path.resolve())

                    await context.close(); break
                except Exception as e: result["error"]=str(e); await context.close()
        finally:
            try: await browser.close()
            except: pass
    return result


# --- main ---
async def main(urls: List[str]):
    timeout = aiohttp.ClientTimeout(total=0)
    conn = aiohttp.TCPConnector(limit=DOWNLOAD_CONCURRENCY, ssl=False)
    results = []
    async with aiohttp.ClientSession(timeout=timeout, connector=conn) as session:
        async with async_playwright() as p:
            sem = asyncio.Semaphore(CONCURRENCY)
            tasks = [worker(p, session, url, i+1, sem) for i, url in enumerate(urls)]
            for coro in tqdm_asyncio.as_completed(tasks, total=len(tasks)):
                res = await coro
                results.append(res)
                print(json.dumps(res, ensure_ascii=False))
    try: RESULTS_FILE.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e: print("Failed to write results.json:", e)
    print(f"✅ Wrote results to {RESULTS_FILE.resolve()}")
    return results


# --- CLI ---
def load_urls_from_arg(argv) -> List[str]:
    if len(argv)<2: sys.exit("Usage: python xhs_batch_download.py links.json or --inline [...]")
    arg = argv[1]
    if arg=="--inline": return [str(x) for x in json.loads(argv[2])]
    else:
        j = json.loads(Path(arg).read_text(encoding="utf-8"))
        out = []
        for it in j:
            if isinstance(it,str): out.append(it)
            elif isinstance(it,dict) and "postUrl" in it: out.append(it["postUrl"])
            else: out.append(str(it))
        return out


if __name__=="__main__":
    urls = load_urls_from_arg(sys.argv)
    asyncio.run(main(urls))
