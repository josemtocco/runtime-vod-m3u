from __future__ import annotations
import asyncio, json, logging, re, time
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse, parse_qs, unquote
import requests
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

BASE='https://www.runtime.tv'
START='https://www.runtime.tv/pt-br'
UA='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140 Safari/537.36'
HEADERS={'User-Agent':UA,'Accept-Language':'pt-BR,pt;q=0.9,en;q=0.8'}
FEATURE_RE=re.compile(r'^/(?:pt-br/)?feature/[^?#]+/?$',re.I)
COLLECTION_RE=re.compile(r'^/(?:pt-br/)?collections/[^?#]+/?$',re.I)
STREAM_RE=re.compile(r'\.(?:m3u8|mpd)(?:$|[?#])',re.I)

@dataclass
class Item:
    key:str; title:str; url:str; genres:list[str]; description:str; logo:str
    stream_url:str=''; stream_type:str=''; last_seen:str=''; active:bool=False
    category_urls:list[str]=None

def clean(s): return re.sub(r'\s+',' ',s or '').strip()
def canon(u):
    p=urlparse(u); return f'{p.scheme}://{p.netloc}{p.path.rstrip("/") or "/"}'

def localize_runtime_url(u):
    """Força o catálogo brasileiro da Runtime."""
    u=canon(u)
    p=urlparse(u)
    path=p.path
    if path.startswith('/pt-br/'):
        return u
    if path.startswith('/feature/'):
        return f'{p.scheme}://{p.netloc}/pt-br{path}'
    if path.startswith('/collections/'):
        return f'{p.scheme}://{p.netloc}/pt-br{path}'
    return u
def same_host(u): return urlparse(u).netloc.lower() in {'runtime.tv','www.runtime.tv'}
def is_feature(u): return same_host(u) and bool(FEATURE_RE.match(urlparse(u).path))
def is_collection(u): return same_host(u) and bool(COLLECTION_RE.match(urlparse(u).path))

def all_links(html, base):
    soup=BeautifulSoup(html,'lxml'); out=set()
    for a in soup.find_all('a',href=True):
        try:
            u=localize_runtime_url(urljoin(base,a['href']))
            if same_host(u): out.add(u)
        except: pass
    return out

def parse_item(html,url,category_urls=None):
    soup=BeautifulSoup(html,'lxml');
    if not is_feature(url): return None
    title=''
    h=soup.find('h1')
    if h: title=clean(h.get_text(' ',strip=True))
    if not title:
        m=soup.find('meta',attrs={'property':'og:title'}); title=clean(m.get('content','')) if m else ''
    if not title and soup.title: title=clean(soup.title.get_text(' ',strip=True))
    title=re.sub(r'\s*\|\s*Runtime\s*$','',title,flags=re.I)
    if not title: return None
    desc=''; m=soup.find('meta',attrs={'name':'description'})
    if m: desc=clean(m.get('content',''))
    if not desc:
        m=soup.find('meta',attrs={'property':'og:description'}); desc=clean(m.get('content','')) if m else ''
    logo=''; m=soup.find('meta',attrs={'property':'og:image'})
    if m: logo=urljoin(url,m.get('content',''))
    genres=[]
    for a in soup.select('a[href*="/collections/"]'):
        t=clean(a.get_text(' ',strip=True))
        if t and len(t)<60: genres.append(t)
    text=clean(soup.get_text(' ',strip=True))
    mm=re.search(r'(?:Genres|Gêneros)\s+(.*?)(?:Director|Diretor|Actor|Ator|$)',text,re.I)
    if mm:
        genres += [clean(x) for x in re.split(r'[,|•/]+',mm.group(1)) if clean(x)]
    genres=list(dict.fromkeys(x for x in genres if 1<len(x)<60))[:6]
    return Item(canon(url),title,canon(url),genres,desc,logo,category_urls=list(category_urls or []))

