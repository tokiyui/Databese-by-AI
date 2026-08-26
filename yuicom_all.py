import re
import csv
import time
import random
import json
import urllib3
import requests

from bs4 import BeautifulSoup
from collections import defaultdict
from urllib.parse import urlparse, urlunparse, quote
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


urllib3.disable_warnings()


# ======================================================
# Session
# ======================================================

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


SITE_PRIORITY = {
    "fc.ogurayui.net": 0,
    "www.yuis-company.jp": 1,
    "yuis-company.jp": 1,
    "yuicom.jp": 2
}


TARGETS = [
    (
        "fc.ogurayui.net",
        "https://fc.ogurayui.net/s/n59/news/detail/*"
    ),

    (
        "yuis-company.jp",
        "https://www.yuis-company.jp/news/*"
    ),

    (
        "yuicom.jp",
        "https://yuicom.jp/news/*"
    ),
]


failed_rows = []


# ======================================================
# GET
# ======================================================

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

            wait = random.uniform(0.5, 2.0)

            print(
                f"[retry] {url} "
                f"({i + 1}/{RETRY_COUNT}) "
                f"{e}"
            )

            time.sleep(wait)

    return None


# ======================================================
# URL正規化
#
# URLを勝手に変更しない。
#
# 特に
#
# https://example.com/news/123?ima=5555
#
# の ?ima=5555 を削除しない。
# ======================================================

def normalize_url(url):

    p = urlparse(url)

    return urlunparse((
        p.scheme,
        p.netloc,
        p.path,
        p.params,
        p.query,
        p.fragment
    ))


# ======================================================
# HTML URL判定
# ======================================================

def is_html_url(url):

    path = urlparse(url).path.lower()

    ng_ext = (
        ".jpg", ".jpeg", ".png", ".gif", ".webp",
        ".svg", ".bmp", ".ico",
        ".pdf", ".zip",
        ".mp3", ".wav", ".m4a",
        ".mp4", ".mov", ".avi",
        ".css", ".js", ".json", ".xml",
        ".woff", ".woff2", ".ttf", ".eot"
    )

    return not path.endswith(ng_ext)


# ======================================================
# CDX
#
# CDXから返ってきた original URL を使用。
#
# URLの ?以降も保持する。
#
# 例:
#
# https://fc.ogurayui.net/s/n59/news/detail/10140?ima=5555
#
# はそのままURLとして保持。
# ======================================================

def get_cdx_urls(domain, pattern):

    cdx_url = (
        "https://web.archive.org/cdx/search/cdx"
        f"?url={quote(pattern, safe='')}"
        "&output=json"
        "&fl=original"
        "&filter=statuscode:200"
        "&filter=mimetype:text/html"
        "&collapse=urlkey"
    )

    r = get(cdx_url)

    if r is None:
        return []

    try:

        data = r.json()

        urls = set()

        for row in data[1:]:

            if not row:
                continue

            # CDXのoriginal URL
            url = row[0]

            if not is_html_url(url):
                continue

            path = urlparse(url).path

            # ------------------------------------------
            # fc.ogurayui.net
            # ------------------------------------------

            if domain == "fc.ogurayui.net":

                if "/detail/" not in path:
                    continue

            # ------------------------------------------
            # yuis-company.jp
            # ------------------------------------------

            elif domain == "yuis-company.jp":

                if "/news/" not in path:
                    continue

            # ------------------------------------------
            # yuicom.jp
            #
            # 月別URLなども含めて
            # /news/以下をすべて対象にする
            # ------------------------------------------

            elif domain == "yuicom.jp":

                if not path.startswith("/news/") and path != "/news":
                    continue

            # ------------------------------------------
            # URLを変更せず保持
            # ------------------------------------------

            urls.add(
                normalize_url(url)
            )

        return sorted(urls)

    except Exception as e:

        print("[CDX ERROR]", e)

        return []


