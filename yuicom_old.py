import re
import csv
import time
import random
import urllib3
import requests

from bs4 import BeautifulSoup
from collections import defaultdict
from urllib.parse import urlparse
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

urllib3.disable_warnings()

# Session
session = requests.Session()

retry_strategy = Retry(
    total=5,
    connect=5,
    read=5,
    backoff_factor=2,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["GET"]
)

adapter = HTTPAdapter(
    max_retries=retry_strategy,
    pool_connections=20,
    pool_maxsize=20
)

session.mount("http://", adapter)
session.mount("https://", adapter)
session.headers.update({
    "User-Agent": "Mozilla/5.0"
})

RETRY_COUNT = 5

# 同じ記事に対して何個のスナップショットまで試すか
# （1つ目のスナップショットが壊れている/本文が取れない場合に備える）
SNAPSHOT_TRY_COUNT = 3

SITE_PRIORITY = {
    "fc.ogurayui.net": 0,
    "www.yuis-company.jp": 1,
    "yuis-company.jp": 1,
    "yuicom.jp": 2
}

TARGETS = [
    ("fc.ogurayui.net", "https://fc.ogurayui.net/s/n59/news/detail/*"),
    ("yuis-company.jp", "https://www.yuis-company.jp/news/*"),
    ("yuicom.jp", "https://yuicom.jp/news/*"),
]

failed_rows = []

# GET
def get(url):
    for i in range(RETRY_COUNT):
        try:
            time.sleep(random.uniform(0.5, 1.5))
            r = session.get(
                url,
                timeout=60,
                verify=False
            )
            r.raise_for_status()
            return r
        except Exception as e:
            wait = random.random()
            print(f"[retry] {url} ({i+1}) {e} wait={wait:.1f}s")
            time.sleep(wait)
    return None

# HTML URL判定
def is_html_url(url):
    url = url.lower()
    ng_ext = (
        ".jpg", ".jpeg", ".png", ".gif", ".webp",
        ".svg", ".bmp", ".ico",
        ".pdf", ".zip",
        ".mp3", ".wav", ".m4a",
        ".mp4", ".mov", ".avi",
        ".css", ".js",
        ".json", ".xml",
        ".woff", ".woff2", ".ttf", ".eot"
    )
    path = url.split("?")[0]
    if path.endswith(ng_ext):
        return False
    return True

# URL正規化（重複排除用）
def normalize_url_key(url):
    p = urlparse(url)
    host = (p.hostname or "").lower()
    path = p.path or "/"
    if path != "/" and path.endswith("/"):
        path = path[:-1]
    return (host, path)

def dedupe_urls(urls):
    best = {}
    for u in urls:
        key = normalize_url_key(u)
        if key not in best:
            best[key] = u
            continue
        cur = best[key]
        cur_https = cur.startswith("https")
        new_https = u.startswith("https")
        if new_https and not cur_https:
            best[key] = u
        elif new_https == cur_https and len(u) < len(cur):
            best[key] = u
    return sorted(best.values())

# CDX
def get_cdx_urls(domain, pattern):
    cdx_url = (
        "https://web.archive.org/cdx/search/cdx"
        f"?url={pattern}"
        "&output=json"
        "&fl=original"
        "&filter=statuscode:200"
        "&collapse=urlkey"
    )
    r = get(cdx_url)
    if r is None:
        return []
    try:
        data = r.json()
        urls = []
        for row in data[1:]:
            url = row[0]
            if not is_html_url(url):
                continue

            # サイト別フィルタ
            if domain == "fc.ogurayui.net":
                if "/detail/" not in url:
                    continue
            elif domain == "yuis-company.jp":
                # 例: https://www.yuis-company.jp/news/2019/0815120000.html
                if not re.search(r"/news/\d{4}/\d+\.html?$", url):
                    continue
            elif domain == "yuicom.jp":
                # 例: https://yuicom.jp/news/11 （数字IDが必須、一覧ページ除外）
                if not re.search(r"/news/\d+/?$", url):
                    continue

            urls.append(url)
        return sorted(set(urls))
    except Exception:
        return []

# Snapshot取得（複数候補を取れるように変更）
def get_snapshots(url, limit=SNAPSHOT_TRY_COUNT):
    cdx_url = (
        "https://web.archive.org/cdx/search/cdx"
        f"?url={url}"
        "&output=json"
        "&fl=timestamp,original"
        "&filter=statuscode:200"
        f"&limit={limit}"
    )
    r = get(cdx_url)
    if r is None:
        return []
    try:
        data = r.json()
        if len(data) < 2:
            return []
        wburls = []
        for ts, orig in data[1:]:
            wburls.append(f"https://web.archive.org/web/{ts}/{orig}")
        return wburls
    except Exception:
        return []

# パース
def clean_text(x):
    return re.sub(r"\s+", " ", x or "").strip()

# yuis-company.jp のページに共通して出てくる
# ヘッダー/フッターの定型文（本文ではないので取り除く）
YUIS_BOILERPLATE_PATTERNS = [
    r"小倉\s*唯\s*オフィシャルファンクラブ.*?Copyright[^。]*",
    r"TEL[:：].*?(?=MAIL|$)",
    r"MAIL[:：]\s*info@[\w.]+",
    r"Copyright\s*Yui.?s.*",
]

# 本文を囲っていそうな候補セレクタ（サイトリニューアルに強くするため複数試す）
CONTENT_SELECTOR_CANDIDATES = [
    ("class", re.compile("news-more__cont")),
    ("class", re.compile("area__body")),
    ("class", re.compile("newsDetail")),
    ("class", re.compile("news-detail")),
    ("class", re.compile("article")),
    ("id", re.compile("main")),
]