async def accept_cookies(page):
    for sel in ['text=I agree to allow cookies','text=Allow cookies','button:has-text("Allow cookies")','button:has-text("I agree")']:
        try:
            loc=page.locator(sel).first
            if await loc.is_visible(timeout=500):
                await loc.click(force=True); await page.wait_for_timeout(500); break
        except: pass

async def extract_page_links(page):
    try:
        return {localize_runtime_url(x) for x in await page.locator('a[href]').evaluate_all('els=>els.map(e=>e.href).filter(Boolean)') if same_host(x)}
    except: return set()

async def expand_page(page, rounds=12):
    # Scroll and activate common "load more" controls until no growth.
    last=0; stable=0
    for _ in range(rounds):
        await page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
        await page.wait_for_timeout(900)
        for sel in ['button:has-text("Load more")','button:has-text("Carregar mais")','a:has-text("Load more")','a:has-text("Carregar mais")','[aria-label*="load more" i]']:
            try:
                loc=page.locator(sel); n=min(await loc.count(),3)
                for i in range(n):
                    try: await loc.nth(i).click(force=True,timeout=700); await page.wait_for_timeout(900)
                    except: pass
            except: pass
        links=await extract_page_links(page)
        if len(links)==last: stable+=1
        else: stable=0; last=len(links)
        if stable>=3: break
    return await extract_page_links(page)

async def sitemap_urls(request):
    """Walk public sitemap/index files exposed by Runtime."""
    seen=set(); found=set(); queue=[
        f'{BASE}/sitemap.xml', f'{BASE}/sitemap_index.xml',
        f'{BASE}/pt-br/sitemap.xml', f'{BASE}/pt-br/sitemap_index.xml',
        f'{BASE}/robots.txt'
    ]
    while queue and len(seen)<40:
        u=queue.pop(0)
        if u in seen: continue
        seen.add(u)
        try:
            r=await request.get(u,timeout=20000,headers={'User-Agent':UA,'Accept-Language':'pt-BR,pt;q=0.9'})
            if r.status!=200: continue
            txt=await r.text()
            if u.endswith('robots.txt'):
                for m in re.findall(r'(?im)^\s*Sitemap:\s*(\S+)',txt): queue.append(m.strip())
                continue
            locs=re.findall(r'<loc>\s*(.*?)\s*</loc>',txt,re.I|re.S)
            for loc in locs:
                loc=unquote(clean(loc))
                if loc.lower().endswith('.xml') and ('sitemap' in loc.lower() or 'index' in loc.lower()):
                    queue.append(loc)
                elif same_host(loc):
                    loc=localize_runtime_url(loc)
                    if is_feature(loc): found.add(loc)
        except Exception as e: logging.debug('Sitemap %s: %s',u,e)
    logging.info('Sitemap/robots: %d páginas VOD',len(found))
    return found

