from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import time
import urllib.parse
import xml.etree.ElementTree as ET
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import requests
import uvicorn

app = FastAPI(title="地區新聞 API", description="九龍灣、牛頭角、啟德當日新聞過濾服務")

DISTRICT_KEYWORDS = {
    "九龍灣": ["九龍灣", "德福廣場", "淘大", "企業廣場", "零碳天地", "MegaBox", "坪石邨"],
    "牛頭角": ["牛頭角", "彩盈邨", "彩福邨", "彩德邨", "安基苑", "玉蓮臺", "牛頭角下邨"],
    "啟德": [
        "啟德",
        "啟德體育園",
        "啟德郵輪碼頭",
        "晴朗商場",
        "AIRSIDE",
        "雙子匯",
        "啟德河",
    ],
}

# --- 後端快取設定 (預設快取 5 分鐘 / 300 秒) ---
NEWS_CACHE = None
CACHE_TIME = 0
CACHE_DURATION = 300  


def is_within_24_hours(pub_date_str: str) -> bool:
    if not pub_date_str:
        return True
    try:
        pub_dt = parsedate_to_datetime(pub_date_str)
        now_utc = datetime.now(timezone.utc)
        diff_seconds = (now_utc - pub_dt).total_seconds()
        return -3600 <= diff_seconds <= 108000
    except Exception:
        return True


@app.get("/api/news")
def get_today_district_news(force_refresh: bool = False):
    global NEWS_CACHE, CACHE_TIME
    now = time.time()

    # 如果有快取且未過期，直接回傳（速度提高 100 倍）
    if not force_refresh and NEWS_CACHE and (now - CACHE_TIME < CACHE_DURATION):
        return NEWS_CACHE

    search_query = "九龍灣 OR 牛頭角 OR 啟德 when:1d"
    encoded_query = urllib.parse.quote(search_query)
    rss_url = f"https://news.google.com/rss/search?q={encoded_query}&hl=zh-HK&gl=HK&ceid=HK:zh-Hant"

    headers = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
    }

    try:
        response = requests.get(rss_url, headers=headers, timeout=5)
        response.raise_for_status()
    except Exception as e:
        # 如果失敗且有舊快取，優先使用舊快取
        if NEWS_CACHE:
            return NEWS_CACHE
        return {"status": "error", "message": str(e), "data": []}

    try:
        root = ET.fromstring(response.content)
    except Exception as e:
        return {"status": "error", "message": f"XML 解析失敗: {str(e)}", "data": []}

    news_items = []

    for item in root.findall(".//item"):
        title = item.findtext("title") or ""
        link = item.findtext("link") or ""
        pub_date = item.findtext("pubDate") or ""

        if not is_within_24_hours(pub_date):
            continue

        matched_districts = set()
        matched_keywords = []

        for district, keywords in DISTRICT_KEYWORDS.items():
            for kw in keywords:
                if kw in title:
                    matched_districts.add(district)
                    matched_keywords.append(kw)

        if matched_districts:
            news_items.append(
                {
                    "title": title,
                    "link": link,
                    "pub_date": pub_date,
                    "districts": list(matched_districts),
                    "matched_keywords": matched_keywords,
                }
            )

    result = {"status": "success", "count": len(news_items), "data": news_items}
    NEWS_CACHE = result
    CACHE_TIME = now
    return result


@app.get("/", response_class=HTMLResponse)
def home_page():
    return """
    <!DOCTYPE html>
    <html lang="zh-HK">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>地區新聞 App</title>
        <script src="https://cdn.tailwindcss.com"></script>
    </head>
    <body class="bg-slate-100 min-h-screen p-4 font-sans">
        <div class="max-w-md mx-auto">
            <header class="flex justify-between items-center mb-5 bg-white p-4 rounded-2xl shadow-sm">
                <div>
                    <h1 class="text-xl font-bold text-slate-800">九龍東新聞速報</h1>
                    <p class="text-xs text-slate-500">九龍灣 · 牛頭角 · 啟德</p>
                </div>
                <button onclick="loadNews(true)" class="bg-blue-600 hover:bg-blue-700 text-white text-xs px-3 py-2 rounded-xl transition flex items-center gap-1">
                    <span>強行更新</span>
                </button>
            </header>

            <div id="news-container" class="space-y-3">
                <p class="text-center text-slate-400 py-8">新聞載入中...</p>
            </div>
        </div>

        <script>
            function renderNews(data) {
                const container = document.getElementById('news-container');
                if (!data || data.length === 0) {
                    container.innerHTML = '<p class="text-center text-slate-400 py-8">過去 24 小時無相關新聞</p>';
                    return;
                }
                container.innerHTML = data.map(item => `
                    <div class="bg-white p-4 rounded-2xl shadow-sm border border-slate-100 hover:shadow-md transition">
                        <div class="flex gap-1.5 mb-2">
                            ${item.districts.map(d => `<span class="bg-blue-50 text-blue-600 text-[10px] font-semibold px-2 py-0.5 rounded-md">${d}</span>`).join('')}
                        </div>
                        <a href="${item.link}" target="_blank" class="block font-medium text-slate-800 hover:text-blue-600 leading-snug mb-3">
                            ${item.title}
                        </a>
                        <p class="text-[10px] text-slate-400">${item.pub_date}</p>
                    </div>
                `).join('');
            }

            async function loadNews(force = false) {
                const container = document.getElementById('news-container');
                
                // 1. 優先渲染本地暫存，實現「0 秒秒開」
                const localData = localStorage.getItem('district_news');
                if (localData && !force) {
                    renderNews(JSON.parse(localData));
                } else {
                    container.innerHTML = '<p class="text-center text-slate-400 py-8">更新最新新聞中...</p>';
                }

                try {
                    const url = force ? '/api/news?force_refresh=true' : '/api/news';
                    const res = await fetch(url);
                    const result = await res.json();
                    
                    if (result.status === 'success' && result.data) {
                        localStorage.setItem('district_news', JSON.stringify(result.data));
                        renderNews(result.data);
                    }
                } catch (e) {
                    if (!localData) {
                        container.innerHTML = '<p class="text-center text-red-400 py-8">載入失敗，請檢查網路連線</p>';
                    }
                }
            }

            loadNews();
        </script>
    </body>
    </html>
    """


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
