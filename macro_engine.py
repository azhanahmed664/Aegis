"""Background multi-source RSS/API macro harvester and briefing synthesis."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
import os
import re
from typing import Any
from urllib.parse import urljoin

import feedparser
import requests


class MacroHarvester:
    """Poll twenty market sources with bounded RSS and HTML fallback requests."""

    CATEGORIES = {
        "Crypto": ("BITCOIN", "BTC", "CRYPTO", "ETHEREUM", "ETH", "ETF", "DOMINANCE", "ALTCOIN", "TOKEN"),
        "Commodities": ("GOLD", "XAU", "SILVER", "XAG", "OIL", "CRUDE", "NATURAL GAS", "COPPER"),
        "Rates": ("YIELD", "TREASURY", "10-YEAR", "10 YEAR", "FED", "POWELL", "RATE", "HIKE", "INFLATION", "FOMC", "ECB"),
        "Equities": ("S&P", "SP500", "EQUITY", "EQUITIES", "STOCKS", "EARNINGS", "NASDAQ", "DOW JONES", "WALL STREET"),
    }
    POSITIVE = ("GAIN", "RISE", "RALLY", "SURGE", "BEAT", "GROWTH", "RECORD HIGH", "UPGRADE", "EASE", "INFLOWS", "BULLISH")
    NEGATIVE = ("FALL", "DROP", "SLUMP", "MISS", "LOSS", "SELL-OFF", "FEAR", "WEAK", "DOWNGRADE", "CRISIS", "BEARISH")
    HAWKISH = ("HIKE", "HAWKISH", "TIGHTEN", "INFLATION", "HIGHER RATES", "RATE INCREASE")
    DOVISH = ("CUT", "DOVISH", "EASING", "LOWER RATES", "RATE REDUCTION", "PAUSE")

    SOURCES = {
        "Federal Reserve": ("https://www.federalreserve.gov/feeds/press_all.xml", "https://www.federalreserve.gov/newsevents/pressreleases.htm"),
        "ECB": ("https://www.ecb.europa.eu/rss/press.html", "https://www.ecb.europa.eu/press/html/index.en.html"),
        "Yahoo Finance BTC": ("https://feeds.finance.yahoo.com/rss/2.0/headline?s=BTC-USD&region=US&lang=en-US", "https://finance.yahoo.com/quote/BTC-USD/news/"),
        "Yahoo Finance S&P 500": ("https://feeds.finance.yahoo.com/rss/2.0/headline?s=%5EGSPC&region=US&lang=en-US", "https://finance.yahoo.com/quote/%5EGSPC/news/"),
        "CoinTelegraph": ("https://cointelegraph.com/rss", "https://cointelegraph.com/"),
        "CoinDesk": ("https://www.coindesk.com/arc/outboundfeeds/rss/", "https://www.coindesk.com/"),
        "CNBC Business": ("https://www.cnbc.com/id/10001147/device/rss/rss.html", "https://www.cnbc.com/business/"),
        "Reuters Business": ("https://feeds.reuters.com/reuters/businessNews", "https://www.reuters.com/business/"),
        "CoinMarketCal": ("", "https://coinmarketcal.com/en/events"),
        "CoinMarketCap": ("https://coinmarketcap.com/headlines/news/rss/", "https://coinmarketcap.com/headlines/news/"),
        "ZeroHedge": ("https://feeds.feedburner.com/zerohedge/feed", "https://www.zerohedge.com/"),
        "Trading Economics": ("https://tradingeconomics.com/rss/news.aspx", "https://tradingeconomics.com/"),
        "TheStreet": ("https://www.thestreet.com/.rss/full/", "https://www.thestreet.com/"),
        "WatcherGuru": ("https://watcher.guru/news/rss", "https://watcher.guru/news"),
        "Investing.com": ("https://www.investing.com/rss/news_14.rss", "https://www.investing.com/news/"),
        "Saxo": ("https://www.home.saxo/en-gb/insights/content-hub/rss", "https://www.home.saxo/en-gb/insights"),
        "Tickmill": ("https://www.tickmill.com/blog/feed/", "https://www.tickmill.com/blog/"),
        "Rio Times": ("https://www.riotimesonline.com/feed/", "https://www.riotimesonline/"),
        "WorldMonitor": ("", "https://worldmonitor.app/"),
        "Bank of England": ("https://www.bankofengland.co.uk/rss/news", "https://www.bankofengland.co.uk/news"),
    }

    def __init__(self, timeout: tuple[int, int] = (3, 7), workers: int = 8):
        self.timeout = timeout
        self.workers = max(1, min(int(workers), 12))
        self.user_agent = "AegisMacroHarvester/3.0 (+market briefing service)"

    @staticmethod
    def _sentiment(headline: str, positive: tuple[str, ...], negative: tuple[str, ...]) -> str:
        text = headline.upper()
        up, down = sum(word in text for word in positive), sum(word in text for word in negative)
        return "Positive" if up > down else "Negative" if down > up else "Neutral"

    @classmethod
    def _classify(cls, title: str, source: str, link: str, published: str) -> dict[str, Any] | None:
        headline = re.sub(r"\s+", " ", str(title or "")).strip()
        if not headline:
            return None
        upper = headline.upper()
        try:
            published_utc = datetime.fromisoformat(str(published).replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()
        except Exception:
            try:
                published_utc = parsedate_to_datetime(str(published)).astimezone(timezone.utc).isoformat()
            except Exception:
                published_utc = ""
        hawk = sum(word in upper for word in cls.HAWKISH)
        dove = sum(word in upper for word in cls.DOVISH)
        tags = [category for category, words in cls.CATEGORIES.items()
                if any(word in upper for word in words)]
        return {
            "published": published_utc,
            "source": source,
            "headline": headline[:500],
            "tags": tags or ["General"],
            "sentiment": cls._sentiment(headline, cls.POSITIVE, cls.NEGATIVE),
            "rates_tone": "Hawkish" if hawk > dove else "Dovish" if dove > hawk else "Mixed",
            "link": str(link or "")[:1000],
        }

    def _get(self, url: str, *, params: dict | None = None, headers: dict | None = None):
        request_headers = {"User-Agent": self.user_agent}
        request_headers.update(headers or {})
        response = requests.get(url, params=params, headers=request_headers, timeout=self.timeout)
        response.raise_for_status()
        return response

    @staticmethod
    def _parse_html(response, limit: int = 20) -> list[dict[str, str]]:
        """Extract article-like anchors, using BeautifulSoup when installed."""
        url = response.url
        html = response.text[:2_000_000]
        candidates: list[tuple[str, str]] = []
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "html.parser")
            for node in soup.select("article h1, article h2, article h3, article a, h1 a, h2 a, h3 a, [class*=title] a"):
                anchor = node if getattr(node, "name", "") == "a" else node.find("a", href=True)
                title = re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()
                href = (anchor.get("href") if anchor else "") or ""
                if 24 <= len(title) <= 240 and href:
                    candidates.append((title, urljoin(url, href)))
        except ImportError:
            class LinkParser(HTMLParser):
                def __init__(self):
                    super().__init__()
                    self.items: list[tuple[str, str]] = []
                    self.href = ""
                    self.parts: list[str] = []
                def handle_starttag(self, tag, attrs):
                    if tag.lower() == "a":
                        self.href = dict(attrs).get("href", "") or ""
                        self.parts = []
                def handle_data(self, data):
                    if self.href:
                        self.parts.append(data)
                def handle_endtag(self, tag):
                    if tag.lower() == "a" and self.href:
                        title = re.sub(r"\s+", " ", " ".join(self.parts)).strip()
                        if 24 <= len(title) <= 240:
                            self.items.append((title, urljoin(url, self.href)))
                        self.href, self.parts = "", []
            parser = LinkParser()
            parser.feed(html)
            candidates.extend(parser.items)
        output, seen = [], set()
        for title, link in candidates:
            if title.casefold() in seen or not link.startswith(("https://", "http://")):
                continue
            seen.add(title.casefold())
            output.append({"title": title, "link": link, "published": ""})
            if len(output) >= limit:
                break
        return output

    def _fetch_source(self, source: str, urls: tuple[str, str]) -> tuple[str, list[dict[str, str]], str]:
        rss_url, fallback_url = urls
        api_key = os.getenv("COINMARKETCAL_API_KEY", "").strip()
        if source == "CoinMarketCal" and api_key:
            try:
                response = self._get(
                    "https://api.coinmarketcal.com/v2/events",
                    params={"limit": 25, "sortBy": "date_asc"},
                    headers={"x-api-key": api_key, "Accept": "application/json"},
                )
                rows = response.json().get("data", [])
                items = [{
                    "title": row.get("title", ""),
                    "link": row.get("sourceUrl") or f"https://coinmarketcal.com/en/event/{row.get('slug', '')}",
                    "published": row.get("date", ""),
                } for row in rows]
                return source, items, "API ONLINE"
            except Exception as exc:
                api_error = str(exc)
        else:
            api_error = ""

        rss_error = ""
        if rss_url:
            try:
                response = self._get(rss_url)
                parsed = feedparser.parse(response.content)
                items = [{
                    "title": getattr(entry, "title", ""),
                    "link": entry.get("link", ""),
                    "published": entry.get("published", entry.get("updated", "")),
                } for entry in parsed.entries[:25] if getattr(entry, "title", "").strip()]
                if items:
                    return source, items, "RSS ONLINE"
                rss_error = "RSS parsed with no entries"
            except Exception as exc:
                rss_error = str(exc)

        try:
            response = self._get(fallback_url)
            items = self._parse_html(response)
            if items:
                reason = "API unavailable; " if api_error else ""
                return source, items, f"HTML FALLBACK ({reason}RSS unavailable/empty)"
            raise RuntimeError("no article headline links found")
        except Exception as exc:
            details = "; ".join(part for part in (api_error, rss_error, str(exc)) if part)
            return source, [], f"OFFLINE: {details[:180]}"

    @staticmethod
    def _tone(items: list[dict[str, Any]]) -> str:
        positive = sum(row.get("sentiment") == "Positive" for row in items)
        negative = sum(row.get("sentiment") == "Negative" for row in items)
        return "constructive" if positive > negative else "defensive" if negative > positive else "mixed"

    def _synthesize(self, headlines: list[dict[str, Any]]) -> str:
        by_tag = {tag: [item for item in headlines if tag in item["tags"]]
                  for tag in self.CATEGORIES}
        crypto, commodities = by_tag["Crypto"], by_tag["Commodities"]
        rates, equities = by_tag["Rates"], by_tag["Equities"]
        dominance = [item for item in crypto if any(word in item["headline"].upper() for word in ("DOMINANCE", "BTC.D", "BITCOIN SHARE"))]
        gold = [item for item in commodities if any(word in item["headline"].upper() for word in ("GOLD", "XAU"))]
        silver = [item for item in commodities if any(word in item["headline"].upper() for word in ("SILVER", "XAG"))]
        yield_items = [item for item in rates if any(word in item["headline"].upper() for word in ("10-YEAR", "10 YEAR", "TREASURY", "YIELD"))]
        hawkish = sum(item["rates_tone"] == "Hawkish" for item in rates)
        dovish = sum(item["rates_tone"] == "Dovish" for item in rates)
        policy = "net hawkish" if hawkish > dovish else "net dovish" if dovish > hawkish else "two-way/mixed"
        broad = self._tone(headlines)
        dominance_text = self._tone(dominance) if dominance else "not directly measured in this headline sample"
        yield_text = self._tone(yield_items) if yield_items else "no direct 10-year yield headline signal"
        return (
            f"Digital assets: {len(crypto)} crypto headlines were captured, with overall headline tone {self._tone(crypto)}. "
            f"Bitcoin-dominance coverage is {dominance_text}; ETF and flow references are news cues rather than a computed dominance series.\n\n"
            f"Precious metals and commodities: {len(gold)} gold and {len(silver)} silver headlines were found. "
            f"Gold coverage reads {self._tone(gold)}, while silver coverage reads {self._tone(silver)}; these are editorial trend cues, not live price trendlines.\n\n"
            f"Rates and duration: US 10-year yield pressure reads {yield_text} from {len(yield_items)} directly relevant headlines. "
            f"Across {len(rates)} rates-tagged items, central-bank language is {policy}.\n\n"
            f"Equities and cross-asset risk: {len(equities)} equity headlines read {self._tone(equities)}, including S&P 500 and earnings references. "
            f"Across the full sample, broad headline tone is {broad}; monitor event-driven volatility rather than treating sentiment tags as trade signals."
        )

    def run_cycle(self) -> dict[str, Any]:
        """Fetch sources concurrently and return one JSON-ready database payload."""
        results = []
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            futures = [pool.submit(self._fetch_source, name, urls)
                       for name, urls in self.SOURCES.items()]
            for future in as_completed(futures):
                try:
                    results.append(future.result())
                except Exception as exc:
                    results.append(("Unknown", [], f"OFFLINE: {str(exc)[:180]}"))
        source_order = {name: i for i, name in enumerate(self.SOURCES)}
        results.sort(key=lambda result: source_order.get(result[0], 1000))
        headlines, source_status = [], []
        seen = set()
        for source, items, status in results:
            source_status.append({"source": source, "status": status, "items": len(items)})
            for item in items:
                row = self._classify(item.get("title"), source, item.get("link", ""), item.get("published", ""))
                if not row:
                    continue
                key = row["headline"].casefold()
                if key not in seen:
                    headlines.append(row)
                    seen.add(key)
        headlines.sort(key=lambda row: (bool(row["published"]), row["published"]), reverse=True)
        headlines = headlines[:120]
        return {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "briefing": self._synthesize(headlines),
            "headlines": headlines,
            "sources": source_status,
            "source_count": len(source_status),
            "reachable_sources": sum("ONLINE" in row["status"] or row["status"].startswith("HTML FALLBACK") for row in source_status),
        }

    def scrape_and_filter(self) -> list[str]:
        """Compatibility method used by older callers."""
        result = self.run_cycle()
        return [f"[{', '.join(row['tags'])}] {row['headline']}" for row in result["headlines"]]

    def generate_macro_briefing(self) -> str:
        """Compatibility method; synthesis is deterministic and daemon-safe."""
        return self.run_cycle()["briefing"]


if __name__ == "__main__":
    import json
    print(json.dumps(MacroHarvester().run_cycle(), indent=2))
