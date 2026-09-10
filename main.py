from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
import time
import urllib.parse
import xml.etree.ElementTree as ET
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import requests
import uvicorn
​app = FastAPI(title="地區新聞 API", description="九龍灣、牛頭角、啟德當日新聞過濾服務")
​DISTRICT_KEYWORDS = {
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
​快取設定 (預設快取 3 分鐘)
​NEWS_CACHE = None
CACHE_TIME = 0
CACHE_DURATION = 180
​def is_today_hkt(pub_date_str: str) -> bool:
"""檢查新聞發布時間是否為香港時間今日 00:00 至目前為止"""
if not pub_date_str:
return True
try:
pub_dt = parsedate_to_datetime(pub_date_str)
# 轉換為香港時間 (UTC+8)
hkt_tz = timezone(timedelta(hours=8))
pub_hkt = pub_dt.astimezone(hkt_tz)
now_hkt = datetime.now(hkt_tz)
​# 計算今日 00:00:00 時間點
start_of_today = now_hkt.replace(
hour=0, minute=0, second=0, microsecond=0
)
​# 時間必須介乎今天 00:00 至當前時間（給予 10 分鐘寬限時間容許伺服器時差）
return start_of_today <= pub_hkt <= (now_hkt + timedelta(minutes=10))
except Exception:
return True
​def identify_source(title: str, link: str) -> str:
"""識別新聞來源媒體名稱，標示於卡片上"""
title_lower = title.lower()
link_lower = link.lower()
​if "stheadline" in link_lower or "星島" in title:
return "星島頭條"
if "hk01" in link_lower or "香港01" in title:
return "HK01"
if "news.gov.hk" in link_lower or "政府新聞" in title:
return "政府新聞網"
if "on.cc" in link_lower or "東網" in title or "東方" in title:
return "東方即時新聞"
​return "指定媒體"
​@app.get("/api/news")
def get_today_district_news(force_refresh: bool = False):
global NEWS_CACHE, CACHE_TIME
now = time.time()
​if not force_refresh and NEWS_CACHE and (now - CACHE_TIME < CACHE_DURATION):
return NEWS_CACHE
​# 搜尋語法限制在指定 4 大媒體網域 (site:...)
search_query = "(九龍灣 OR 牛頭角 OR 啟德) (site:stheadline.com OR site:hk01.com OR site:news.gov.hk OR site:on.cc)"
encoded_query = urllib.parse.quote(search_query)
rss_url = f"https://news.google.com/rss/search?q={encoded_query}&hl=zh-HK&gl=HK&ceid=HK:zh-Hant"
​headers = {
"User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
}
​try:
response = requests.get(rss_url, headers=headers, timeout=8)
response.raise_for_status()
except Exception as e:
if NEWS_CACHE:
return NEWS_CACHE
return {"status": "error", "message": str(e), "data": []}
​try:
root = ET.fromstring(response.content)
except Exception as e:
return {"status": "error", "message": f"XML 解析失敗: {str(e)}", "data": []}
​news_items = []
​for item in root.findall(".//item"):
title = item.findtext("title") or ""
link = item.findtext("link") or ""
pub_date = item.findtext("pubDate") or ""
​# 1. 時間過濾：僅保留今日 00:00 至登入當刻
if not is_today_hkt(pub_date):
continue
​# 2. 地理關鍵字比對
matched_districts = set()
matched_keywords = []
​for district, keywords in DISTRICT_KEYWORDS.items():
for kw in keywords:
if kw in title:
matched_districts.add(district)
matched_keywords.append(kw)
​if matched_districts:
source_name = identify_source(title, link)
news_items.append(
{
"title": title,
"link": link,
"pub_date": pub_date,
"source": source_name,
"districts": list(matched_districts),
"matched_keywords": matched_keywords,
}
)
​result = {"status": "success", "count": len(news_items), "data": news_items}
NEWS_CACHE = result
CACHE_TIME = now
return result
​@app.get("/", response_class=HTMLResponse)
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
<body class="bg-slate-100 min-h-screen p-4 font-sans">
<div class="max-w-md mx-auto">
<header class="flex justify-between items-center mb-3 bg-white p-4 rounded-2xl shadow-sm">
<div>
<h1 class="text-xl font-bold text-slate-800">九龍東新聞速報</h1>
<p class="text-xs text-slate-500">今日 00:00 起 · 4 大指定媒體</p>
</div>
<button onclick="loadNews(true)" class="bg-blue-600 hover:bg-blue-700 text-white text-xs px-3 py-2 rounded-xl transition flex items-center gap-1">
<span>重新整理</span>
</button>
</header>
​<div class="mb-3 px-1 flex flex-wrap gap-1.5 text-[11px] text-slate-500">
<span class="bg-slate-200/80 px-2 py-0.5 rounded-full">星島頭條</span>
<span class="bg-slate-200/80 px-2 py-0.5 rounded-full">HK01</span>
<span class="bg-slate-200/80 px-2 py-0.5 rounded-full">政府新聞網</span>
<span class="bg-slate-200/80 px-2 py-0.5 rounded-full">東方即時新聞</span>
</div>
​<div id="news-container" class="space-y-3">
<p class="text-center text-slate-400 py-8">新聞載入中...</p>
</div>
</div>
​<script>
function renderNews(data) {
const container = document.getElementById('news-container');
if (!data || data.length === 0) {
container.innerHTML = '<p class="text-center text-slate-400 py-8">今日 00:00 至目前無相關新聞</p>';
return;
}
container.innerHTML = data.map(item => <div class="bg-white p-4 rounded-2xl shadow-sm border border-slate-100 hover:shadow-md transition"> <div class="flex items-center justify-between mb-2"> <div class="flex gap-1.5"> ${item.districts.map(d =><span class="bg-blue-50 text-blue-600 text-[10px] font-semibold px-2 py-0.5 rounded-md">${d}</span>).join('')} </div> <span class="bg-amber-50 text-amber-700 text-[10px] font-medium px-2 py-0.5 rounded-md border border-amber-200/50">${item.source}</span> </div> <a href="${item.link}" target="_blank" class="block font-medium text-slate-800 hover:text-blue-600 leading-snug mb-2"> ${item.title} </a> <p class="text-[10px] text-slate-400">${item.pub_date}</p> </div> ).join('');
}
​async function loadNews(force = false) {
const container = document.getElementById('news-container');
​const localData = localStorage.getItem('district_news_v3');
if (localData && !force) {
renderNews(JSON.parse(localData));
} else {
container.innerHTML = '<p class="text-center text-slate-400 py-8">正在檢索今日 4 大媒體新聞...</p>';
}
​try {
const url = force ? '/api/news?force_refresh=true' : '/api/news';
const res = await fetch(url);
const result = await res.json();
​if (result.status === 'success' && result.data) {
localStorage.setItem('district_news_v3', JSON.stringify(result.data));
renderNews(result.data);
}
} catch (e) {
if (!localData) {
container.innerHTML = '<p class="text-center text-red-400 py-8">載入失敗，請檢查網路連線</p>';
}
}
}
​loadNews();
</script>
</body>
</html>
"""
​if name == "main":
uvicorn.run(app, host="0.0.0.0", port=8000)