async def discover_network(page):
    """Capture public API/JSON responses and recursively extract Runtime URLs."""
    features=set(); cats=set(); api_urls=set(); bodies=[]
    async def response_handler(resp):
        u=resp.url
        if not same_host(u): return
        ct=(resp.headers.get('content-type') or '').lower()
        if 'json' not in ct and not any(x in u.lower() for x in ['/api/','graphql','catalog','search','collection']): return
        try:
            txt=await resp.text()
            if len(txt)>3_000_000: txt=txt[:3_000_000]
            bodies.append(txt)
            if '/api/' in u.lower() or 'graphql' in u.lower() or 'catalog' in u.lower() or 'search' in u.lower(): api_urls.add(u)
        except: pass
    page.on('response',response_handler)
    try:
        await page.goto(START,wait_until='domcontentloaded',timeout=50000)
        await accept_cookies(page); await expand_page(page,rounds=15)
        await page.wait_for_timeout(2500)
    except Exception as e: logging.debug('Bootstrap network: %s',e)
    finally:
        try: page.remove_listener('response',response_handler)
        except: pass
    # Extract URLs from raw JSON/JS response bodies. This catches APIs whose
    # records are not represented as ordinary <a> elements.
    for txt in bodies:
        for raw in re.findall(r'https?://(?:www\.)?runtime\.tv[^"\'\\<>\s]+',txt,re.I):
            u=localize_runtime_url(raw.replace('\\/','/'))
            if is_feature(u): features.add(u)
            elif is_collection(u): cats.add(u)
        for raw in re.findall(r'(?<![A-Za-z0-9])/(?:pt-br/)?(?:feature|collections)/[^"\'\\<>\s?#]+',txt,re.I):
            u=localize_runtime_url(urljoin(BASE,raw.replace('\\/','/')))
            if is_feature(u): features.add(u)
            elif is_collection(u): cats.add(u)
    # Also inspect resource URLs, useful for REST/GraphQL endpoints.
    try:
        resources=await page.evaluate("performance.getEntriesByType('resource').map(e=>e.name)")
        api_urls |= {u for u in resources if same_host(u) and any(x in u.lower() for x in ['/api/','graphql','catalog','search','collection'])}
    except: pass
    logging.info('Rede/API: %d endpoints | %d filmes | %d coleções',len(api_urls),len(features),len(cats))
    return features,cats,api_urls

async def crawl_navigation(page, seeds, max_pages=500, max_depth=3):
    """Breadth-first crawl of Runtime's public navigation, restricted to likely catalog routes."""
    q=[(localize_runtime_url(x),0) for x in seeds]
    seen=set(); features=set(); cats=set()
    allow_words=('pt-br','feature','collections','movie','movies','film','films','catalog','browse','discover','search','serie','series','genre','genero')
    while q and len(seen)<max_pages:
        u,d=q.pop(0)
        u=localize_runtime_url(u)
        if u in seen or not same_host(u): continue
        path=urlparse(u).path.lower()
        if d>0 and not any(w in path for w in allow_words): continue
        seen.add(u)
        if is_feature(u): features.add(u); continue
        if is_collection(u): cats.add(u)
        try:
            await page.goto(u,wait_until='domcontentloaded',timeout=30000)
            await accept_cookies(page)
            links=await expand_page(page,rounds=8 if d<2 else 4)
            for x in links:
                x=localize_runtime_url(x)
                if is_feature(x): features.add(x)
                elif is_collection(x): cats.add(x)
                elif d<max_depth and same_host(x):
                    xp=urlparse(x).path.lower()
                    if any(w in xp for w in allow_words): q.append((x,d+1))
        except Exception as e: logging.debug('Crawl %s: %s',u,e)
    logging.info('Crawl navegação: %d páginas | %d filmes | %d coleções',len(seen),len(features),len(cats))
    return features,cats

async def discover_categories(page):
    cats=set(); features=set()
    await page.goto(START,wait_until='domcontentloaded',timeout=50000); await accept_cookies(page); await page.wait_for_timeout(2500)
    for sel in ['text=MENU','button:has-text("MENU")','[aria-label*="menu" i]','button[class*="menu" i]']:
        try:
            loc=page.locator(sel).first
            if await loc.is_visible(timeout=700): await loc.click(force=True); await page.wait_for_timeout(1000); break
        except: pass
    links=await expand_page(page,rounds=15)
    cats|={x for x in links if is_collection(x)}
    features|={x for x in links if is_feature(x)}
    logging.info('Home/menu: %d coleções | %d filmes',len(cats),len(features))
    return cats,features

async def discover_category(page,cat):
    cat=localize_runtime_url(cat)
    await page.goto(cat,wait_until='domcontentloaded',timeout=50000); await accept_cookies(page); await page.wait_for_timeout(1800)
    links=await expand_page(page,rounds=45)
    feats={x for x in links if is_feature(x)}
    logging.info('Categoria %s -> %d filmes/páginas VOD',cat,len(feats))
    return feats

