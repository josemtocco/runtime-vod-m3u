from __future__ import annotations
import argparse, asyncio, json, logging, os, re, sys, time
from pathlib import Path
from urllib.parse import urlparse

from runtime_scraper import scrape, Item

ROOT = Path(__file__).resolve().parent
STATE = ROOT / "catalogo.json"
OUT = ROOT / "runtime_vod.m3u"


def load_state():
    if not STATE.exists(): return {}
    try:
        data = json.loads(STATE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def esc(s):
    return (s or "").replace('"', "'").replace("\n", " ").strip()


def group(item):
    if item.genres:
        return "Runtime | " + " / ".join(item.genres[:2])
    return "Runtime | VOD"


def merge(items, old):
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    current = {}
    for x in items:
        d = x.__dict__.copy()
        d["last_seen"] = now
        d["active"] = bool(d.get("stream_url"))
        current[x.key] = d

    # Preserve metadata for known entries only when the current scan failed to rediscover them.
    # They are NOT written to M3U as active; this avoids stale playback URLs.
    merged = dict(old)
    for k, d in current.items():
        merged[k] = d
    for k, d in merged.items():
        if k not in current:
            d["active"] = False
    return merged


def write_m3u(catalog):
    active = [d for d in catalog.values() if d.get("active") and d.get("stream_url")]
    active.sort(key=lambda d: (group_obj(d).lower(), d.get("title", "").lower()))
    lines = ["#EXTM3U"]
    for d in active:
        title = esc(d.get("title"))
        logo = esc(d.get("logo"))
        g = esc(group_obj(d))
        attrs = [f'tvg-name="{title}"', f'group-title="{g}"']
        if logo: attrs.append(f'tvg-logo="{logo}"')
        lines.append(f'#EXTINF:-1 {" ".join(attrs)},{title}')
        lines.append(d["stream_url"])
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(active)


def group_obj(d):
    genres = d.get("genres") or []
    return "Runtime | " + " / ".join(genres[:2]) if genres else "Runtime | VOD"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-pages", type=int, default=150)
    ap.add_argument("--max-items", type=int, default=500)
    ap.add_argument("--concurrency", type=int, default=3)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

    old = load_state()
    logging.info("Catálogo anterior: %d itens", len(old))
    items = asyncio.run(scrape(max_pages=args.max_pages, max_items=args.max_items, concurrency=args.concurrency))
    logging.info("Itens processados: %d | com stream: %d", len(items), sum(bool(x.stream_url) for x in items))
    if not items and old:
        logging.error("Nenhum conteúdo descoberto. Preservando M3U anterior.")
        return 2
    catalog = merge(items, old)
    STATE.write_text(json.dumps(catalog, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    n = write_m3u(catalog)
    logging.info("M3U gerada: %d itens ativos", n)
    if n == 0 and not old:
        logging.warning("Nenhum stream público foi capturado; catálogo salvo para diagnóstico.")

if __name__ == "__main__":
    main()
