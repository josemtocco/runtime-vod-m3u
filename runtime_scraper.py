from __future__ import annotations
import asyncio, base64, json, logging, re, time
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse, parse_qs, unquote

import requests
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

BASE = 'https://www.runtime.tv'
START = f'{BASE}/pt-br'
UA = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140 Safari/537.36'
HEADERS = {'User-Agent': UA, 'Accept-Language': 'pt-BR,pt;q=0.95,en;q=0.7'}
FEATURE_RE = re.compile(r'^/(?:pt-br/)?feature/[^?#]+/?$', re.I)
COLLECTION_RE = re.compile(r'^/(?:pt-br/)?collections/[^?#]+/?$', re.I)
STREAM_RE = re.compile(r'\.(?:m3u8|mpd)(?:$|[?#])', re.I)

@dataclass
class Item:
    key: str
    title: str
    url: str
    genres: list[str]
    description: str
    logo: str
    stream_url: str = ''
    stream_type: str = ''
    last_seen: str = ''
    active: bool = False
    category_urls: list[str] | None = None


def clean(s):
    return re.sub(r'\s+', ' ', s or '').strip()


def canon(u):
    p = urlparse(u)
    return f'{p.scheme}://{p.netloc}{p.path.rstrip("/") or "/"}'


def localize_runtime_url(u):
    try:
        u = canon(u)
        p = urlparse(u)
        path = p.path
        if path.startswith('/pt-br/'):
            return u
        if path.startswith('/feature/') or path.startswith('/collections/') or path.startswith('/linear/'):
            return f'{p.scheme}://{p.netloc}/pt-br{path}'
        return u
    except Exception:
        return u


def same_host(u):
    return urlparse(u).netloc.lower() in {'runtime.tv', 'www.runtime.tv'}


def is_feature(u):
    return same_host(u) and bool(FEATURE_RE.match(urlparse(u).path))


def is_collection(u):
    return same_host(u) and bool(COLLECTION_RE.match(urlparse(u).path))


def extract_runtime_urls(text, base=BASE):
    out = set()
    if not text:
        return out
    # Absolute URLs and escaped URLs in HTML/JSON/JS.
    patterns = [
        r'https?://(?:www\.)?runtime\.tv[^"\'<>\\\s]+',
        r'(?<![A-Za-z0-9])/(?:pt-br/)?(?:feature|collections)/[^"\'<>\\\s?#]+',
    ]
    for pat in patterns:
        for raw in re.findall(pat, text, re.I):
            raw = raw.replace('\\/', '/').replace('\\u002F', '/')
            try:
                u = localize_runtime_url(urljoin(base, raw))
                if is_feature(u) or is_collection(u):
                    out.add(u)
            except Exception:
                pass
    return out


def all_links(html, base):
    soup = BeautifulSoup(html, 'lxml')
    out = set()
    for a in soup.find_all('a', href=True):
        try:
            u = localize_runtime_url(urljoin(base, a['href']))
            if same_host(u):
                out.add(u)
        except Exception:
            pass
    out |= extract_runtime_urls(html, base)
    return out


def parse_item(html, url, category_urls=None):
    url = localize_runtime_url(url)
    if not is_feature(url):
        return None
    soup = BeautifulSoup(html, 'lxml')
    title = ''
    h = soup.find('h1')
    if h:
        title = clean(h.get_text(' ', strip=True))
    if not title:
        m = soup.find('meta', attrs={'property': 'og:title'})
        title = clean(m.get('content', '')) if m else ''
    if not title and soup.title:
        title = clean(soup.title.get_text(' ', strip=True))
    title = re.sub(r'\s*\|\s*Runtime\s*$', '', title, flags=re.I)
    if not title:
        return None
    desc = ''
    m = soup.find('meta', attrs={'name': 'description'})
    if m:
        desc = clean(m.get('content', ''))
    if not desc:
        m = soup.find('meta', attrs={'property': 'og:description'})
        desc = clean(m.get('content', '')) if m else ''
    logo = ''
    m = soup.find('meta', attrs={'property': 'og:image'})
    if m:
        logo = urljoin(url, m.get('content', ''))
    genres = []
    for a in soup.select('a[href*="/collections/"]'):
        t = clean(a.get_text(' ', strip=True))
        if t and len(t) < 60:
            genres.append(t)
    text = clean(soup.get_text(' ', strip=True))
    mm = re.search(r'(?:Genres|Gêneros)\s+(.*?)(?:Director|Diretor|Actor|Ator|$)', text, re.I)
    if mm:
        genres += [clean(x) for x in re.split(r'[,|•/]+', mm.group(1)) if clean(x)]
    genres = list(dict.fromkeys(x for x in genres if 1 < len(x) < 60))[:6]
    return Item(canon(url), title, canon(url), genres, desc, logo, category_urls=list(category_urls or []))


