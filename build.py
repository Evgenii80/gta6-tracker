#!/usr/bin/env python3
"""
Сборщик контента для сайта GTA 6 tracker.
1. Тянет новости из RSS-лент по ключевым словам (GTA 6 / Grand Theft Auto VI).
2. Пишет свежие в data/news.json.
3. Вставляет блок новостей в index.html между маркерами NEWS:START/NEWS:END.

Запуск: python3 build.py
Стандартная библиотека, без зависимостей.
"""
import json
import re
import html as html_mod
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent

# --- Источники: RSS-ленты, не требующие ключей ---
FEEDS = [
    "https://www.gamespot.com/feeds/game-news/",
    "https://www.eurogamer.net/feed",
    "https://www.videogameschronicle.com/feed/",
]

# --- Ключевые слова: пост с любым из них считаем новостью про GTA 6 ---
KEYWORDS = re.compile(
    r"\b(gta\s?6|gta\s?vi|grand theft auto (6|vi))\b", re.IGNORECASE
)

# --- Подтип «гайд/секрет»: заголовки-как-пройти, где-найти и т.п. ---
GUIDE_KEYWORDS = re.compile(
    r"\b(how to|how long|where to|where (is|are|find)|guide|walkthrough|tips?|secret|secrets|easter egg|hidden|collectible|\u043a\u0430\u043a \u043f\u0440\u043e\u0439\u0442\u0438|\u0433\u0434\u0435 \u043d\u0430\u0439\u0442\u0438|\u0441\u0435\u043a\u0440\u0435\u0442\u044b|\u043f\u0440\u043e\u0445\u043e\u0436\u0434\u0435\u043d\u0438\u0435)\b",
    re.IGNORECASE,
)

MAX_NEWS = 10
MAX_GUIDES = 8
MARK_START = "<!--NEWS:START-->"
MARK_END = "<!--NEWS:END-->"
G_START = "<!--GUIDES:START-->"
G_END = "<!--GUIDES:END-->"


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (gta6-site-builder)"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read()


MEDIA_NS = "{http://search.yahoo.com/mrss/}"


def get_thumb(item_el):
    """URL миниатюры из media:content / media:thumbnail, если есть."""
    for tag in ("content", "thumbnail"):
        el = item_el.find(f"{MEDIA_NS}{tag}")
        if el is not None and el.get("url"):
            return el.get("url")
    return None


def parse_rss(xml_bytes: bytes):
    """Вытаскивает (title, link, pubDate, thumb) из RSS 2.0 / Atom."""
    items = []
    root = ET.fromstring(xml_bytes)
    # RSS 2.0
    for it in root.iter("item"):
        t = (it.findtext("title") or "").strip()
        l = (it.findtext("link") or "").strip()
        d = (it.findtext("pubDate") or "").strip()
        if t and l:
            items.append((t, l, d, get_thumb(it)))
    # Atom
    ns = "{http://www.w3.org/2005/Atom}"
    if not items:
        for it in root.iter(f"{ns}entry"):
            t = (it.findtext(f"{ns}title") or "").strip()
            link_el = it.find(f"{ns}link")
            l = link_el.get("href") if link_el is not None else ""
            d = (it.findtext(f"{ns}updated") or it.findtext(f"{ns}published") or "").strip()
            if t and l:
                items.append((t, l, d, None))
    return items


def parse_date(s: str):
    for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%Y-%m-%dT%H:%M:%S%z", "%a, %d %b %Y %H:%M:%S GMT"):
        try:
            dt = datetime.strptime(s.replace("+0000", "GMT").replace("GMT", "+0000") if "%z" in fmt else s, fmt)
            return dt.astimezone(timezone.utc)
        except Exception:
            continue
    return None


def main():
    all_items = []
    for feed in FEEDS:
        try:
            for title, link, pubdate, thumb in parse_rss(fetch(feed)):
                if KEYWORDS.search(title):
                    dt = parse_date(pubdate) if pubdate else None
                    all_items.append({
                        "title": title,
                        "link": link,
                        "source": re.sub(r"^www\.", "", link.split("/")[2]) if "://" in link else "?",
                        "date": dt.isoformat() if dt else None,
                        "thumb": thumb,
                    })
        except Exception as e:
            print(f"[warn] {feed}: {e}")

    # уникализуем по заголовку, сортируем свежими вверх
    seen, unique = set(), []
    for it in all_items:
        k = it["title"].lower().strip()
        if k not in seen:
            seen.add(k)
            unique.append(it)
    unique.sort(key=lambda x: x["date"] or "", reverse=True)
    news_list = [it for it in unique if not GUIDE_KEYWORDS.search(it["title"])][:MAX_NEWS]
    guide_list = [it for it in unique if GUIDE_KEYWORDS.search(it["title"])][:MAX_GUIDES]
    print(f"[ok] новостей: {len(news_list)}, гайдов/секретов: {len(guide_list)} (всего подходящих {len(all_items)})")

    # --- data/*.json ---
    out = ROOT / "data"
    out.mkdir(exist_ok=True)
    now_iso = datetime.now(timezone.utc).isoformat()
    (out / "news.json").write_text(
        json.dumps({"updated": now_iso, "items": news_list}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    (out / "guides.json").write_text(
        json.dumps({"updated": now_iso, "items": guide_list}, ensure_ascii=False, indent=2),
        encoding="utf-8")

    idx = ROOT / "index.html"
    page = idx.read_text(encoding="utf-8")

    def inject(mark_start, mark_end, items, kind):
        nonlocal page
        if items:
            rows = []
            for it in items:
                title = html_mod.escape(it["title"])
                date_str = ""
                if it["date"]:
                    d = datetime.fromisoformat(it["date"])
                    date_str = f'<span class="n-date">{d.strftime("%d.%m")}</span>'
                thumb = f'<img class="n-thumb" src="{html_mod.escape(it["thumb"], quote=True)}" alt="" loading="lazy">' if it.get("thumb") else ""
                rows.append(
                    f'<a class="n-item" href="{html_mod.escape(it["link"], quote=True)}" target="_blank" rel="noopener">'
                    f'{date_str}{thumb}<span class="n-title">{title}</span><span class="n-src">{html_mod.escape(it["source"])}</span></a>'
                )
            updated = datetime.now(timezone.utc).strftime("%d.%m.%Y %H:%M UTC")
            block = (mark_start + f'\n<p class="n-updated">{kind}: обновлено автоматически {updated}</p>\n'
                     + "\n".join(rows) + "\n" + mark_end)
        else:
            block = mark_start + "\n" + mark_end
        if mark_start in page and mark_end in page:
            pre = page.split(mark_start)[0]
            post = page.split(mark_end)[1]
            page = pre + block + post
            return True
        print(f"[warn] маркеры {mark_start}/{mark_end} не найдены")
        return False

    ok1 = inject(MARK_START, MARK_END, news_list, "Новости")
    ok2 = inject(G_START, G_END, guide_list, "Гайды в сети")
    if ok1 or ok2:
        idx.write_text(page, encoding="utf-8")
        print("[ok] index.html обновлён")


if __name__ == "__main__":
    main()
