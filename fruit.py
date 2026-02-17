sugi import time
import requests
from bs4 import BeautifulSoup
import re

# =========================
# Session + User-Agent
# =========================
session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (compatible; ArchiveScraper/1.0)"
})

# =========================
# 初期化
# =========================
with open('yui.txt', 'w', encoding='utf-8') as f:
    f.write("url,title,date,content\n")

with open('fruit.txt', 'w', encoding='utf-8') as f:
    f.write("url,title,date,content\n")

# =========================
# Utility
# =========================
def clean_text(text):
    if not text:
        return ""
    text = re.sub(r'\s+', ' ', text)
    text = text.replace(',', '，')
    return text.strip()

# =========================
# Extractors
# =========================
def extract_title(soup):
    h3 = soup.select_one('article.info_article h3')
    if h3:
        return clean_text(h3.get_text())

    for selector in ['h1', 'h2']:
        tag = soup.find(selector)
        if tag:
            return clean_text(tag.get_text())

    if soup.title:
        return clean_text(soup.title.get_text())

    return ""

def extract_date(soup):
    time_area = soup.select_one('span.time_area')
    if time_area:
        return clean_text(time_area.get_text())

    selectors = [
        'time',
        '.date',
        '.entry-date',
        '.info_date',
        '.post-date',
        '.news-date'
    ]
    for sel in selectors:
        tag = soup.select_one(sel)
        if tag:
            return clean_text(tag.get_text())

    text = soup.get_text()
    m = re.search(r'(\d{4}[./-]\d{1,2}[./-]\d{1,2})', text)
    return m.group(1) if m else ""

def extract_content(soup):
    div = soup.select_one('article.info_article div.content')
    if not div:
        return ""

    # script / style / Wayback用ゴミ除去
    for tag in div.find_all(['script', 'style']):
        tag.decompose()

    return clean_text(div.get_text())

# =========================
# Wayback 判定ロジック
# =========================
def is_wayback_not_exist(response):
    """Wayback上で『保存されていない／除外』と断定できる"""
    if response is None:
        return True

    if response.status_code in (404, 410):
        return True

    text = response.text.lower()
    keywords = [
        "has not archived",
        "not available on the wayback machine",
        "excluded from the wayback machine",
        "this url is not available",
        "page cannot be displayed"
    ]
    return any(k in text for k in keywords)

def is_wayback_temporary_error(response):
    """Waybackの一時障害・過負荷"""
    if response is None:
        return True

    if response.status_code in (429, 500, 502, 503, 504):
        return True

    text = response.text.lower()
    keywords = [
        "service unavailable",
        "temporarily unavailable",
        "please try again later",
        "wayback machine is down"
    ]
    return any(k in text for k in keywords)

# =========================
# Fetch
# =========================
def fetch(url, max_retry=5):
    """
    Wayback Machine 専用 fetch
    - 存在しない → 即 None
    - 一時障害のみリトライ
    """
    retry = 0
    while retry < max_retry:
        try:
            r = session.get(url, timeout=30)

            # 明確に「存在しない」
            if is_wayback_not_exist(r):
                return None

            # 正常取得
            if r.status_code == 200 and not is_wayback_temporary_error(r):
                return r

            # Wayback 側の問題 → リトライ
            print(f"[Wayback temporary error] {r.status_code} retry {retry+1}/{max_retry}")

        except requests.exceptions.RequestException as e:
            print(f"[Connection error] retry {retry+1}/{max_retry}\n{e}")

        retry += 1
        time.sleep(120)

    print("Retry limit reached → skip")
    return None

# =========================
# ogurayui.jp（コメントアウト）
# =========================
'''
for i in range(1, 5000):
    url = f'https://web.archive.org/web/20220815000000/http://www.ogurayui.jp/info/{i}/'
    print(f'Processing {url}')

    response = fetch(url)
    time.sleep(30)

    if response is None:
        continue

    soup = BeautifulSoup(response.content, 'html.parser')

    title = extract_title(soup)
    date = extract_date(soup)
    content = extract_content(soup)

    if content:
        with open('yui.txt', 'a', encoding='utf-8') as f:
            f.write(f"{url},{title},{date},{content}\n")
'''

# =========================
# yuikaori.info
# =========================
for i in range(1, 3000):
    url = f'https://web.archive.org/web/20170630000000/http://www.yuikaori.info/info/{i}/'
    print(f'Processing {url}')

    response = fetch(url)
    time.sleep(10)

    if response is None:
        continue

    soup = BeautifulSoup(response.content, 'html.parser')

    title = extract_title(soup)
    date = extract_date(soup)
    content = extract_content(soup)

    if content:
        with open('fruit.txt', 'a', encoding='utf-8') as f:
            f.write(f"{url},{title},{date},{content}\n")

print("Done!")