async def accept_cookies(page):
    for sel in [
        'text=I agree to allow cookies', 'text=Allow cookies',
        'button:has-text("Allow cookies")', 'button:has-text("I agree")'
    ]:
        try:
            loc = page.locator(sel).first
            if await loc.is_visible(timeout=500):
                await loc.click(force=True)
                await page.wait_for_timeout(250)
                break
        except Exception:
            pass


async def page_links(page):
    try:
        vals = await page.locator('a[href]').evaluate_all('els=>els.map(e=>e.href).filter(Boolean)')
        return {localize_runtime_url(x) for x in vals if same_host(x)}
    except Exception:
        return set()


async def extract_html_and_links(page):
    try:
        html = await page.content()
    except Exception:
        html = ''
    links = await page_links(page)
    links |= extract_runtime_urls(html, page.url if page.url else BASE)
    return html, links


async def expand_and_paginate(page, rounds=18, max_pages=40):
    """Collect current page plus real pagination/next links and load-more rows."""
    discovered = set()
    visited_pages = set()
    stable = 0
    for _ in range(rounds):
        html, links = await extract_html_and_links(page)
        discovered |= links
        # Follow common load-more controls before looking for pagination.
        clicked = False
        for sel in [
            'button:has-text("Load more")', 'button:has-text("Carregar mais")',
            'a:has-text("Load more")', 'a:has-text("Carregar mais")',
            '[aria-label*="load more" i]', '[aria-label*="carregar mais" i]'
        ]:
            try:
                loc = page.locator(sel)
                n = min(await loc.count(), 4)
                for i in range(n):
                    try:
                        if await loc.nth(i).is_visible(timeout=300):
                            await loc.nth(i).click(force=True, timeout=900)
                            await page.wait_for_timeout(700)
                            clicked = True
                    except Exception:
                        pass
            except Exception:
                pass
        if clicked:
            continue
        await page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
        await page.wait_for_timeout(650)
        _, links2 = await extract_html_and_links(page)
        before = len(discovered)
        discovered |= links2
        if len(discovered) == before:
            stable += 1
        else:
            stable = 0
        if stable >= 3:
            break

    # Capture pagination links visible in the final DOM. Do not recursively crawl
    # arbitrary site links here; only page/next patterns are followed.
    candidates = []
    for u in discovered:
        pathq = urlparse(u).path.lower() + '?' + (urlparse(u).query or '').lower()
        if any(k in pathq for k in ('page=', 'page/', 'p=', 'offset=', 'start=', 'next')):
            candidates.append(u)
    candidates = sorted(set(candidates))[:max_pages]
    for u in candidates:
        if u in visited_pages:
            continue
        try:
            await page.goto(u, wait_until='domcontentloaded', timeout=30000)
            await accept_cookies(page)
            await page.wait_for_timeout(500)
            html, links = await extract_html_and_links(page)
            discovered |= links
            visited_pages.add(u)
        except Exception:
            pass
    return discovered


async def sitemap_urls(request):
    seen, found = set(), set()
    queue = [
        f'{BASE}/robots.txt', f'{BASE}/sitemap.xml', f'{BASE}/sitemap_index.xml',
        f'{BASE}/pt-br/sitemap.xml', f'{BASE}/pt-br/sitemap_index.xml'
    ]
    while queue and len(seen) < 100:
        u = queue.pop(0)
        if u in seen:
            continue
        seen.add(u)
        try:
            r = await request.get(u, timeout=15000, headers=HEADERS)
            if r.status != 200:
                continue
            txt = await r.text()
            if u.lower().endswith('robots.txt'):
                queue.extend(re.findall(r'(?im)^\s*Sitemap:\s*(\S+)', txt))
                continue
            for raw in re.findall(r'<loc>\s*(.*?)\s*</loc>', txt, re.I | re.S):
                loc = localize_runtime_url(unquote(clean(raw)))
                if loc.lower().endswith('.xml'):
                    queue.append(loc)
                elif is_feature(loc):
                    found.add(loc)
        except Exception as e:
            logging.debug('Sitemap %s: %s', u, e)
    logging.info('Sitemap/robots: %d páginas VOD', len(found))
    return found