async def select_portuguese_audio(page):
    # A Runtime BR page can still expose an English default track. Try the
    # visible language/audio controls before accepting the stream.
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
            loc=page.locator(sel)
            n=min(await loc.count(),4)
            for i in range(n):
                try:
                    if await loc.nth(i).is_visible(timeout=400):
                        await loc.nth(i).click(force=True,timeout=900)
                        await page.wait_for_timeout(800)
                except: pass
        except: pass


def manifest_has_portuguese(url, session=None):
    """Require an explicit Portuguese audio indication in the HLS master."""
    if not url: return False
    low=url.lower()
    # The Runtime often embeds defaultAudioLang inside a base64 JSON payload.
    try:
        from urllib.parse import parse_qs
        import base64
        payload=(parse_qs(urlparse(url).query).get('payload') or [''])[0]
        if payload:
            raw=base64.b64decode(payload + '='*((4-len(payload)%4)%4)).decode('utf-8','ignore').lower()
            if re.search(r'"defaultaudiolang"\s*:\s*"(?:pt|pt-br|por)"', raw, re.I):
                return True
            if re.search(r'defaultaudiolang/(?:pt|pt-br|por)(?:/|%2f)', raw, re.I):
                return True
            # Explicit English default means this rendition is not acceptable.
            if re.search(r'"defaultaudiolang"\s*:\s*"en(?:-us)?"', raw, re.I):
                return False
    except Exception:
        pass
    try:
        import requests as _requests
        ss=session or _requests.Session()
        r=ss.get(url,headers={'User-Agent':UA,'Referer':BASE+'/pt-br/'},timeout=18)
        if r.status_code != 200: return False
        txt=r.text
        # HLS EXT-X-MEDIA audio groups normally identify the language with
        # LANGUAGE="pt", LANGUAGE="pt-BR" or NAME="Português".
        if re.search(r'EXT-X-MEDIA[^\n]*TYPE=AUDIO[^\n]*(?:LANGUAGE|NAME)=["\'](?:pt(?:-BR)?|por|portugu[eê]s)', txt, re.I):
            return True
        if re.search(r'(?:LANGUAGE|NAME)=["\'](?:pt(?:-BR)?|por|portugu[eê]s)["\']', txt, re.I):
            return True
    except Exception as e:
        logging.debug('Manifesto não pôde ser analisado: %s',e)
    return False

async def capture_stream(page,url):
    found=[]
    def on_response(resp):
        u=resp.url
        if STREAM_RE.search(u): found.append(u)
    page.on('response',on_response)
    try:
        await page.goto(localize_runtime_url(url),wait_until='domcontentloaded',timeout=40000); await accept_cookies(page); await page.wait_for_timeout(2200)
        await select_portuguese_audio(page)
        # Prefer explicit player controls, then inspect video/source elements.
        for sel in ['button[aria-label*="play" i]','button[title*="play" i]','[role=button][aria-label*="play" i]','button[aria-label*="assistir" i]','video']:
            try:
                loc=page.locator(sel); n=min(await loc.count(),5)
                for i in range(n):
                    try: await loc.nth(i).click(force=True,timeout=1200); await page.wait_for_timeout(2200)
                    except: pass
            except: pass
        await page.wait_for_timeout(2500)
        html=await page.content()
        found += re.findall(r'https?://[^"\'<>\s]+?\.(?:m3u8|mpd)(?:\?[^"\'<>\s]*)?',html,re.I)
        try:
            found += [x for x in await page.evaluate("performance.getEntriesByType('resource').map(e=>e.name)") if STREAM_RE.search(x)]
        except: pass
        try:
            found += await page.locator('video,source').evaluate_all("els=>els.map(e=>e.src||e.currentSrc).filter(Boolean)")
        except: pass
    except PlaywrightTimeoutError: logging.warning('Timeout VOD: %s',url)
    except Exception as e: logging.debug('VOD %s: %s',url,e)
    finally:
        try: page.remove_listener('response',on_response)
        except: pass
    cand=[]
    for u in found:
        if u.startswith(('http://','https://')) and STREAM_RE.search(u) and not any(x in u.lower() for x in ['doubleclick','googleads','analytics','facebook.com']): cand.append(u)
    cand=list(dict.fromkeys(cand)); h=[x for x in cand if re.search(r'\.m3u8(?:$|[?#])',x,re.I)]; d=[x for x in cand if re.search(r'\.mpd(?:$|[?#])',x,re.I)]
    if h:
        for u in h:
            if manifest_has_portuguese(u):
                return u,'hls'
        logging.info('VOD sem áudio português explícito: %s',url)
        return '',''
    if d:
        logging.info('VOD DASH sem verificação de áudio português: %s',url)
        return '',''
    return '',''

