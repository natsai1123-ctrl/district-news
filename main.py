from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
import re
import urllib.parse
import xml.etree.ElementTree as ET
import difflib
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import requests
import uvicorn

app = FastAPI(title="地區新聞過濾服務")

# 香港時區 (UTC+8)
HKT = timezone(timedelta(hours=8))

TARGET_SOURCES = {
    "HK01": ["hk01.com", "香港01", "hk01"],
    "星島頭條": ["stheadline.com", "星島頭條", "星島日報", "stheadline"],
    "政府新聞網": ["news.gov.hk", "政府新聞網", "香港政府新聞網"],
    "東方即時新聞": ["on.cc", "東方即時", "東網", "東方日報"]
}

DISTRICT_KEYWORDS = [
    "九龍灣", "德福廣場", "淘大", "企業廣場", "零碳天地", "MegaBox", "坪石邨",
    "牛頭角", "彩盈邨", "彩福邨", "彩德邨", "安基苑", "玉蓮臺", "牛頭角下邨",
    "啟德", "啟德體育園", "啟德郵輪碼頭", "晴朗商場", "AIRSIDE", "雙子匯", "啟德河"
]


def is_today_hkt(pub_date_str: str) -> bool:
    if not pub_date_str:
        return False
    try:
        pub_dt = parsedate_to_datetime(pub_date_str).astimezone(HKT)
        now_hkt = datetime.now(HKT)
        today_0000 = now_hkt.replace(hour=0, minute=0, second=0, microsecond=0)
        return today_0000 <= pub_dt <= now_hkt
    except Exception:
        return True


def clean_title(title: str) -> str:
    """清理標題尾巴的媒體後綴"""
    return re.sub(r'\s*[-|｜]\s*[^||-]+$', '', title).strip()


def is_similar(t1: str, t2: str) -> bool:
    """使用 fuzzy match 檢查標題相似度，大於 55% 視為同一則新聞更新"""
    t1_compact = re.sub(r'\s+', '', t1)
    t2_compact = re.sub(r'\s+', '', t2)
    return difflib.SequenceMatcher(None, t1_compact, t2_compact).ratio() > 0.55


def match_source(title: str, link: str, source_text: str) -> str:
    combined = f"{title} {link} {source_text}".lower()
    for source_name, keywords in TARGET_SOURCES.items():
        if any(kw.lower() in combined for kw in keywords):
            return source_name
    return None


@app.get("/api/news")
def get_today_district_news():
    sites_query = " OR ".join([f"site:{k}" for k in ["stheadline.com", "hk01.com", "news.gov.hk", "hk.on.cc"]])
    search_query = f"(九龍灣 OR 牛頭角 OR 啟德) ({sites_query})"
    encoded_query = urllib.parse.quote(search_query)
    rss_url = f"https://news.google.com/rss/search?q={encoded_query}&hl=zh-HK&gl=HK&ceid=HK:zh-Hant"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    try:
        response = requests.get(rss_url, headers=headers, timeout=10)
        response.raise_for_status()
    except requests.RequestException as e:
        return {"status": "error", "message": str(e), "data": {}}

    root = ET.fromstring(response.content)
    
    categorized_data = {
        "HK01": [],
        "星島頭條": [],
        "政府新聞網": [],
        "東方即時新聞": []
    }

    for item in root.findall(".//item"):
        title = item.find("title").text if item.find("title") is not None else ""
        link = item.find("link").text if item.find("link") is not None else ""
        pub_date = item.find("pubDate").text if item.find("pubDate") is not None else ""
        source_elem = item.find("source")
        source_text = source_elem.text if source_elem is not None else ""

        if not is_today_hkt(pub_date):
            continue

        source_name = match_source(title, link, source_text)
        if not source_name:
            continue

        matched_kw = [kw for kw in DISTRICT_KEYWORDS if kw in title]
        if not matched_kw:
            continue

        c_title = clean_title(title)
        
        try:
            pub_dt = parsedate_to_datetime(pub_date)
            formatted_time = pub_dt.astimezone(HKT).strftime("%m-%d %H:%M")
        except Exception:
            pub_dt = datetime.min.replace(tzinfo=timezone.utc)
            formatted_time = pub_date

        news_entry = {
            "title": title,
            "clean_title": c_title,
            "link": link,
            "pub_date": formatted_time,
            "pub_dt": pub_dt,
            "keywords": matched_kw
        }

        # 模糊比對去重邏輯 (門檻 > 55%)
        is_duplicate = False
        target_list = categorized_data[source_name]
        
        for i, existing_entry in enumerate(target_list):
            if is_similar(c_title, existing_entry["clean_title"]):
                is_duplicate = True
                # 若為同一新聞，時間較新者覆蓋；若時間相同，保留標題較長者
                if pub_dt > existing_entry["pub_dt"]:
                    target_list[i] = news_entry
                elif pub_dt == existing_entry["pub_dt"]:
                    if len(title) > len(existing_entry["title"]):
                        target_list[i] = news_entry
                break
                
        if not is_duplicate:
            target_list.append(news_entry)

    # 按時間排序並清理內部欄位
    for src in categorized_data:
        categorized_data[src].sort(key=lambda x: x["pub_dt"], reverse=True)
        for item in categorized_data[src]:
            del item["pub_dt"]
            del item["clean_title"]

    return {"status": "success", "data": categorized_data}


