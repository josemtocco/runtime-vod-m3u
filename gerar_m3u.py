from __future__ import annotations
import argparse,asyncio,json,logging,os,time
from pathlib import Path
from urllib.parse import quote
import requests
from runtime_scraper import scrape
ROOT=Path(__file__).resolve().parent; STATE=ROOT/'catalogo.json'; OUT=ROOT/'runtime_vod.m3u'
SHORTEN=os.getenv('SHORTEN_URLS','true').lower() not in {'0','false','no'}
TINY_TIMEOUT=int(os.getenv('TINYURL_TIMEOUT','20'))

def load():
    try:
        d=json.loads(STATE.read_text(encoding='utf8')); return d if isinstance(d,dict) else {}
    except: return {}
def esc(s): return (s or '').replace('"',"'").replace('\n',' ').strip()
def shorten(url,session):
    if not SHORTEN or not url:return url
    try:
        r=session.get('https://tinyurl.com/api-create.php',params={'url':url},timeout=TINY_TIMEOUT,headers={'User-Agent':'runtime-vod-m3u/3.0'})
        u=r.text.strip()
        if u.startswith('https://tinyurl.com/') and len(u)<100:return u
    except Exception as e: logging.warning('TinyURL falhou: %s',e)
    return url

def merge(items,old):
    now=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()); cur={}
    for x in items:
        d=x.__dict__.copy(); d['last_seen']=now; d['active']=bool(d.get('stream_url')); cur[x.key]=d
    merged=dict(old)
    for k,d in cur.items(): merged[k]=d
    for k in list(merged):
        if k not in cur: merged[k]['active']=False
    return merged

def write_m3u(cat):
    active=[d for d in cat.values() if d.get('active') and d.get('stream_url')]
    active.sort(key=lambda d:((d.get('genres') or ['VOD'])[0].lower(),d.get('title','').lower()))
    sess=requests.Session(); lines=['#EXTM3U']
    for d in active:
        title=esc(d.get('title')); genres=d.get('genres') or ['VOD']; group='Runtime | '+genres[0]
        attrs=f'tvg-name="{title}" group-title="{esc(group)}"'
        if d.get('logo'): attrs+=f' tvg-logo="{esc(d["logo"])}"'
        short=shorten(d['stream_url'],sess); d['playlist_url']=short
        lines += [f'#EXTINF:-1 {attrs},{title}',short]
    OUT.write_text('\n'.join(lines)+'\n',encoding='utf8'); return len(active)

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--max-categories',type=int,default=300); ap.add_argument('--max-items',type=int,default=10000); ap.add_argument('--concurrency',type=int,default=4); ap.add_argument('--verbose',action='store_true'); a=ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO,format='%(asctime)s | %(levelname)s | %(message)s')
    old=load(); logging.info('Catálogo anterior: %d itens',len(old))
    items,cats=asyncio.run(scrape(a.max_categories,a.max_items,a.concurrency)); logging.info('Categorias: %d | Itens processados: %d | com stream: %d',len(cats),len(items),sum(bool(x.stream_url) for x in items))
    if not items:
        logging.error('Nenhum VOD processado; preservando catálogo e M3U anterior.'); return 2
    cat=merge(items,old); n=write_m3u(cat); STATE.write_text(json.dumps(cat,ensure_ascii=False,indent=2,sort_keys=True),encoding='utf8'); logging.info('M3U gerada: %d itens ativos',n)
if __name__=='__main__': main()
