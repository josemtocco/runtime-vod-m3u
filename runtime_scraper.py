from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import asdict, dataclass
from typing import Iterable
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

BASE = "https://www.runtime.tv"
START_URL = "https://www.runtime.tv/pt-br"
FEATURE_RE = re.compile(r"^/pt-br/feature/[^?#]+/?$")
COLLECTION_RE = re.compile(r"^/collections/[^?#]+/?$")
STREAM_RE = re.compile(r"\.(?:m3u8|mpd)(?:$|[?#])", re.I)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131 Safari/537.36",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
}

@dataclass
class Item:
    key: str
    title: str
    url: str
    genres: list[str]
    description: str
    logo: str
    stream_url: str = ""
    stream_type: str = ""
    last_seen: str = ""
    active: bool = False


def clean(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def canonical(url: str) -> str:
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}{p.path.rstrip('/') or '/'}"


def same_host(url: str) -> bool:
    return urlparse(url).netloc.lower().endswith("runtime.tv")


def extract_links(html: str, base: str) -> set[str]:
    soup = BeautifulSoup(html, "lxml")
    out = set()
    for a in soup.find_all("a", href=True):
        u = canonical(urljoin(base, a["href"]))
        path = urlparse(u).path
        if same_host(u) and (FEATURE_RE.match(path) or COLLECTION_RE.match(path)):
            out.add(u)
    return out


def parse_item(html: str, url: str) -> Item | None:
    soup = BeautifulSoup(html, "lxml")
    path = urlparse(url).path
    if not FEATURE_RE.match(path):
        return None

    title = ""
    h1 = soup.find("h1")
    if h1:
        title = clean(h1.get_text(" ", strip=True))
    if not title:
        og = soup.find("meta", attrs={"property": "og:title"})
        title = clean(og.get("content", "")) if og else ""
    if not title:
        title = clean(soup.title.get_text(" ", strip=True)) if soup.title else ""
    title = re.sub(r"\s*\|\s*Runtime\s*$", "", title, flags=re.I)
    if not title:
        return None

    desc = ""
    md = soup.find("meta", attrs={"name": "description"})
    if md:
        desc = clean(md.get("content", ""))
    if not desc:
        ogd = soup.find("meta", attrs={"property": "og:description"})
        desc = clean(ogd.get("content", "")) if ogd else ""

    logo = ""
    ogi = soup.find("meta", attrs={"property": "og:image"})
    if ogi:
        logo = urljoin(url, ogi.get("content", ""))

    genres: list[str] = []
    text = soup.get_text(" ", strip=True)
    m = re.search(r"Genres\s+(.*?)(?:Director\(s\)|Director|Actor\(s\)|Actor|$)", text, re.I)
    if m:
        raw = clean(m.group(1))
        genres = [clean(x) for x in re.split(r"\s{2,}|\s*[,|•]\s*", raw) if clean(x)]
    if not genres:
        genres = [clean(x.get_text(" ", strip=True)) for x in soup.select("a[href*='/collections/']")]
    genres = list(dict.fromkeys(x for x in genres if 1 < len(x) < 50))[:6]

    return Item(
        key=canonical(url), title=title, url=canonical(url), genres=genres,
        description=desc, logo=logo,
    )


def json_ld_urls(html: str, page_url: str) -> set[str]:
    out = set()
    soup = BeautifulSoup(html, "lxml")
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or script.get_text())
        except Exception:
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            x = stack.pop()
            if isinstance(x, dict):
                for k, v in x.items():
                    if isinstance(v, str) and (STREAM_RE.search(v) or "video" in k.lower() or "contenturl" in k.lower()):
                        if STREAM_RE.search(v): out.add(urljoin(page_url, v))
                    elif isinstance(v, (dict, list)): stack.append(v)
            elif isinstance(x, list): stack.extend(x)
    return out


async def capture_stream(page, url: str, timeout_ms: int = 25000) -> tuple[str, str, str]:
    found: list[str] = []
    drm = {"encrypted-media", "widevine", "playready", "fairplay", "clearkey"}

    def on_response(resp):
        u = resp.url
        if STREAM_RE.search(u):
            found.append(u)

    page.on("response", on_response)
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        await page.wait_for_timeout(2500)
        # Trigger lazy players/buttons when possible without assuming a specific player.
        for selector in ["button", "[role=button]", "video"]:
            try:
                loc = page.locator(selector)
                n = min(await loc.count(), 10)
                for i in range(n):
                    try:
                        await loc.nth(i).click(timeout=800, force=True)
                        await page.wait_for_timeout(700)
                    except Exception:
                        pass
            except Exception:
                pass
        await page.wait_for_timeout(2500)
        content = await page.content()
        found.extend(json_ld_urls(content, url))
        text = content.lower()
        if any(x in text for x in drm):
            logging.debug("Possível DRM em %s", url)
    except PlaywrightTimeoutError:
        logging.warning("Timeout: %s", url)
    except Exception as e:
        logging.debug("Falha navegador %s: %s", url, e)
    finally:
        try: page.remove_listener("response", on_response)
        except Exception: pass

    # Prefer HLS; discard obvious ad/telemetry URLs.
    candidates = []
    for u in found:
        if not u.startswith(("http://", "https://")): continue
        if any(x in u.lower() for x in ["doubleclick", "googleads", "analytics"]): continue
        candidates.append(u)
    candidates = list(dict.fromkeys(candidates))
    hls = [u for u in candidates if re.search(r"\.m3u8(?:$|[?#])", u, re.I)]
    dash = [u for u in candidates if re.search(r"\.mpd(?:$|[?#])", u, re.I)]
    chosen = (hls or dash or [""])[0]
    typ = "hls" if chosen in hls else ("dash" if chosen else "")
    return chosen, typ, content if 'content' in locals() else ""


async def scrape(start=START_URL, max_pages=150, max_items=500, concurrency=3):
    session = requests.Session(); session.headers.update(HEADERS)
    queue = [canonical(start)]
    seen_pages = set()
    item_urls: set[str] = set()

    while queue and len(seen_pages) < max_pages:
        batch = []
        while queue and len(batch) < 10:
            u = queue.pop(0)
            if u not in seen_pages: batch.append(u)
        for u in batch:
            seen_pages.add(u)
            try:
                r = session.get(u, timeout=20)
                if r.ok:
                    links = extract_links(r.text, u)
                    item_urls.update(x for x in links if FEATURE_RE.match(urlparse(x).path))
                    for x in links:
                        if COLLECTION_RE.match(urlparse(x).path) and x not in seen_pages and x not in queue:
                            queue.append(x)
            except Exception as e:
                logging.debug("HTTP %s: %s", u, e)
        if len(item_urls) >= max_items: break

    items: list[Item] = []
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=["--disable-dev-shm-usage", "--no-sandbox"])
        sem = asyncio.Semaphore(concurrency)

        async def one(u):
            async with sem:
                ctx = await browser.new_context(locale="pt-BR", user_agent=HEADERS["User-Agent"])
                page = await ctx.new_page()
                try:
                    r = await page.request.get(u, timeout=20000)
                    html = await r.text()
                    item = parse_item(html, u)
                    if not item: return None
                    stream, typ, _ = await capture_stream(page, u)
                    item.stream_url, item.stream_type = stream, typ
                    item.last_seen = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                    item.active = bool(stream)
                    return item
                except Exception as e:
                    logging.debug("Item %s: %s", u, e)
                    return None
                finally:
                    await ctx.close()

        urls = list(item_urls)[:max_items]
        results = await asyncio.gather(*(one(u) for u in urls))
        await browser.close()
        items = [x for x in results if x]
    return items
