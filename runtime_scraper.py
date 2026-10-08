from __future__ import annotations
import asyncio, json, logging, re, time
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse
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
def same_host(u): return urlparse(u).netloc.lower() in {'runtime.tv','www.runtime.tv'}
def is_feature(u): return same_host(u) and bool(FEATURE_RE.match(urlparse(u).path))
def is_collection(u): return same_host(u) and bool(COLLECTION_RE.match(urlparse(u).path))

def all_links(html, base):
    soup=BeautifulSoup(html,'lxml'); out=set()
    for a in soup.find_all('a',href=True):
        try:
            u=canon(urljoin(base,a['href']))
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
        return {canon(x) for x in await page.locator('a[href]').evaluate_all('els=>els.map(e=>e.href).filter(Boolean)') if same_host(x)}
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

async def discover_categories(page):
    cats=set(); features=set()
    await page.goto(START,wait_until='domcontentloaded',timeout=40000); await accept_cookies(page); await page.wait_for_timeout(2500)
    # Open menu/navigation drawers; category links may only exist after interaction.
    for sel in ['text=MENU','button:has-text("MENU")','[aria-label*="menu" i]','button[class*="menu" i]']:
        try:
            loc=page.locator(sel).first
            if await loc.is_visible(timeout=700): await loc.click(force=True); await page.wait_for_timeout(1200); break
        except: pass
    links=await expand_page(page,rounds=8)
    cats|={x for x in links if is_collection(x)}
    features|={x for x in links if is_feature(x)}
    logging.info('Categorias encontradas no menu/home: %d',len(cats))
    return cats,features

async def discover_category(page,cat):
    await page.goto(cat,wait_until='domcontentloaded',timeout=40000); await accept_cookies(page); await page.wait_for_timeout(2200)
    links=await expand_page(page,rounds=20)
    feats={x for x in links if is_feature(x)}
    logging.info('Categoria %s -> %d filmes/páginas VOD',cat,len(feats))
    return feats

async def capture_stream(page,url):
    found=[]
    def on_response(resp):
        u=resp.url
        if STREAM_RE.search(u): found.append(u)
    page.on('response',on_response)
    try:
        await page.goto(url,wait_until='domcontentloaded',timeout=40000); await accept_cookies(page); await page.wait_for_timeout(2200)
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
    if h:return h[0],'hls'
    if d:return d[0],'dash'
    return '',''

async def scrape(max_categories=100,max_items=2000,concurrency=3):
    async with async_playwright() as pw:
        browser=await pw.chromium.launch(headless=True,args=['--no-sandbox','--disable-dev-shm-usage','--disable-gpu'])
        ctx=await browser.new_context(locale='pt-BR',user_agent=UA)
        page=await ctx.new_page()
        cats,features=await discover_categories(page)
        # Fallback: known category route candidates, only used if menu discovery is sparse.
        seeds=['action','adventure','animation','comedy','crime','documentary','drama','family','horror','romance','science-fiction','sci-fi','thriller','western','classic','foreign','music','mystery','fantasy']
        for s in seeds:
            cats.add(f'{BASE}/collections/{s}')
        cats=list(sorted(cats))[:max_categories]
        all_features=set(features)
        for i,cat in enumerate(cats,1):
            try: all_features |= await discover_category(page,cat)
            except Exception as e: logging.debug('Categoria %s falhou: %s',cat,e)
            if len(all_features)>=max_items: break
        logging.info('TOTAL: %d categorias visitadas | %d páginas VOD descobertas',len(cats),len(all_features))
        urls=list(sorted(all_features))[:max_items]
        sem=asyncio.Semaphore(concurrency); items=[]
        async def one(u):
            async with sem:
                c=await browser.new_context(locale='pt-BR',user_agent=UA); p=await c.new_page()
                try:
                    resp=await p.request.get(u,timeout=25000); html=await resp.text(); item=parse_item(html,u)
                    if not item:return None
                    # Categorias are inferred from links on the film page too.
                    stream,typ=await capture_stream(p,u)
                    item.stream_url=stream; item.stream_type=typ; item.active=bool(stream); item.last_seen=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())
                    return item
                except Exception as e: logging.debug('Item %s: %s',u,e); return None
                finally: await c.close()
        results=await asyncio.gather(*(one(u) for u in urls)); items=[x for x in results if x]
        await browser.close(); return items,cats