async def scrape(max_categories=300,max_items=10000,concurrency=3):
    async with async_playwright() as pw:
        browser=await pw.chromium.launch(headless=True,args=['--no-sandbox','--disable-dev-shm-usage','--disable-gpu'])
        ctx=await browser.new_context(locale='pt-BR',user_agent=UA)
        page=await ctx.new_page()

        cats,features=await discover_categories(page)
        net_features,net_cats,api_urls=await discover_network(page)
        features |= net_features; cats |= net_cats

        # Public sitemap is the deepest/most deterministic catalog source when
        # Runtime exposes one. It is intentionally combined with DOM/API crawling.
        features |= await sitemap_urls(ctx.request)

        # Crawl the Brazilian navigation tree rather than relying on a fixed list
        # of genres. This is important because Runtime can expose hidden rows/pages.
        nav_seeds={START, f'{BASE}/pt-br', *cats}
        nav_features,nav_cats=await crawl_navigation(page,nav_seeds,max_pages=700,max_depth=3)
        features |= nav_features; cats |= nav_cats

        # Fallback seeds, ALWAYS localized. They supplement discovery; they do not
        # replace it and therefore cannot hide new Runtime categories.
        seeds=['action','adventure','animation','comedy','crime','documentary','drama','family','horror','romance','science-fiction','sci-fi','thriller','western','classic','foreign','music','mystery','fantasy','war','history','kids','independent','international']
        for s in seeds: cats.add(f'{BASE}/pt-br/collections/{s}')

        cats=list(sorted(cats))[:max_categories]
        for i,cat in enumerate(cats,1):
            try: features |= await discover_category(page,cat)
            except Exception as e: logging.debug('Categoria %s falhou: %s',cat,e)
            if len(features)>=max_items: break

        features=set(localize_runtime_url(x) for x in features if is_feature(localize_runtime_url(x)))
        logging.info('DESCOBERTA PROFUNDA: %d categorias | %d páginas VOD',len(cats),len(features))
        urls=list(sorted(features))[:max_items]

        sem=asyncio.Semaphore(concurrency); items=[]
        async def one(u):
            async with sem:
                c=await browser.new_context(locale='pt-BR',user_agent=UA); p=await c.new_page()
                try:
                    u=localize_runtime_url(u)
                    resp=await p.request.get(u,timeout=30000); html=await resp.text(); item=parse_item(html,u)
                    if not item:return None
                    stream,typ=await capture_stream(p,u)
                    item.stream_url=stream; item.stream_type=typ; item.active=bool(stream); item.last_seen=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())
                    return item
                except Exception as e: logging.debug('Item %s: %s',u,e); return None
                finally: await c.close()
        # Process in batches so very large catalogs do not create thousands of
        # simultaneous Playwright contexts.
        for i in range(0,len(urls),120):
            batch=urls[i:i+120]
            results=await asyncio.gather(*(one(u) for u in batch)); items.extend(x for x in results if x)
            logging.info('VOD processados: %d/%d | com stream: %d',min(i+120,len(urls)),len(urls),sum(bool(x.stream_url) for x in items))
        await browser.close(); return items,cats

