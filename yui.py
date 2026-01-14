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
# 蛻晄悄蛹�
# =========================
with open('yui.txt', 'w', encoding='utf-8') as f:
    f.write("url,title,date,content\n")
 
def clean_text(text):
    if not text:
        return ""
    text = re.sub(r'\s+', ' ', text)
    text = text.replace(',', '��')
    return text.strip()
 
# =========================
# 謚ｽ蜃ｺ髢｢謨ｰ��HTML讒矩�蟇ｾ蠢懶ｼ�
# =========================
def extract_title(soup):
    tag = soup.select_one('.section--detail .block--title .tit')
    if tag:
        return clean_text(tag.get_text(separator=''))
    return ""
 
def extract_date(soup):
    tag = soup.select_one('.section--detail .block--title .date')
    if tag:
        return clean_text(tag.get_text()).replace('.', '-')
    return ""
 
def extract_content(soup):
    div = soup.select_one('.section--detail .block--txt')
    if div:
        return clean_text(div.get_text(separator='\n'))
    return ""
 
# =========================
# 蜿門ｾ怜�逅�
# =========================
def fetch(url):
    while True:
        try:
            r = session.get(url, timeout=30)
            if r.status_code == 200:
                return r
            if r.status_code in (404, 410):
                return None
            print(f"Status {r.status_code} 竊� retry after 10s")
        except requests.exceptions.RequestException as e:
            print(f"Connection error 竊� retry after 10s\n{e}")
        #time.sleep(10)
 
# =========================
# 繝｡繧､繝ｳ繝ｫ繝ｼ繝�
# =========================
for i in range(50000, 70000): #70000
    url = f'https://ogurayui-official.com/news/detail/{i}'
    print(f'Processing {url}')
 
    response = fetch(url)
    #time.sleep(0.5)
 
    if response is None:
        continue
 
    soup = BeautifulSoup(response.content, 'html.parser')
 
    title = extract_title(soup)
    date = extract_date(soup)
    content = extract_content(soup)
 
    if title and content:
        with open('yui.txt', 'a', encoding='utf-8') as f:
            f.write(f"{url},{title},{date},{content}\n")
 
print("Done!")
 