async def discover_network(page):
    features, cats, bodies, api_urls = set(), set(), [], set()
    async def on_response(resp):
        u = resp.url
        if not same_host(u):
            return
        ct = (resp.headers.get('content-type') or '').lower()
        low = u.lower()
        if 'json' not in ct and not any(x in low for x in ('/api/', 'graphql', 'catalog', 'search', 'collection', 'browse')):
            return
        try:
            txt = await resp.text()
            if len(txt) <= 5_000_000:
                bodies.append(txt)
            if any(x in low for x in ('/api/', 'graphql', 'catalog', 'search', 'collection', 'browse')):
                api_urls.add(u)
        except Exception:
            pass
    page.on('response', on_response)
    try:
        await page.goto(START, wait_until='domcontentloaded', timeout=45000)
        await accept_cookies(page)
        await expand_and_paginate(page, rounds=12, max_pages=15)
        await page.wait_for_timeout(1800)
    except Exception as e:
        logging.debug('Bootstrap network: %s', e)
    finally:
        try:
            page.remove_listener('response', on_response)
        except Exception:
            pass
    for txt in bodies:
        urls = extract_runtime_urls(txt)
        features |= {x for x in urls if is_feature(x)}
        cats |= {x for x in urls if is_collection(x)}
    try:
        resources = await page.evaluate("performance.getEntriesByType('resource').map(e=>e.name)")
        api_urls |= {u for u in resources if same_host(u) and any(x in u.lower() for x in ('/api/', 'graphql', 'catalog', 'search', 'collection', 'browse'))}
    except Exception:
        pass
    logging.info('Rede/API: %d endpoints | %d filmes | %d coleções', len(api_urls), len(features), len(cats))
    return features, cats, api_urls


async def discover_categories(page):
    cats, features = set(), set()
    try:
        await page.goto(START, wait_until='domcontentloaded', timeout=45000)
        await accept_cookies(page)
        await page.wait_for_timeout(800)
        links = await expand_and_paginate(page, rounds=14, max_pages=20)
        cats |= {x for x in links if is_collection(x)}
        features |= {x for x in links if is_feature(x)}
    except Exception as e:
        logging.debug('Home: %s', e)
    logging.info('Home/menu: %d coleções | %d filmes', len(cats), len(features))
    return cats, features


async def discover_category(page, cat):
    cat = localize_runtime_url(cat)
    feats = set()
    try:
        await page.goto(cat, wait_until='domcontentloaded', timeout=40000)
        await accept_cookies(page)
        await page.wait_for_timeout(700)
        links = await expand_and_paginate(page, rounds=20, max_pages=50)
        feats = {x for x in links if is_feature(x)}
    except Exception as e:
        logging.debug('Categoria %s: %s', cat, e)
    logging.info('Categoria %s -> %d filmes/páginas VOD', cat, len(feats))
    return feats


async def select_portuguese_audio(page):
    # Click visible Portuguese selectors if the player exposes them.
    selectors = [
        'button:has-text("Português")', 'button:has-text("Portuguese")',
        '[role=button]:has-text("Português")', '[role=button]:has-text("Portuguese")',
        'text=Português (Brasil)', 'text=Português', 'text=Portuguese',
        '[aria-label*="Português" i]', '[aria-label*="Portuguese" i]',
        '[title*="Português" i]', '[title*="Portuguese" i]',
        '[data-language*="pt" i]', '[data-lang="pt-BR"]', '[data-lang="pt"]'
    ]
    for sel in selectors:
        try:
            loc = page.locator(sel)
            n = min(await loc.count(), 4)
            for i in range(n):
                try:
                    if await loc.nth(i).is_visible(timeout=250):
                        await loc.nth(i).click(force=True, timeout=700)
                        await page.wait_for_timeout(450)
                except Exception:
                    pass
        except Exception:
            pass


