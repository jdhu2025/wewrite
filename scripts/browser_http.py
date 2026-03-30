#!/usr/bin/env python3
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional
from urllib.error import HTTPError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen


DEFAULT_BROWSER_HTTP_URL = "http://127.0.0.1:18791"
DEFAULT_OPENCLAW_CONFIG = Path("/config/.openclaw/openclaw.json")
DEFAULT_ADAPTER_ROOT = Path("/config/.bb-browser/bb-sites")


class BrowserAutomationError(RuntimeError):
    pass


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _extract_gateway_token(config: Dict[str, Any]) -> str:
    return str(config.get("gateway", {}).get("auth", {}).get("token") or "").strip()


def _json_request(method: str, url: str, token: str, payload: Optional[Dict[str, Any]] = None) -> Any:
    headers = {"Authorization": f"Bearer {token}"}
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")
    request = Request(url, data=data, headers=headers, method=method.upper())
    try:
        with urlopen(request, timeout=120) as response:
            raw = response.read().decode("utf-8")
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        raise BrowserAutomationError(f"HTTP {exc.code} for {url}: {body[:300]}") from exc
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise BrowserAutomationError(f"Browser API returned non-JSON response for {url}") from exc


def _public_json_get(url: str) -> Any:
    request = Request(url, headers={"User-Agent": "Mozilla/5.0"}, method="GET")
    with urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