# ======================================================
# Snapshot
#
# URL完全一致でCDX検索
#
# ?ima=5555 も検索対象に含める。
# ======================================================

def get_snapshot(url):

    cdx_url = (
        "https://web.archive.org/cdx/search/cdx"
        f"?url={quote(url, safe='')}"
        "&output=json"
        "&fl=timestamp,original,mimetype,statuscode"
        "&filter=statuscode:200"
        "&filter=mimetype:text/html"
        "&limit=10"
        "&filter=!mimetype:warc/revisit"
    )

    r = get(cdx_url)

    if r is None:
        return []

    try:

        data = r.json()

        result = []

        for row in data[1:]:

            if len(row) < 4:
                continue

            ts, orig, mime, status = row

            if status != "200":
                continue

            if "html" not in mime.lower():
                continue

            result.append(
                f"https://web.archive.org/web/{ts}/{orig}"
            )

        return result

    except Exception:

        return []


# ======================================================
# Text
# ======================================================

def clean_text(text):

    if not text:
        return ""

    text = text.replace("\xa0", " ")

    return re.sub(
        r"\s+",
        " ",
        text
    ).strip()


# ======================================================
# HTMLから自然な文章だけを取得
# ======================================================

def element_text(tag):

    if tag is None:
        return ""

    for x in tag.find_all([
        "script",
        "style",
        "noscript",
        "svg",
        "template"
    ]):
        x.decompose()

    return clean_text(
        tag.get_text(
            " ",
            strip=True
        )
    )


# ======================================================
# タイトル候補
# ======================================================

def title_candidates(soup):

    candidates = []

    def add(text, score):

        text = clean_text(text)

        if not text:
            return

        if len(text) < 2:
            return

        if len(text) > 500:
            return

        candidates.append(
            (score, text)
        )

    # ------------------------------------------
    # meta
    # ------------------------------------------

    for prop in [
        "og:title",
        "twitter:title",
        "title"
    ]:

        tag = soup.find(
            "meta",
            attrs={
                "property": prop
            }
        )

        if tag:
            add(
                tag.get("content"),
                100
            )

        tag = soup.find(
            "meta",
            attrs={
                "name": prop
            }
        )

        if tag:
            add(
                tag.get("content"),
                95
            )

    # ------------------------------------------
    # heading
    # ------------------------------------------

    for tagname, score in [
        ("h1", 100),
        ("h2", 90),
        ("h3", 75),
        ("h4", 60),
        ("h5", 50),
        ("h6", 40)
    ]:

        for tag in soup.find_all(tagname):

            add(
                tag.get_text(
                    " ",
                    strip=True
                ),
                score
            )

    # ------------------------------------------
    # title
    # ------------------------------------------

    if soup.title:

        add(
            soup.title.get_text(
                " ",
                strip=True
            ),
            70
        )

    # ------------------------------------------
    # class / id
    # ------------------------------------------

    keywords = re.compile(
        r"(title|ttl|headline|subject|"
        r"news-title|article-title|entry-title)",
        re.I
    )

    for tag in soup.find_all(
        attrs={
            "class": keywords
        }
    ):

        add(
            tag.get_text(
                " ",
                strip=True
            ),
            65
        )

    # ------------------------------------------
    # JSON-LD
    # ------------------------------------------

    for script in soup.find_all(
        "script",
        type=re.compile(
            r"ld\+json",
            re.I
        )
    ):

        try:

            data = json.loads(
                script.string or script.get_text()
            )

            stack = (
                data
                if isinstance(data, list)
                else [data]
            )

            for obj in stack:

                if isinstance(obj, dict):

                    for key in [
                        "headline",
                        "name"
                    ]:

                        if key in obj:

                            add(
                                obj[key],
                                90
                            )

        except Exception:
            pass

    return candidates


# ======================================================
# タイトル決定
# ======================================================