def get_clean_body_text(soup):
    soup_copy = BeautifulSoup(str(soup), "html.parser")
    for tag_name in ("head", "script", "style", "nav", "header", "footer"):
        for tag in soup_copy.find_all(tag_name):
            tag.decompose()
    return soup_copy.get_text("\n", strip=True)

def find_date_near(text, anchor_index, window=60):
    date_re = r"\d{4}[./\-]\d{1,2}[./\-]\d{1,2}"
    if anchor_index is not None:
        after = text[anchor_index: anchor_index + window]
        m = re.search(date_re, after)
        if m:
            return m.group().replace("-", "/").replace(".", "/")
    m = re.search(date_re, text)
    if m:
        return m.group().replace("-", "/").replace(".", "/")
    return ""

def parse_site(html, url):
    soup = BeautifulSoup(html, "html.parser")
    title = ""
    date = ""
    content = ""
    # ------------------------------------------------
    # fc.ogurayui.net
    # ------------------------------------------------
    if "fc.ogurayui.net" in url:
        h5 = soup.find("h5")
        if h5:
            title = h5.get_text(" ", strip=True)
        d = soup.find("p", class_=re.compile("salesdate"))
        if d:
            date = d.get_text(" ", strip=True)
        c = soup.find("div", class_=re.compile("news-more__cont"))
        if c:
            content = c.get_text(" ", strip=True)
    # ------------------------------------------------
    # yuicom.jp
    # ------------------------------------------------
    elif "yuicom.jp" in url:
        h2 = soup.find("h2")
        if h2:
            title = h2.get_text(" ", strip=True)
        body = soup.select_one(".area__body")
        if body:
            content = body.get_text(" ", strip=True)
        full_text = get_clean_body_text(soup)
        anchor_idx = None
        if title:
            anchor_idx = full_text.find(title)
            if anchor_idx != -1:
                anchor_idx += len(title)
            else:
                anchor_idx = None
        date = find_date_near(full_text, anchor_idx)
    # ------------------------------------------------
    # yuis-company.jp
    # ------------------------------------------------
    else:
        if soup.title:
            raw_title = soup.title.get_text(strip=True)
            title = raw_title.split("｜")[0].split("|")[0].strip()
        if not title:
            h = soup.find(["h1", "h2"])
            if h:
                title = h.get_text(" ", strip=True)
        full_text = get_clean_body_text(soup)
        anchor_idx = None
        if title:
            anchor_idx = full_text.find(title)
            if anchor_idx != -1:
                anchor_idx += len(title)
            else:
                anchor_idx = None
        date = find_date_near(full_text, anchor_idx)

        # 本文抽出
        content_node = None
        for attr, pattern in CONTENT_SELECTOR_CANDIDATES:
            node = soup.find(attrs={attr: pattern})
            if node and len(node.get_text(strip=True)) > 30:
                content_node = node
                break
        if content_node:
            content = content_node.get_text(" ", strip=True)
        else:
            stripped = full_text
            for pat in YUIS_BOILERPLATE_PATTERNS:
                stripped = re.sub(pat, " ", stripped, flags=re.DOTALL)
            content = stripped
    return (
        clean_text(title),
        clean_text(date),
        clean_text(content)
    )

# 記事処理
def process(url):
    wburls = get_snapshots(url)
    if not wburls:
        failed_rows.append([
            url,
            "",
            "snapshot_not_found"
        ])
        return None

    last_reason = ""
    last_wburl = ""
    for wburl in wburls:
        r = get(wburl)
        if r is None:
            last_reason = "fetch_failed"
            last_wburl = wburl
            continue
        ctype = r.headers.get("Content-Type", "").lower()
        if "html" not in ctype:
            last_reason = f"non_html ({ctype})"
            last_wburl = wburl
            continue
        try:
            title, date, content = parse_site(r.text, url)
        except Exception as e:
            last_reason = str(e)
            last_wburl = wburl
            continue
        if not title and not content:
            last_reason = "empty_parse"
            last_wburl = wburl
            continue
        return (
            url,
            title,
            date,
            content,
            wburl
        )
    failed_rows.append([
        url,
        last_wburl,
        last_reason or "unknown_failure"
    ])
    return None

def main():
    all_rows = []
    site_urls = defaultdict(list)
    # URL収集
    for domain, pattern in TARGETS:
        print("\nCDX:", domain)
        urls = get_cdx_urls(domain, pattern)
        urls = dedupe_urls(urls)
        print("found", len(urls))
        site_urls[domain] = sorted(urls)
    # 優先順
    domains = sorted(
        site_urls.keys(),
        key=lambda x: SITE_PRIORITY.get(x, 99)
    )

    for domain in domains:
        print("\nPROCESS SITE:", domain)
        for i, url in enumerate(site_urls[domain], 1):
            print(i, "/", len(site_urls[domain]), url)
            row = process(url)
            if row:
                all_rows.append(row)
            else:
                print("skip")

    # 最終ソート
    def sort_key(r):
        host = urlparse(r[0]).hostname or ""
        return (
            SITE_PRIORITY.get(host, 99),
            r[0]
        )
    all_rows.sort(key=sort_key)

    # 成功
    with open(
            "fc_all_integrated.csv",
            "w",
            newline="",
            encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow([
            "url",
            "title",
            "date",
            "content",
            "archive_url"
        ])
        w.writerows(all_rows)

    # 失敗
    with open(
            "failed_urls.csv",
            "w",
            newline="",
            encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow([
            "original_url",
            "archive_url",
            "reason"
        ])
        w.writerows(failed_rows)

    print()
    print("SUCCESS =", len(all_rows))
    print("FAILED  =", len(failed_rows))

if __name__ == "__main__":
    main()