@app.get("/", response_class=HTMLResponse)
def home_page():
    return """
    <!DOCTYPE html>
    <html lang="zh-HK">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>地區新聞速報</title>
        <script src="https://cdn.tailwindcss.com"></script>
    </head>
    <body class="bg-slate-100 min-h-screen p-3 md:p-6 font-sans">
        <div class="max-w-2xl mx-auto">
            <header class="flex justify-between items-center mb-4 bg-white p-4 rounded-2xl shadow-sm">
                <div>
                    <h1 class="text-xl font-bold text-slate-800">地區新聞速報</h1>
                    <p class="text-xs text-slate-500">今日 00:00 至今 · 智慧去重版 (>55% 相似度)</p>
                </div>
                <button onclick="loadNews()" class="bg-blue-600 hover:bg-blue-700 text-white text-xs px-3 py-2 rounded-xl transition">
                    重新整理
                </button>
            </header>

            <div id="content" class="space-y-6">
                <p class="text-center text-slate-400 py-8">新聞更新中...</p>
            </div>
        </div>

        <script>
            const SOURCES = [
                { id: "HK01", name: "HK01", icon: "📰", color: "border-red-500" },
                { id: "星島頭條", name: "星島頭條", icon: "🗞️", color: "border-blue-500" },
                { id: "政府新聞網", name: "政府新聞網", icon: "🏛️", color: "border-emerald-500" },
                { id: "東方即時新聞", name: "東方即時新聞", icon: "⚡", color: "border-amber-500" }
            ];

            async function loadNews() {
                const container = document.getElementById('content');
                container.innerHTML = '<p class="text-center text-slate-400 py-8">正在檢索各大媒體今日新聞...</p>';
                
                try {
                    const res = await fetch('/api/news');
                    const result = await res.json();
                    
                    if (result.status !== 'success') {
                        container.innerHTML = '<p class="text-center text-red-400 py-8">載入失敗</p>';
                        return;
                    }

                    const data = result.data;
                    let html = '';

                    SOURCES.forEach(src => {
                        const items = data[src.id] || [];
                        html += `
                            <div class="bg-white rounded-2xl p-4 shadow-sm border-l-4 ${src.color}">
                                <div class="flex justify-between items-center mb-3 border-b border-slate-100 pb-2">
                                    <h2 class="font-bold text-slate-800 flex items-center gap-1.5">
                                        <span>${src.icon}</span> ${src.name}
                                    </h2>
                                    <span class="text-xs bg-slate-100 text-slate-600 px-2 py-0.5 rounded-full font-semibold">
                                        ${items.length} 則
                                    </span>
                                </div>
                                ${items.length === 0 ? 
                                    '<p class="text-xs text-slate-400 py-3 text-center">今日暫無相關新聞</p>' : 
                                    '<div class="space-y-3">' + items.map(item => `
                                        <div class="p-2.5 rounded-xl hover:bg-slate-50 transition border border-slate-50">
                                            <a href="${item.link}" target="_blank" class="block font-medium text-slate-800 hover:text-blue-600 text-sm leading-snug mb-1.5">
                                                ${item.title}
                                            </a>
                                            <div class="flex justify-between items-center text-[10px] text-slate-400">
                                                <span>關鍵字: ${item.keywords.join(', ')}</span>
                                                <span class="bg-slate-100 px-1.5 py-0.5 rounded">${item.pub_date}</span>
                                            </div>
                                        </div>
                                    `).join('') + '</div>'
                                }
                            </div>
                        `;
                    });

                    container.innerHTML = html;
                } catch (e) {
                    container.innerHTML = '<p class="text-center text-red-400 py-8">載入異常，請檢查網路</p>';
                }
            }

            loadNews();
        </script>
    </body>
    </html>
    """

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
