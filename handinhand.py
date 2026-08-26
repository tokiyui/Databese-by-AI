import requests
from bs4 import BeautifulSoup
import csv
import re
import time

BASE_URL = "https://ishiharakaori-fc.com/news/?id={}"

headers = {
    "User-Agent": "Mozilla/5.0"
}

rows = []

for i in range(1, 601):
    url = BASE_URL.format(i)

    try:
        r = requests.get(url, headers=headers, timeout=20)
        r.raise_for_status()

        soup = BeautifulSoup(r.content, "html.parser")

        # 記事ページの要素
        date_tag = soup.select_one(".details__date")
        title_tag = soup.select_one(".details__title")
        content_tag = soup.select_one(".details__content.aem-post")

        # 記事が存在しない場合
        if not date_tag or not title_tag or not content_tag:
            print(f"{i}: 存在しない")
            continue

        date = date_tag.get_text(strip=True)
        title = title_tag.get_text(" ", strip=True)

        # 本文中の画像・不要な要素を削除
        for tag in content_tag.select("img"):
            tag.decompose()

        # HTMLタグを除去し、改行を入れずに取得
        body = content_tag.get_text(" ", strip=True)

        # 空白を整理
        body = re.sub(r"\s+", " ", body).strip()

        rows.append([
            url,
            date,
            title,
            body
        ])

        print(f"{i}: {date} {title}")

    except requests.RequestException as e:
        print(f"{i}: 通信エラー {e}")

    except Exception as e:
        print(f"{i}: エラー {e}")

    time.sleep(0.2)


# CSV保存
with open(
    "ishiharakaori_news.csv",
    "w",
    newline="",
    encoding="utf-8-sig"
) as f:
    writer = csv.writer(f)
    writer.writerow(["URL", "更新日", "タイトル", "本文"])
    writer.writerows(rows)

print(f"\n取得完了: {len(rows)}件")