def extract_title(soup):

    candidates = title_candidates(soup)

    if not candidates:
        return ""

    def final_score(item):

        score, text = item

        if len(text) > 150:
            score -= 30

        if len(text) < 3:
            score -= 20

        if re.fullmatch(
            r"\d{4}[./-]\d{1,2}[./-]\d{1,2}",
            text
        ):
            score -= 50

        return score

    return max(
        candidates,
        key=final_score
    )[1]


# ======================================================
# 日付抽出
# ======================================================

DATE_PATTERNS = [

    r"(20\d{2})[./-](\d{1,2})[./-](\d{1,2})",

    r"(20\d{2})年\s*(\d{1,2})月\s*(\d{1,2})日",

    r"(20\d{2})年\s*(\d{1,2})月",
]


def normalize_date(text):

    text = clean_text(text)

    for pattern in DATE_PATTERNS:

        m = re.search(
            pattern,
            text
        )

        if not m:
            continue

        groups = m.groups()

        if len(groups) == 3:

            return (
                f"{groups[0]}/"
                f"{int(groups[1]):02d}/"
                f"{int(groups[2]):02d}"
            )

        if len(groups) == 2:

            return (
                f"{groups[0]}/"
                f"{int(groups[1]):02d}"
            )

    return ""


# ======================================================
# 日付候補
# ======================================================

def date_candidates(soup):

    candidates = []

    def add(text, score):

        date = normalize_date(text)

        if date:
            candidates.append(
                (score, date)
            )

    # ------------------------------------------
    # time
    # ------------------------------------------

    for tag in soup.find_all("time"):

        add(
            tag.get("datetime"),
            120
        )

        add(
            tag.get_text(
                " ",
                strip=True
            ),
            110
        )

    # ------------------------------------------
    # meta
    # ------------------------------------------

    meta_names = [
        "article:published_time",
        "article:modified_time",
        "date",
        "datepublished",
        "datePublished",
        "pubdate",
        "publishdate",
        "DC.date",
        "DC.Date"
    ]

    for name in meta_names:

        for attr in [
            "property",
            "name",
            "itemprop"
        ]:

            tag = soup.find(
                "meta",
                attrs={
                    attr: name
                }
            )

            if tag:

                add(
                    tag.get("content"),
                    115
                )

    # ------------------------------------------
    # JSON-LD
    # ------------------------------------------

    for script in soup.find_all(
        "script",
        type=re.compile(
            r"ld\+json",
            re.I
        )
    ):

        try:

            data = json.loads(
                script.string or script.get_text()
            )

            objects = (
                data
                if isinstance(data, list)
                else [data]
            )

            for obj in objects:

                if not isinstance(obj, dict):
                    continue

                for key in [
                    "datePublished",
                    "dateCreated",
                    "dateModified",
                    "uploadDate"
                ]:

                    if key in obj:

                        add(
                            str(obj[key]),
                            120
                        )

        except Exception:
            pass

    # ------------------------------------------
    # class / id
    # ------------------------------------------

    for tag in soup.find_all(
        attrs={
            "class": re.compile(
                r"(date|datetime|published|"
                r"publish|posted|released)",
                re.I
            )
        }
    ):

        add(
            tag.get_text(
                " ",
                strip=True
            ),
            100
        )

    # ------------------------------------------
    # ページ全体
    # ------------------------------------------

    text = soup.get_text(
        " ",
        strip=True
    )

    add(
        text,
        30
    )

    return candidates


# ======================================================
# 日付決定
# ======================================================

def extract_date(soup):

    candidates = date_candidates(soup)

    if not candidates:
        return ""

    return max(
        candidates,
        key=lambda x: x[0]
    )[1]


# ======================================================
# 本文候補
# ======================================================