def stream_payload_language(url):
    """Return (language, explicit) from Runtime's payload when available."""
    try:
        payload = (parse_qs(urlparse(url).query).get('payload') or [''])[0]
        if not payload:
            return '', False
        raw = base64.b64decode(payload + '=' * ((4 - len(payload) % 4) % 4)).decode('utf-8', 'ignore')
        low = raw.lower()
        m = re.search(r'"defaultaudiolang"\s*:\s*"([a-z-]+)"', low)
        if m:
            return m.group(1), True
        m = re.search(r'defaultaudiolang[/:%]+([a-z-]+)', low)
        if m:
            return m.group(1), True
    except Exception:
        pass
    return '', False


def manifest_language(url, session=None):
    """Return pt/en/unknown from an HLS master. Unknown is not automatically rejected."""
    lang, explicit = stream_payload_language(url)
    if explicit:
        if lang.startswith(('pt', 'por')):
            return 'pt'
        if lang.startswith(('en', 'eng')):
            return 'en'
    try:
        ss = session or requests.Session()
        r = ss.get(url, headers={'User-Agent': UA, 'Referer': START + '/'}, timeout=12)
        if r.status_code != 200:
            return 'unknown'
        txt = r.text
        if re.search(r'#EXT-X-MEDIA[^\n]*TYPE=AUDIO[^\n]*(?:LANGUAGE|NAME)=["\'](?:pt(?:-BR)?|por|portugu[eê]s)', txt, re.I):
            return 'pt'
        if re.search(r'(?:LANGUAGE|NAME)=["\'](?:pt(?:-BR)?|por|portugu[eê]s)["\']', txt, re.I):
            return 'pt'
        if re.search(r'#EXT-X-MEDIA[^\n]*TYPE=AUDIO[^\n]*(?:LANGUAGE|NAME)=["\'](?:en(?:-US)?|eng|english)', txt, re.I):
            return 'en'
    except Exception:
        pass
    return 'unknown'


def manifest_has_portuguese(url, session=None, page_locale=True):
    lang = manifest_language(url, session)
    # Explicit English is rejected. Explicit Portuguese is accepted. Unknown is
    # accepted only when the stream was obtained from the pt-BR page/player.
    if lang == 'pt':
        return True
    if lang == 'en':
        return False
    return bool(page_locale)


async def capture_stream(page, url):
    found = []
    def on_response(resp):
        u = resp.url
        if STREAM_RE.search(u):
            found.append(u)
    page.on('response', on_response)
    try:
        await page.goto(localize_runtime_url(url), wait_until='domcontentloaded', timeout=35000)
        await accept_cookies(page)
        await page.wait_for_timeout(1200)
        await select_portuguese_audio(page)
        # Trigger playback once; avoid clicking every possible button, which made
        # previous versions spend excessive time on each title.
        for sel in ['video', 'button[aria-label*="play" i]', '[role=button][aria-label*="play" i]']:
            try:
                loc = page.locator(sel).first
                if await loc.is_visible(timeout=300):
                    await loc.click(force=True, timeout=700)
                    await page.wait_for_timeout(1300)
                    break
            except Exception:
                pass
        await page.wait_for_timeout(900)
        try:
            found += await page.evaluate("performance.getEntriesByType('resource').map(e=>e.name).filter(x=>/\\.(m3u8|mpd)(?:$|[?#])/i.test(x))")
        except Exception:
            pass
        try:
            found += await page.locator('video,source').evaluate_all("els=>els.map(e=>e.src||e.currentSrc).filter(Boolean)")
        except Exception:
            pass
        try:
            html = await page.content()
            found += re.findall(r'https?://[^"\'<>\s]+?\.(?:m3u8|mpd)(?:\?[^"\'<>\s]*)?', html, re.I)
        except Exception:
            pass
    except PlaywrightTimeoutError:
        logging.debug('Timeout VOD: %s', url)
    except Exception as e:
        logging.debug('VOD %s: %s', url, e)
    finally:
        try:
            page.remove_listener('response', on_response)
        except Exception:
            pass
    cand = []
    for u in found:
        if isinstance(u, str) and u.startswith(('http://', 'https://')) and STREAM_RE.search(u):
            if not any(x in u.lower() for x in ('doubleclick', 'googleads', 'analytics', 'facebook.com')):
                cand.append(u)
    cand = list(dict.fromkeys(cand))
    hls = [x for x in cand if re.search(r'\.m3u8(?:$|[?#])', x, re.I)]
    dash = [x for x in cand if re.search(r'\.mpd(?:$|[?#])', x, re.I)]
    sess = requests.Session()
    for u in hls:
        if manifest_has_portuguese(u, sess, page_locale=True):
            return u, 'hls'
    # DASH is accepted only when the URL itself explicitly says pt; otherwise we
    # avoid inventing an audio-language guarantee.
    for u in dash:
        lang, explicit = stream_payload_language(u)
        if explicit and lang.startswith(('pt', 'por')):
            return u, 'dash'
    return '', ''


