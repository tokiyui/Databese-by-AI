import time
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
with open('inori.txt', 'w', encoding='utf-8') as f:
    f.write("url,title,date,content\n")

def clean_text(text):
    if not text:
        return ""
    text = re.sub(r'\s+', ' ', text)
    text = text.replace(',', '，')
    return text.strip()

# =========================
# 抽出関数（HTML構造対応）
# =========================
def extract_title(soup):
    tag = soup.select_one('p.title')
    return clean_text(tag.get_text()) if tag else ""

def extract_date(soup):
    tag = soup.select_one('.list__data.date')
    if tag:
        return clean_text(tag.get_text()).replace('.', '-')
    return ""

def extract_content(soup):
    div = soup.select_one('div.aem-post')
    return clean_text(div.get_text(separator='\n')) if div else ""

# =========================
# 取得処理
# =========================
def fetch(url):
    while True:
        try:
            r = session.get(url, timeout=30)
            if r.status_code == 200:
                return r
            if r.status_code in (404, 410):
                return None
            print(f"Status {r.status_code} → retry after 10s")
        except requests.exceptions.RequestException as e:
            print(f"Connection error → retry after 10s\n{e}")
        time.sleep(10)

# =========================
# メインループ
# =========================
for i in range(1, 2000):
    url = f'https://www.inoriminase.com/news/?id={i}'
    print(f'Processing {url}')

    response = fetch(url)
    time.sleep(0.5)

    if response is None:
        continue

    soup = BeautifulSoup(response.content, 'html.parser')

    title = extract_title(soup)
    date = extract_date(soup)
    content = extract_content(soup)

    if title and content:
        with open('inori.txt', 'a', encoding='utf-8') as f:
            f.write(f"{url},{title},{date},{content}\n")

print("Done!")