def content_candidates(soup):

    candidates = []

    soup2 = BeautifulSoup(
        str(soup),
        "html.parser"
    )

    for tag in soup2.find_all([
        "script",
        "style",
        "noscript",
        "svg",
        "template",
        "nav",
        "header",
        "footer",
        "form"
    ]):
        tag.decompose()

    selectors = [

        "article",

        "main",

        "[role='main']",

        ".article",
        ".article-body",
        ".article__body",
        ".article-content",
        ".article__content",

        ".entry",
        ".entry-content",
        ".entry__content",

        ".news",
        ".news-body",
        ".news__body",
        ".news-detail",
        ".news-detail__body",
        ".news-more__cont",

        ".content",
        ".content-body",
        ".content__body",
        ".contents",
        ".contents-body",

        ".area__body",
        ".area-body",

        ".post",
        ".post-content",

        ".main",
        "#main",
        "#content",
        "#contents"
    ]

    for selector in selectors:

        for tag in soup2.select(selector):

            text = element_text(tag)

            if len(text) >= 30:

                candidates.append(
                    (len(text), text)
                )

    keyword = re.compile(
        r"(article|content|contents|"
        r"news|entry|post|body|main|detail)",
        re.I
    )

    for tag in soup2.find_all(
        attrs={
            "class": keyword
        }
    ):

        text = element_text(tag)

        if len(text) >= 30:

            candidates.append(
                (len(text), text)
            )

    for tag in soup2.find_all(
        id=keyword
    ):

        text = element_text(tag)

        if len(text) >= 30:

            candidates.append(
                (len(text), text)
            )

    paragraphs = []

    for p in soup2.find_all("p"):

        text = clean_text(
            p.get_text(
                " ",
                strip=True
            )
        )

        if len(text) >= 5:
            paragraphs.append(text)

    if paragraphs:

        text = clean_text(
            " ".join(paragraphs)
        )

        candidates.append(
            (len(text) + 50, text)
        )

    if soup2.body:

        text = element_text(
            soup2.body
        )

        if text:

            candidates.append(
                (len(text), text)
            )

    return candidates


# ======================================================
# 本文決定
# ======================================================

def extract_content(soup, title=""):

    candidates = content_candidates(soup)

    if not candidates:
        return ""

    filtered = []

    for score, text in candidates:

        if len(text) < 30:
            continue

        if title and text == title:
            continue

        filtered.append(
            (score, text)
        )

    if not filtered:
        return ""

    def score(item):

        length, text = item

        s = length

        if length > 20000:
            s -= (length - 20000) * 0.5

        sentence_count = len(
            re.findall(
                r"[。！？.!?]",
                text
            )
        )

        s += min(
            sentence_count * 20,
            500
        )

        return s

    return max(
        filtered,
        key=score
    )[1]


# ======================================================
# JSON-LD本文
# ======================================================

def extract_jsonld_content(soup):

    candidates = []

    for script in soup.find_all(
        "script",
        type=re.compile(
            r"ld\+json",
            re.I
        )
    ):

        try:

            data = json.loads(
                script.string or script.get_text()
            )

            objects = (
                data
                if isinstance(data, list)
                else [data]
            )

            for obj in objects:

                if not isinstance(obj, dict):
                    continue

                for key in [
                    "articleBody",
                    "description"
                ]:

                    value = obj.get(key)

                    if isinstance(
                        value,
                        str
                    ):

                        value = clean_text(
                            value
                        )

                        if len(value) >= 30:

                            candidates.append(
                                value
                            )

        except Exception:
            pass

    if not candidates:
        return ""

    return max(
        candidates,
        key=len
    )


# ======================================================
# 総合パース
# ======================================================

def parse_site(html, url):

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    title = extract_title(
        soup
    )

    date = extract_date(
        soup
    )

    content = extract_content(
        soup,
        title
    )

    jsonld_content = extract_jsonld_content(
        soup
    )

    if len(jsonld_content) > len(content):
        content = jsonld_content

    return (
        clean_text(title),
        clean_text(date),
        clean_text(content)
    )


# ======================================================
# 記事処理
# ======================================================