class BrowserHttpClient:
    def __init__(
        self,
        base_url: Optional[str] = None,
        token: Optional[str] = None,
        config_path: Path = DEFAULT_OPENCLAW_CONFIG,
    ) -> None:
        config = _load_json(config_path)
        resolved_token = (token or _extract_gateway_token(config)).strip()
        if not resolved_token:
            raise BrowserAutomationError("Missing OpenClaw gateway token.")
        self.base_url = (base_url or DEFAULT_BROWSER_HTTP_URL).rstrip("/")
        self.token = resolved_token

    def _request(
        self,
        method: str,
        path: str,
        payload: Optional[Dict[str, Any]] = None,
        query: Optional[Dict[str, Any]] = None,
    ) -> Any:
        url = f"{self.base_url}{path}"
        if query:
            clean_query = {key: value for key, value in query.items() if value is not None}
            url = f"{url}?{urlencode(clean_query)}"
        return _json_request(method, url, self.token, payload)

    def list_tabs(self) -> list[Dict[str, Any]]:
        payload = self._request("GET", "/tabs")
        if isinstance(payload, dict) and isinstance(payload.get("tabs"), list):
            return payload["tabs"]
        if isinstance(payload, list):
            return payload
        raise BrowserAutomationError("Unexpected browser tabs payload.")

    def open_tab(self, url: str) -> Dict[str, Any]:
        payload = self._request("POST", "/tabs/open", {"url": url})
        if not isinstance(payload, dict) or not payload.get("targetId"):
            raise BrowserAutomationError(f"Failed to open browser tab for {url}")
        return payload

    def navigate(self, target_id: str, url: str) -> Dict[str, Any]:
        payload = self._request("POST", "/navigate", {"targetId": target_id, "url": url})
        if not isinstance(payload, dict) or not payload.get("ok"):
            raise BrowserAutomationError(f"Failed to navigate tab {target_id} to {url}")
        return payload

    def act(self, target_id: str, kind: str, **kwargs: Any) -> Dict[str, Any]:
        payload = {"targetId": target_id, "kind": kind, **kwargs}
        result = self._request("POST", "/act", payload)
        if not isinstance(result, dict) or not result.get("ok"):
            raise BrowserAutomationError(f"Browser action failed: {kind}")
        return result

    def evaluate(self, target_id: str, fn: str) -> Any:
        return self.act(target_id, "evaluate", fn=fn).get("result")

    def wait(
        self,
        target_id: str,
        *,
        time_ms: Optional[int] = None,
        text: Optional[str] = None,
        fn: Optional[str] = None,
        timeout_ms: Optional[int] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {}
        if time_ms is not None:
            payload["timeMs"] = time_ms
        if text:
            payload["text"] = text
        if fn:
            payload["fn"] = fn
        if timeout_ms is not None:
            payload["timeoutMs"] = timeout_ms
        return self.act(target_id, "wait", **payload)

    def open_or_reuse_tab(self, open_url: str) -> Dict[str, Any]:
        hostname = urlparse(open_url).hostname or ""
        if hostname:
            for tab in self.list_tabs():
                tab_url = str(tab.get("url") or "")
                if not tab_url.startswith("http"):
                    continue
                if "sw.js" in tab_url or tab_url.startswith("blob:"):
                    continue
                if "Service Worker" in str(tab.get("title") or ""):
                    continue
                if (urlparse(tab_url).hostname or "") == hostname:
                    try:
                        self.navigate(str(tab["targetId"]), open_url)
                        return {"targetId": str(tab["targetId"]), "url": open_url}
                    except BrowserAutomationError as exc:
                        if "tab not found" not in str(exc).lower():
                            raise
        return self.open_tab(open_url)


class BrowserAdapterRunner:
    def __init__(self, client: BrowserHttpClient, adapter_root: Path = DEFAULT_ADAPTER_ROOT) -> None:
        self.client = client
        self.adapter_root = adapter_root
        self._cache: Dict[str, str] = {}

    def _adapter_path(self, site: str) -> Path:
        return self.adapter_root / f"{site}.js"

    def _load_function_source(self, site: str) -> str:
        if site in self._cache:
            return self._cache[site]
        path = self._adapter_path(site)
        if not path.exists():
            raise BrowserAutomationError(f"Adapter not found: {site}")
        source = path.read_text(encoding="utf-8")
        marker = "async function(args)"
        start = source.find(marker)
        if start < 0:
            raise BrowserAutomationError(f"Adapter format unsupported: {site}")
        function_source = source[start:].strip()
        self._cache[site] = function_source
        return function_source

    def run_site(self, site: str, args: Dict[str, Any], open_url: str) -> Dict[str, Any]:
        if site == "hackernews/top":
            return self._run_hackernews_top(args)
        if site == "twitter/search":
            return self._run_twitter_search(args, open_url)
        function_source = self._load_function_source(site)
        wrapper = (
            "() => (async () => { "
            f"const __site = {function_source}; "
            f"return await __site({json.dumps(args, ensure_ascii=False)});"
            " })()"
        )
        last_error: Optional[Exception] = None
        for _ in range(2):
            tab = self.client.open_or_reuse_tab(open_url)
            target_id = str(tab["targetId"])
            try:
                result = self.client.evaluate(target_id, wrapper)
                if not isinstance(result, dict):
                    raise BrowserAutomationError(f"Adapter returned invalid payload: {site}")
                return result
            except BrowserAutomationError as exc:
                if "tab not found" not in str(exc).lower():
                    raise
                last_error = exc
        if last_error:
            raise last_error
        raise BrowserAutomationError(f"Adapter returned invalid payload: {site}")

    def _run_hackernews_top(self, args: Dict[str, Any]) -> Dict[str, Any]:
        count = min(int(args.get("count") or 20), 50)
        ids = _public_json_get("https://hacker-news.firebaseio.com/v0/topstories.json")[:count]
        items = []
        for index, item_id in enumerate(ids, start=1):
            post = _public_json_get(f"https://hacker-news.firebaseio.com/v0/item/{item_id}.json")
            items.append(
                {
                    "rank": index,
                    "id": post.get("id"),
                    "title": post.get("title"),
                    "url": post.get("url"),
                    "hn_url": f"https://news.ycombinator.com/item?id={post.get('id')}",
                    "author": post.get("by"),
                    "score": post.get("score"),
                    "comments": post.get("descendants") or 0,
                    "time": post.get("time"),
                }
            )
        return {"count": len(items), "posts": items}

    def _run_twitter_search(self, args: Dict[str, Any], open_url: str) -> Dict[str, Any]:
        query = str(args.get("query") or "").strip()
        if not query:
            raise BrowserAutomationError("twitter/search requires query")
        if "since:" not in query:
            since_date = (datetime.now(timezone.utc) - timedelta(days=2)).strftime("%Y-%m-%d")
            query = f"{query} since:{since_date}"
        count = min(int(args.get("count") or 20), 50)
        top = str(args.get("type") or "").strip().lower() == "top"
        search_url = "https://x.com/search?q=" + urlencode({"q": query})[2:] + "&src=typed_query&f=" + ("top" if top else "live")
        tab = self.client.open_or_reuse_tab(open_url)
        target_id = str(tab["targetId"])
        self.client.navigate(target_id, search_url)
        self.client.wait(target_id, time_ms=2500)
        scraper = (
            "() => (async () => {"
            f"const count = {count};"
            f"const product = {json.dumps('Top' if top else 'Latest')};"
            "const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));"
            "const ready = () => {"
            "  const bodyText = document.body?.innerText || '';"
            "  return document.querySelectorAll('article').length > 0 || bodyText.includes('No results') || bodyText.includes('Try searching for');"
            "};"
            "for (let i = 0; i < 24; i += 1) { if (ready()) break; await wait(500); }"
            "let lastCount = -1;"
            "let stableRounds = 0;"
            "for (let i = 0; i < 12; i += 1) {"
            "  const articleCount = document.querySelectorAll('article').length;"
            "  window.scrollTo(0, document.body.scrollHeight);"
            "  if (articleCount >= count) break;"
            "  if (articleCount === lastCount) stableRounds += 1; else stableRounds = 0;"
            "  if (stableRounds >= 2) break;"
            "  lastCount = articleCount;"
            "  await wait(700);"
            "}"
            "const tweets = [];"
            "const seen = new Set();"
            "for (const article of Array.from(document.querySelectorAll('article'))) {"
            "  const statusLink = Array.from(article.querySelectorAll('a[href*=\"/status/\"]')).map((a) => a.href).find((href) => /^https:\\/\\/x\\.com\\/[^/]+\\/status\\/\\d+$/.test(href));"
            "  if (!statusLink || seen.has(statusLink)) continue;"
            "  seen.add(statusLink);"
            "  const match = statusLink.match(/^https:\\/\\/x\\.com\\/([^/]+)\\/status\\/(\\d+)$/);"
            "  const userNameNodes = Array.from(article.querySelectorAll('[data-testid=\"User-Name\"] span')).map((node) => node.innerText.trim()).filter(Boolean);"
            "  const text = article.querySelector('[data-testid=\"tweetText\"]')?.innerText?.trim() || '';"
            "  tweets.push({"
            "    id: match?.[2],"
            "    author: match?.[1],"
            "    name: userNameNodes.find((value) => !value.startsWith('@') && value !== '·'),"
            "    url: statusLink,"
            "    text,"
            "    created_at: article.querySelector('time')?.getAttribute('datetime') || undefined"
            "  });"
            "  if (tweets.length >= count) break;"
            "}"
            "return {query: " + json.dumps(query, ensure_ascii=False) + ", product, count: tweets.length, tweets};"
            "})()"
        )
        result = self.client.evaluate(target_id, scraper)
        if not isinstance(result, dict):
            raise BrowserAutomationError("twitter/search scraper returned invalid payload")
        return result


def first_non_empty(values: Iterable[Any]) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""