async def scrape(max_categories=120, max_items=1200, concurrency=6):
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu'])
        ctx = await browser.new_context(locale='pt-BR', user_agent=UA)
        page = await ctx.new_page()

        cats, features = await discover_categories(page)
        net_features, net_cats, _ = await discover_network(page)
        features |= net_features
        cats |= net_cats
        features |= await sitemap_urls(ctx.request)

        # Runtime has a finite set of common genre slugs. They are supplements,
        # not the discovery mechanism. Keep them localized to pt-BR.
        seeds = [
            'action','adventure','animation','comedy','crime','documentary','drama',
            'family','horror','romance','science-fiction','sci-fi','thriller','western',
            'classic','foreign','music','mystery','fantasy','war','history','kids',
            'independent','international','biography','sport','suspense'
        ]
        cats |= {f'{BASE}/pt-br/collections/{s}' for s in seeds}
        cats = sorted(cats)[:max_categories]

        # Category pages are the primary expansion path. Each category now follows
        # actual pagination instead of relying only on infinite-scroll clicks.
        for cat in cats:
            features |= await discover_category(page, cat)
            if len(features) >= max_items:
                break

        # One final home pass catches "recommended" and cross-category rows.
        try:
            await page.goto(START, wait_until='domcontentloaded', timeout=30000)
            links = await expand_and_paginate(page, rounds=8, max_pages=15)
            features |= {x for x in links if is_feature(x)}
            cats |= {x for x in links if is_collection(x)}
        except Exception:
            pass

        features = {localize_runtime_url(x) for x in features if is_feature(localize_runtime_url(x))}
        urls = sorted(features)[:max_items]
        logging.info('CATÁLOGO BRASIL DESCOBERTO: %d categorias | %d páginas VOD', len(cats), len(urls))

        # Reuse a small pool of pages instead of creating a new browser context for
        # every film. This is the main runtime improvement over v5.
        pages = [await ctx.new_page() for _ in range(max(1, concurrency))]
        queue = asyncio.Queue()
        for u in urls:
            await queue.put(u)
        items = []
        lock = asyncio.Lock()

        async def worker(idx, p):
            while True:
                try:
                    u = queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                try:
                    await p.goto(u, wait_until='domcontentloaded', timeout=25000)
                    await accept_cookies(p)
                    html = await p.content()
                    item = parse_item(html, u)
                    if item:
                        stream, typ = await capture_stream(p, u)
                        item.stream_url = stream
                        item.stream_type = typ
                        item.active = bool(stream)
                        item.last_seen = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
                        async with lock:
                            items.append(item)
                            if len(items) % 25 == 0:
                                logging.info('VOD processados: %d/%d | com stream: %d', len(items), len(urls), sum(bool(x.stream_url) for x in items))
                except Exception as e:
                    logging.debug('Item %s: %s', u, e)
                finally:
                    queue.task_done()

        await asyncio.gather(*(worker(i, p) for i, p in enumerate(pages)))
        for p in pages:
            try: await p.close()
            except Exception: pass
        await browser.close()
        logging.info('PROCESSAMENTO FINAL: %d itens | %d com stream', len(items), sum(bool(x.stream_url) for x in items))
        return items, cats
