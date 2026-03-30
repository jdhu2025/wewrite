#!/usr/bin/env python3
"""
Fetch trending topics from Chinese public hotlists plus bb-browser sources.

Default public sources:
  1. Weibo hot search
  2. Toutiao hot board
  3. Baidu realtime hot search

Optional bb-browser expansion sources (auto-enabled by style topics when available):
  - X / Twitter search
  - Hacker News
  - Product Hunt
  - Reddit
  - Reuters
  - Xueqiu

Usage:
    python3 scripts/fetch_hotspots.py --limit 20
    python3 scripts/fetch_hotspots.py --limit 30 --disable-bb
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests
import yaml

from browser_http import BrowserAdapterRunner, BrowserAutomationError, BrowserHttpClient

TIMEOUT = 10
BB_TIMEOUT = 120
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
}

SKILL_DIR = Path(__file__).resolve().parents[1]
STYLE_PATH = SKILL_DIR / "style.yaml"
LOW_QUALITY_TOKENS = [
    "nsfw",
    "furry",
    "yiff",
    "fanart",
    "bara",
    "giveaway",
    "dm me",
    "telegram",
    "pump",
    "airdrop",
    "join now",
]
AI_KEYWORDS = ["openai", "anthropic", "claude", "gemini", "chatgpt", "llm", "agent", "ai model", "reasoning model"]
FINANCE_KEYWORDS = ["fomc", "inflation", "cpi", "fed", "treasury", "yield", "rate cut", "rate hike", "bond market", "macro"]
CRYPTO_KEYWORDS = ["bitcoin", "btc", "ethereum", "eth", "crypto", "stablecoin", "tokenization", "defi", "solana"]
USSTOCKS_KEYWORDS = ["nasdaq", "s&p 500", "earnings", "$nvda", "$tsla", "nvidia", "tesla", "apple", "microsoft", "dow"]
AI_CN_KEYWORDS = ["ai", "人工智能", "大模型", "智能体", "openai", "claude", "gemini"]
FINANCE_CN_KEYWORDS = ["金融", "财经", "宏观", "通胀", "利率", "央行", "债券", "降息", "加息"]
CRYPTO_CN_KEYWORDS = ["币圈", "加密", "比特币", "以太坊", "稳定币", "数字货币", "区块链"]
USSTOCKS_CN_KEYWORDS = ["美股", "纳指", "标普", "英伟达", "特斯拉", "苹果", "微软", "财报"]


def fetch_weibo() -> list[dict]:
    """Fetch Weibo hot search."""
    try:
        resp = requests.get(
            "https://weibo.com/ajax/side/hotSearch",
            headers={**HEADERS, "Referer": "https://weibo.com/"},
            timeout=TIMEOUT,
        )
        data = resp.json()
        items = []
        for entry in data.get("data", {}).get("realtime", []):
            note = entry.get("note", "")
            if not note:
                continue
            items.append(
                {
                    "title": note,
                    "source": "微博",
                    "source_key": "weibo",
                    "hot": int(entry.get("num", 0) or 0),
                    "url": f"https://s.weibo.com/weibo?q=%23{note}%23",
                    "description": entry.get("label_name", ""),
                    "platform": "weibo",
                    "source_weight": 0.75,
                }
            )
        return items
    except Exception as exc:
        print(f"[warn] weibo failed: {exc}", file=sys.stderr)
        return []


def fetch_toutiao() -> list[dict]:
    """Fetch Toutiao hot board."""
    try:
        resp = requests.get(
            "https://www.toutiao.com/hot-event/hot-board/?origin=toutiao_pc",
            headers=HEADERS,
            timeout=TIMEOUT,
        )
        data = resp.json()
        items = []
        for entry in data.get("data", []):
            title = entry.get("Title", "")
            if not title:
                continue
            items.append(
                {
                    "title": title,
                    "source": "今日头条",
                    "source_key": "toutiao",
                    "hot": int(entry.get("HotValue", 0) or 0),
                    "url": entry.get("Url", ""),
                    "description": entry.get("Label", "") or "",
                    "platform": "toutiao",
                    "source_weight": 0.74,
                }
            )
        return items
    except Exception as exc:
        print(f"[warn] toutiao failed: {exc}", file=sys.stderr)
        return []


def fetch_baidu() -> list[dict]:
    """Fetch Baidu hot search."""
    try:
        resp = requests.get(
            "https://top.baidu.com/api/board?platform=wise&tab=realtime",
            headers=HEADERS,
            timeout=TIMEOUT,
        )
        data = resp.json()
        items = []
        for card in data.get("data", {}).get("cards", []):
            top_content = card.get("content", [])
            if not top_content:
                continue
            entries = top_content[0].get("content", []) if isinstance(top_content[0], dict) else top_content
            for entry in entries:
                word = entry.get("word", "")
                if not word:
                    continue
                items.append(
                    {
                        "title": word,
                        "source": "百度",
                        "source_key": "baidu",
                        "hot": int(entry.get("hotScore", 0) or 0),
                        "url": entry.get("url", ""),
                        "description": entry.get("desc", "") or "",
                        "platform": "baidu",
                        "source_weight": 0.72,
                    }
                )
        return items
    except Exception as exc:
        print(f"[warn] baidu failed: {exc}", file=sys.stderr)
        return []


def deduplicate(items: list[dict]) -> list[dict]:
    """Remove duplicates by exact title match, then fallback to url."""
    seen_titles = set()
    seen_urls = set()
    result = []
    for item in items:
        title = str(item.get("title", "")).strip()
        url = str(item.get("url", "")).strip()
        if not title:
            continue
        if title in seen_titles:
            continue
        if url and url in seen_urls:
            continue
        seen_titles.add(title)
        if url:
            seen_urls.add(url)
        result.append(item)
    return result


def load_topics() -> list[str]:
    if not STYLE_PATH.exists():
        return []
    try:
        data = yaml.safe_load(STYLE_PATH.read_text(encoding="utf-8")) or {}
    except Exception:
        return []
    topics = data.get("topics") or []
    return [str(topic).strip() for topic in topics if str(topic).strip()]


def _is_noisy_text(text: str) -> bool:
    lowered = text.lower()
    if sum(1 for token in LOW_QUALITY_TOKENS if token in lowered) >= 1:
        return True
    if lowered.count("#") >= 4:
        return True
    return False


def _contains_any(text: str, keywords: list[str]) -> bool:
    lowered = text.lower()
    return any(keyword in lowered for keyword in keywords)


def topic_flags(topics: list[str]) -> dict[str, bool]:
    joined = " ".join(topics).lower()

    def has_any(keywords: list[str]) -> bool:
        return any(keyword in joined for keyword in keywords)

    flags = {
        "ai": has_any(["ai", "人工智能", "智能体", "大模型", "模型", "科技", "tech", "互联网", "agent"]),
        "product": has_any(["产品", "工具", "效率", "创业", "商业", "saas", "startup"]),
        "finance": has_any(["金融", "财经", "宏观", "经济", "投资", "资金", "利率", "债券"]),
        "crypto": has_any(["币", "crypto", "区块链", "比特币", "以太坊", "btc", "eth"]),
        "usstocks": has_any(["美股", "纳指", "标普", "英伟达", "特斯拉", "财报", "stocks", "equity"]),
    }
    flags["fallback"] = not any(flags.values())
    return flags


def _public_item_relevant(item: dict, flags: dict[str, bool]) -> bool:
    if flags["fallback"]:
        return True
    text = f"{item.get('title', '')} {item.get('description', '')}".lower()
    if flags["ai"] and _contains_any(text, AI_CN_KEYWORDS):
        return True
    if flags["finance"] and _contains_any(text, FINANCE_CN_KEYWORDS):
        return True
    if flags["crypto"] and _contains_any(text, CRYPTO_CN_KEYWORDS):
        return True
    if flags["usstocks"] and _contains_any(text, USSTOCKS_CN_KEYWORDS):
        return True
    return False


def parse_twitter_ai(data: dict) -> list[dict]:
    items = []
    for tweet in data.get("tweets", []):
        text = str(tweet.get("text", "")).strip()
        if not text or _is_noisy_text(text) or not _contains_any(text, AI_KEYWORDS):
            continue
        items.append(
            {
                "title": text[:80],
                "source": "X",
                "source_key": "twitter_ai",
                "hot": 0,
                "url": tweet.get("url", ""),
                "description": text[:220],
                "platform": "twitter",
                "source_weight": 1.0,
                "published_at": tweet.get("created_at"),
                "author": tweet.get("author"),
            }
        )
    return items


def parse_twitter_finance(data: dict) -> list[dict]:
    items = []
    for tweet in data.get("tweets", []):
        text = str(tweet.get("text", "")).strip()
        if not text or _is_noisy_text(text) or not _contains_any(text, FINANCE_KEYWORDS):
            continue
        items.append(
            {
                "title": text[:80],
                "source": "X",
                "source_key": "twitter_finance",
                "hot": 0,
                "url": tweet.get("url", ""),
                "description": text[:220],
                "platform": "twitter",
                "source_weight": 0.98,
                "published_at": tweet.get("created_at"),
                "author": tweet.get("author"),
            }
        )
    return items


def parse_twitter_crypto(data: dict) -> list[dict]:
    items = []
    for tweet in data.get("tweets", []):
        text = str(tweet.get("text", "")).strip()
        if not text or _is_noisy_text(text) or not _contains_any(text, CRYPTO_KEYWORDS):
            continue
        items.append(
            {
                "title": text[:80],
                "source": "X",
                "source_key": "twitter_crypto",
                "hot": 0,
                "url": tweet.get("url", ""),
                "description": text[:220],
                "platform": "twitter",
                "source_weight": 1.0,
                "published_at": tweet.get("created_at"),
                "author": tweet.get("author"),
            }
        )
    return items


def parse_twitter_usstocks(data: dict) -> list[dict]:
    items = []
    for tweet in data.get("tweets", []):
        text = str(tweet.get("text", "")).strip()
        if not text or _is_noisy_text(text) or not _contains_any(text, USSTOCKS_KEYWORDS):
            continue
        items.append(
            {
                "title": text[:80],
                "source": "X",
                "source_key": "twitter_usstocks",
                "hot": 0,
                "url": tweet.get("url", ""),
                "description": text[:220],
                "platform": "twitter",
                "source_weight": 0.98,
                "published_at": tweet.get("created_at"),
                "author": tweet.get("author"),
            }
        )
    return items


def parse_hn(data: dict) -> list[dict]:
    return [
        {
            "title": post.get("title", ""),
            "source": "Hacker News",
            "source_key": "hackernews_top",
            "hot": int(post.get("score", 0) or 0),
            "url": post.get("url") or post.get("hn_url", ""),
            "description": f"score {post.get('score', 0)} / comments {post.get('comments', 0)}",
            "platform": "hackernews",
            "source_weight": 0.92,
            "published_at": post.get("time"),
            "author": post.get("author"),
        }
        for post in data.get("posts", [])
        if post.get("title")
    ]


def parse_producthunt(data: dict) -> list[dict]:
    return [
        {
            "title": product.get("name", ""),
            "source": "Product Hunt",
            "source_key": "producthunt_today",
            "hot": int(product.get("votes", 0) or 0),
            "url": product.get("url", ""),
            "description": (product.get("tagline") or product.get("description") or "")[:220],
            "platform": "producthunt",
            "source_weight": 0.9,
            "published_at": product.get("featured_at"),
        }
        for product in data.get("products", [])
        if product.get("name")
    ]


def parse_xueqiu(data: dict) -> list[dict]:
    return [
        {
            "title": f"{item.get('name', '')}（{item.get('symbol', '')}）",
            "source": "雪球",
            "source_key": "xueqiu_hot_stock",
            "hot": int(item.get("heat", 0) or 0),
            "url": item.get("url", ""),
            "description": f"当前价 {item.get('price', '-') }，涨跌 {item.get('changePercent', '-')}",
            "platform": "xueqiu",
            "source_weight": 0.9,
        }
        for item in data.get("items", [])
        if item.get("name")
    ]


def parse_reuters_markets(data: dict) -> list[dict]:
    return [
        {
            "title": article.get("title", ""),
            "source": "Reuters",
            "source_key": "reuters_markets",
            "hot": 0,
            "url": article.get("url", ""),
            "description": article.get("description", "")[:220],
            "platform": "reuters",
            "source_weight": 1.02,
            "published_at": article.get("date"),
            "author": article.get("authors"),
        }
        for article in data.get("results", [])
        if article.get("title")
    ]


def parse_reuters_ai(data: dict) -> list[dict]:
    items = parse_reuters_markets(data)
    for item in items:
        item["source_key"] = "reuters_ai"
        item["source_weight"] = 1.03
    return items


def parse_reuters_crypto(data: dict) -> list[dict]:
    items = parse_reuters_markets(data)
    for item in items:
        item["source_key"] = "reuters_crypto"
        item["source_weight"] = 1.01
    return items


def parse_reddit_ai(data: dict) -> list[dict]:
    return [
        {
            "title": post.get("title", ""),
            "source": "Reddit",
            "source_key": "reddit_ai",
            "hot": int(post.get("score", 0) or 0),
            "url": post.get("permalink") or post.get("url", ""),
            "description": (post.get("selftext_preview") or "")[:220],
            "platform": "reddit",
            "source_weight": 0.86,
            "published_at": post.get("created_utc"),
            "author": post.get("author"),
        }
        for post in data.get("posts", [])
        if post.get("title")
    ]


def parse_reddit_crypto(data: dict) -> list[dict]:
    items = parse_reddit_ai(data)
    for item in items:
        item["source_key"] = "reddit_crypto"
        item["source_weight"] = 0.84
    return items


def parse_reddit_stocks(data: dict) -> list[dict]:
    items = parse_reddit_ai(data)
    for item in items:
        item["source_key"] = "reddit_stocks"
        item["source_weight"] = 0.84
    return items


def build_bb_sources(topics: list[str]) -> list[dict]:
    flags = topic_flags(topics)
    sources: list[dict] = []

    def add(source: dict) -> None:
        if source["id"] not in {item["id"] for item in sources}:
            sources.append(source)

    if flags["ai"] or flags["fallback"]:
        add(
            {
                "id": "twitter_ai",
                "site": "twitter/search",
                "args": [
                    "(OpenAI OR Anthropic OR Gemini OR Claude OR ChatGPT OR LLM OR AI agent) lang:en min_faves:80 -filter:replies -filter:retweets -AIart -furry -NSFW",
                    "8",
                    "latest",
                ],
                "parser": parse_twitter_ai,
            }
        )
        add(
            {
                "id": "reddit_ai",
                "site": "reddit/hot",
                "args": ["MachineLearning", "6"],
                "parser": parse_reddit_ai,
            }
        )
    if flags["product"] or flags["fallback"]:
        add({"id": "hackernews_top", "site": "hackernews/top", "args": ["10"], "parser": parse_hn})
        add({"id": "producthunt_today", "site": "producthunt/today", "args": ["8"], "parser": parse_producthunt})

    if flags["finance"]:
        add(
            {
                "id": "twitter_finance",
                "site": "twitter/search",
                "args": [
                    "(FOMC OR CPI OR inflation OR treasury yields OR bond market OR rate cuts) lang:en min_faves:60 -filter:replies -filter:retweets",
                    "8",
                    "latest",
                ],
                "parser": parse_twitter_finance,
            }
        )
    if flags["usstocks"]:
        add(
            {
                "id": "twitter_usstocks",
                "site": "twitter/search",
                "args": [
                    "(Nasdaq OR S&P 500 OR earnings OR $NVDA OR $TSLA OR Nvidia OR Tesla) lang:en min_faves:60 -filter:replies -filter:retweets",
                    "8",
                    "latest",
                ],
                "parser": parse_twitter_usstocks,
            }
        )
        add({"id": "xueqiu_hot_stock", "site": "xueqiu/hot-stock", "args": ["8"], "parser": parse_xueqiu})
        add({"id": "reddit_stocks", "site": "reddit/hot", "args": ["stocks", "6"], "parser": parse_reddit_stocks})

    if flags["crypto"]:
        add(
            {
                "id": "twitter_crypto",
                "site": "twitter/search",
                "args": [
                    "(bitcoin OR ethereum OR crypto OR stablecoin) lang:en min_faves:80 -filter:replies -filter:retweets",
                    "8",
                    "latest",
                ],
                "parser": parse_twitter_crypto,
            }
        )
        add(
            {
                "id": "reddit_crypto",
                "site": "reddit/hot",
                "args": ["CryptoCurrency", "6"],
                "parser": parse_reddit_crypto,
            }
        )
    return sources


def fetch_bb_sources(topics: list[str]) -> tuple[list[dict], list[str], list[str]]:
    items: list[dict] = []
    sources_ok: list[str] = []
    sources_fail: list[str] = []
    source_defs = build_bb_sources(topics)
    if not source_defs:
        return items, sources_ok, sources_fail

    try:
        client = BrowserHttpClient()
        runner = BrowserAdapterRunner(client)
    except BrowserAutomationError as exc:
        print(f"[warn] bb-browser adapters unavailable: {exc}", file=sys.stderr)
        return items, sources_ok, [source["id"] for source in source_defs]

    open_urls = {
        "twitter/search": "https://x.com/home",
        "hackernews/top": "https://news.ycombinator.com/",
        "producthunt/today": "https://www.producthunt.com/",
        "reddit/hot": "https://www.reddit.com/",
        "reuters/search": "https://www.reuters.com/",
        "xueqiu/hot-stock": "https://xueqiu.com/",
    }

    arg_keys = {
        "twitter/search": ["query", "count", "type"],
        "hackernews/top": ["count"],
        "producthunt/today": ["count"],
        "reddit/hot": ["subreddit", "count"],
        "reuters/search": ["query", "count"],
        "xueqiu/hot-stock": ["count", "type"],
    }

    for source in source_defs:
        try:
            args = {key: value for key, value in zip(arg_keys.get(source["site"], []), source["args"])}
            raw = runner.run_site(source["site"], args, open_urls[source["site"]])
            parsed = source["parser"](raw)
            if parsed:
                items.extend(parsed)
                sources_ok.append(source["id"])
            else:
                sources_fail.append(source["id"])
        except Exception as exc:
            print(f"[warn] {source['id']} failed: {exc}", file=sys.stderr)
            sources_fail.append(source["id"])
    return items, sources_ok, sources_fail


def _raw_hot(item: dict) -> int:
    value = item.get("hot", 0)
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def _freshness_bonus(item: dict) -> float:
    published_at = str(item.get("published_at") or "").strip()
    if not published_at:
        return 0.0
    try:
        normalized = published_at.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        age_hours = max(0.0, (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds() / 3600)
        return max(0.0, 20.0 - min(age_hours, 20.0))
    except Exception:
        return 0.0


def normalize_scores(items: list[dict]) -> list[dict]:
    by_source: dict[str, list[dict]] = {}
    for order, item in enumerate(items):
        item["_source_order"] = order
        by_source.setdefault(item.get("source_key", item.get("source", "unknown")), []).append(item)

    for source_items in by_source.values():
        source_items.sort(
            key=lambda entry: (
                _raw_hot(entry),
                -int(entry.get("_source_order", 0)),
            ),
            reverse=True,
        )
        n = len(source_items)
        for rank, item in enumerate(source_items):
            base = round(100 * (n - rank) / n, 1) if n > 0 else 0.0
            weighted = base * float(item.get("source_weight", 1.0) or 1.0)
            item["hot_normalized"] = round(weighted + _freshness_bonus(item), 1)
    return items


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch trending topics")
    parser.add_argument("--limit", type=int, default=20, help="Max items to return")
    parser.add_argument("--disable-bb", action="store_true", help="Disable bb-browser expansion sources")
    args = parser.parse_args()

    all_items = []
    sources_ok = []
    sources_fail = []

    topics = load_topics()
    flags = topic_flags(topics)

    for name, fetcher in [("weibo", fetch_weibo), ("toutiao", fetch_toutiao), ("baidu", fetch_baidu)]:
        items = fetcher()
        if items:
            items = [item for item in items if _public_item_relevant(item, flags)]
        if items:
            sources_ok.append(name)
            all_items.extend(items)
        else:
            sources_fail.append(name)

    if not args.disable_bb:
        bb_items, bb_ok, bb_fail = fetch_bb_sources(topics)
        all_items.extend(bb_items)
        sources_ok.extend(bb_ok)
        sources_fail.extend(bb_fail)

    all_items = deduplicate(all_items)
    all_items = normalize_scores(all_items)
    all_items.sort(key=lambda item: item.get("hot_normalized", 0), reverse=True)
    all_items = all_items[: args.limit]

    tz = timezone(timedelta(hours=8))
    output = {
        "timestamp": datetime.now(tz).isoformat(),
        "topics": topics,
        "sources": sources_ok,
        "sources_failed": sources_fail,
        "count": len(all_items),
        "items": all_items,
    }

    if not all_items:
        output["error"] = "All sources failed. SKILL.md should fall back to WebSearch."

    json.dump(output, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
