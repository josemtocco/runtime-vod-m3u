from __future__ import annotations
import argparse, asyncio, json, logging, os, time
from pathlib import Path
import requests
from runtime_scraper import scrape

ROOT = Path(__file__).resolve().parent
STATE = ROOT / 'catalogo.json'
OUT = ROOT / 'runtime_vod.m3u'
SHORTEN = os.getenv('SHORTEN_URLS', 'true').lower() not in {'0','false','no'}
TINY_TIMEOUT = int(os.getenv('TINYURL_TIMEOUT', '15'))
MIN_ACTIVE_RATIO = float(os.getenv('MIN_ACTIVE_RATIO', '0.20'))


def load():
    try:
        d = json.loads(STATE.read_text(encoding='utf8'))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def esc(s):
    return (s or '').replace('"', "'").replace('\n', ' ').strip()


def shorten(url, session, existing=''):
    # Reuse a previously shortened URL when the underlying stream did not change.
    if existing and existing.startswith('https://tinyurl.com/'):
        return existing
    if not SHORTEN or not url:
        return url
    try:
        r = session.get(
            'https://tinyurl.com/api-create.php',
            params={'url': url}, timeout=TINY_TIMEOUT,
            headers={'User-Agent': 'runtime-vod-m3u/6.0'}
        )
        u = r.text.strip()
        if u.startswith('https://tinyurl.com/') and len(u) < 100:
            return u
    except Exception as e:
        logging.warning('TinyURL falhou: %s', e)
    return url


def merge(items, old):
    now = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    cur = {}
    for x in items:
        d = x.__dict__.copy()
        d['last_seen'] = now
        d['active'] = bool(d.get('stream_url'))
        old_d = old.get(x.key, {}) if isinstance(old, dict) else {}
        if d.get('stream_url') == old_d.get('stream_url') and old_d.get('playlist_url'):
            d['playlist_url'] = old_d['playlist_url']
        cur[x.key] = d
    merged = dict(old)
    for k, d in cur.items():
        merged[k] = d
    for k in list(merged):
        if k not in cur:
            merged[k]['active'] = False
    return merged


def write_m3u(cat, session):
    active = [d for d in cat.values() if d.get('active') and d.get('stream_url')]
    active.sort(key=lambda d: ((d.get('genres') or ['VOD'])[0].lower(), d.get('title','').lower()))
    lines = ['#EXTM3U']
    for d in active:
        title = esc(d.get('title'))
        genres = d.get('genres') or ['VOD']
        group = 'Runtime | ' + genres[0]
        attrs = f'tvg-name="{title}" group-title="{esc(group)}"'
        if d.get('logo'):
            attrs += f' tvg-logo="{esc(d["logo"])}"'
        short = shorten(d['stream_url'], session, d.get('playlist_url', ''))
        d['playlist_url'] = short
        lines += [f'#EXTINF:-1 {attrs},{title}', short]
    OUT.write_text('\n'.join(lines) + '\n', encoding='utf8')
    return len(active)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--max-categories', type=int, default=120)
    ap.add_argument('--max-items', type=int, default=1200)
    ap.add_argument('--concurrency', type=int, default=6)
    ap.add_argument('--verbose', action='store_true')
    ap.add_argument('--force-write', action='store_true', help='permite substituir uma M3U válida por uma muito menor')
    a = ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')

    old = load()
    old_active = sum(bool(d.get('active') and d.get('stream_url')) for d in old.values())
    logging.info('Catálogo anterior: %d itens | %d ativos', len(old), old_active)

    items, cats = asyncio.run(scrape(a.max_categories, a.max_items, a.concurrency))
    found_active = sum(bool(x.stream_url) for x in items)
    logging.info('Categorias: %d | Itens processados: %d | com stream: %d', len(cats), len(items), found_active)

    # Critical safety: never turn a good playlist into an empty playlist because
    # Runtime changed a response, timed out, or the player stopped exposing URLs.
    if not items or found_active == 0:
        logging.error('Nenhum stream válido encontrado; M3U anterior PRESERVADA.')
        return 2
    if old_active and not a.force_write and found_active < max(3, int(old_active * MIN_ACTIVE_RATIO)):
        logging.error('Queda anormal: %d ativos encontrados contra %d anteriores. M3U anterior PRESERVADA.', found_active, old_active)
        return 3

    cat = merge(items, old)
    sess = requests.Session()
    n = write_m3u(cat, sess)
    STATE.write_text(json.dumps(cat, ensure_ascii=False, indent=2, sort_keys=True), encoding='utf8')
    logging.info('M3U gerada: %d itens ativos', n)
    if n == 0:
        logging.error('Proteção final: catálogo resultou em 0 ativos; M3U anterior deve ser restaurada manualmente.')
        return 4
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