def process(url):

    # ------------------------------------------
    # ここでURLを変更しない
    # ------------------------------------------

    snapshots = get_snapshot(
        url
    )

    if not snapshots:

        failed_rows.append([
            url,
            "",
            "snapshot_not_found"
        ])

        return None

    best = None
    best_score = -1

    for wburl in snapshots:

        r = get(wburl)

        if r is None:
            continue

        ctype = r.headers.get(
            "Content-Type",
            ""
        ).lower()

        if "html" not in ctype:
            continue

        try:

            title, date, content = parse_site(
                r.text,
                url
            )

            score = 0

            if title:
                score += 100

            if date:
                score += 50

            if content:
                score += min(
                    len(content) / 100,
                    100
                )

            low = r.text.lower()

            if (
                "404 not found" in low
                or "page not found" in low
            ):
                score -= 200

            if score > best_score:

                best_score = score

                best = (
                    url,
                    title,
                    date,
                    content,
                    wburl
                )

            if (
                title
                and date
                and len(content) >= 100
            ):
                break

        except Exception:
            continue

    if best is not None:

        return best

    failed_rows.append([
        url,
        snapshots[0],
        "parse_failed"
    ])

    return None


# ======================================================
# Main
# ======================================================

def main():

    all_rows = []

    site_urls = defaultdict(list)

    # ==================================================
    # URL収集
    # ==================================================

    for domain, pattern in TARGETS:

        print(
            "\nCDX:",
            domain
        )

        urls = get_cdx_urls(
            domain,
            pattern
        )

        print(
            "found",
            len(urls)
        )

        site_urls[domain] = sorted(
            urls
        )

    # ==================================================
    # 優先順
    # ==================================================

    domains = sorted(
        site_urls.keys(),
        key=lambda x:
            SITE_PRIORITY.get(
                x,
                99
            )
    )

    # ==================================================
    # 処理
    # ==================================================

    for domain in domains:

        print(
            "\nPROCESS SITE:",
            domain
        )

        for i, url in enumerate(
            site_urls[domain],
            1
        ):

            print(
                i,
                "/",
                len(site_urls[domain]),
                url
            )

            row = process(url)

            if row:
                all_rows.append(row)
            else:
                print("skip")

    # ==================================================
    # 重複除去
    #
    # クエリ付きURLとクエリなしURLを別URLとして扱う。
    # ==================================================

    unique = {}

    for row in all_rows:

        url = normalize_url(
            row[0]
        )

        if url not in unique:

            unique[url] = row

        else:

            old = unique[url]

            old_score = (
                bool(old[1]) * 100
                + bool(old[2]) * 50
                + len(old[3])
            )

            new_score = (
                bool(row[1]) * 100
                + bool(row[2]) * 50
                + len(row[3])
            )

            if new_score > old_score:
                unique[url] = row

    all_rows = list(
        unique.values()
    )

    # ==================================================
    # 最終ソート
    # ==================================================

    def sort_key(r):

        domain = urlparse(
            r[0]
        ).netloc.lower()

        domain = domain.split(":")[0]

        return (
            SITE_PRIORITY.get(
                domain,
                99
            ),
            r[0]
        )

    all_rows.sort(
        key=sort_key
    )

    # ==================================================
    # CSV
    # ==================================================

    with open(
        "fc_all_integrated.csv",
        "w",
        newline="",
        encoding="utf-8-sig"
    ) as f:

        w = csv.writer(f)

        w.writerow([
            "url",
            "title",
            "date",
            "content",
            "archive_url"
        ])

        w.writerows(
            all_rows
        )

    # ==================================================
    # Failed
    # ==================================================

    with open(
        "failed_urls.csv",
        "w",
        newline="",
        encoding="utf-8-sig"
    ) as f:

        w = csv.writer(f)

        w.writerow([
            "original_url",
            "archive_url",
            "reason"
        ])

        w.writerows(
            failed_rows
        )

    print()
    print(
        "SUCCESS =",
        len(all_rows)
    )
    print(
        "FAILED  =",
        len(failed_rows)
    )


if __name__ == "__main__":
    main()
