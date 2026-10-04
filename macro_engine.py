"""Background multi-source RSS/API macro harvester and briefing synthesis."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
import json
import os
import re
from typing import Any
from urllib.parse import urljoin

import feedparser
import numpy as np
import pandas as pd
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

    @staticmethod
    def _fetch_market_context() -> dict[str, dict[str, Any]]:
        """Fetch price/range context so the briefing can state real trend levels."""
        tickers = ["BTC-USD", "GC=F", "SI=F", "CL=F", "NG=F", "^TNX", "^TYX", "DX-Y.NYB", "^GSPC"]
        try:
            import yfinance as yf
            data = yf.download(
                tickers=tickers, period="3mo", interval="1d", group_by="ticker",
                auto_adjust=True, progress=False, threads=True, timeout=8,
            )
        except Exception as exc:
            return {"_error": {"error": str(exc)[:180]}}
        output: dict[str, dict[str, Any]] = {}
        for ticker in tickers:
            try:
                close = data[ticker]["Close"] if isinstance(data.columns, pd.MultiIndex) else data["Close"]
                close = pd.to_numeric(close, errors="coerce").dropna()
                if close.empty:
                    continue
                values = close.to_numpy(dtype=float)
                tail = values[-20:]
                last = float(values[-1])
                prior_20 = values[-21:-1] if len(values) > 20 else values[:-1]
                upper = float(np.max(prior_20)) if len(prior_20) else last
                lower = float(np.min(prior_20)) if len(prior_20) else last
                scale = 0.1 if ticker in {"^TNX", "^TYX"} else 1.0
                pct_5d = ((last / float(values[-6])) - 1) * 100 if len(values) >= 6 and values[-6] else 0.0
                pct_20d = ((last / float(values[-21])) - 1) * 100 if len(values) >= 21 and values[-21] else 0.0
                state = "breakout above 20-session range" if last > upper else "breakdown below 20-session range" if last < lower else "consolidating inside 20-session range"
                output[ticker] = {
                    "last": last * scale, "change_5d_pct": pct_5d, "change_20d_pct": pct_20d,
                    "range_low_20d": float(np.min(tail)) * scale, "range_high_20d": float(np.max(tail)) * scale,
                    "state": state,
                }
            except Exception:
                continue
        return output

    @staticmethod
    def _market_line(context: dict[str, dict[str, Any]], ticker: str, label: str) -> str:
        item = context.get(ticker)
        if not item:
            return f"{label} quote context unavailable"
        return (
            f"{label} {item['state']} at {item['last']:,.4g}; "
            f"5-session {item['change_5d_pct']:+.2f}%, 20-session {item['change_20d_pct']:+.2f}%; "
            f"recent range {item['range_low_20d']:,.4g}–{item['range_high_20d']:,.4g}"
        )

    def _synthesize(self, headlines: list[dict[str, Any]], market_data: dict[str, dict[str, Any]]) -> str:
        by_tag = {tag: [item for item in headlines if tag in item["tags"]]
                  for tag in self.CATEGORIES}
        crypto, commodities = by_tag["Crypto"], by_tag["Commodities"]
        rates, equities = by_tag["Rates"], by_tag["Equities"]
        dominance = [item for item in crypto if any(word in item["headline"].upper() for word in ("DOMINANCE", "BTC.D", "BITCOIN SHARE"))]
        etf_flows = [item for item in crypto if any(word in item["headline"].upper() for word in ("ETF", "INFLOW", "OUTFLOW", "FUND FLOW"))]
        gold = [item for item in commodities if any(word in item["headline"].upper() for word in ("GOLD", "XAU"))]
        silver = [item for item in commodities if any(word in item["headline"].upper() for word in ("SILVER", "XAG"))]
        oil_news = [item for item in commodities if any(word in item["headline"].upper() for word in ("OIL", "CRUDE", "BRENT"))]
        natgas_news = [item for item in commodities if any(word in item["headline"].upper() for word in ("NATURAL GAS", "LNG", "STORAGE"))]
        yield_items = [item for item in rates if any(word in item["headline"].upper() for word in ("10-YEAR", "10 YEAR", "TREASURY", "YIELD"))]
        hawkish = sum(item["rates_tone"] == "Hawkish" for item in rates)
        dovish = sum(item["rates_tone"] == "Dovish" for item in rates)
        policy = "net hawkish" if hawkish > dovish else "net dovish" if dovish > hawkish else "two-way/mixed"
        btc = market_data.get("BTC-USD", {})
        dominance_text = self._tone(dominance) if dominance else "no direct dominance reading in the source sample"
        flow_text = self._tone(etf_flows) if etf_flows else "no directional ETF flow headline was captured"
        breakout = btc.get("state", "price state unavailable")
        if "breakout" in breakout:
            btc_note = "momentum has cleared its prior 20-session ceiling"
        elif "breakdown" in breakout:
            btc_note = "price has slipped below its prior 20-session floor"
        elif "consolidating" in breakout:
            btc_note = "price remains inside its recent 20-session range"
        else:
            btc_note = "price structure could not be confirmed from the market feed"
        btc_stats = self._market_line(market_data, "BTC-USD", "Bitcoin")
        gold_stats = self._market_line(market_data, "GC=F", "Gold")
        silver_stats = self._market_line(market_data, "SI=F", "Silver")
        oil_stats = self._market_line(market_data, "CL=F", "WTI crude")
        gas_stats = self._market_line(market_data, "NG=F", "Natural Gas")
        ten_year = self._market_line(market_data, "^TNX", "US 10-Year Treasury yield")
        thirty_year = self._market_line(market_data, "^TYX", "US 30-Year Treasury yield")
        dxy = self._market_line(market_data, "DX-Y.NYB", "DXY")
        spx = self._market_line(market_data, "^GSPC", "S&P 500")
        geo = sum(any(term in row["headline"].upper() for term in ("WAR", "IRAN", "MIDDLE EAST", "GEOPOLIT", "SANCTION", "SHIPPING")) for row in oil_news)
        seasonality = sum(any(term in row["headline"].upper() for term in ("WINTER", "SUMMER", "SEASONAL", "STORAGE", "WEATHER", "HEATING")) for row in natgas_news)
        tone = self._tone(headlines)
        policy_news = "Fed and ECB language leans " + policy if rates else "Fed/ECB policy posture is not explicit in the current headline set"
        cal_terms = [term for term in ("CPI", "NFP", "JOLTS") if any(term in row["headline"].upper() for row in headlines)]
        calendar = ", ".join(cal_terms) if cal_terms else "CPI, NFP, and JOLTS remain the scheduled event-risk watchlist; source headlines contained no confirmed release date"
        return (
            f"DIGITAL ASSETS — {btc_stats}. Bitcoin is {btc_note}. ETF net-flow headlines ({len(etf_flows)}) lean {flow_text}; "
            f"that flow read is editorial rather than a measured fund-flow total. Bitcoin-dominance coverage is {dominance_text}, "
            f"so sustained BTC leadership would imply a relative headwind for altcoins, while easing dominance would improve their breadth backdrop.\n\n"
            f"COMMODITIES & PRECIOUS METALS — {gold_stats}; {silver_stats}. The recent 20-session ranges provide working bounce/rejection bands, "
            f"not technical support guarantees. {oil_stats}; {geo} oil headlines referenced geopolitical or shipping risk. {gas_stats}; "
            f"{seasonality} Natural Gas headlines referenced weather, storage, or seasonal demand, which are the key seasonal catalysts in this sample.\n\n"
            f"RATES & GLOBAL YIELDS — {ten_year}; {thirty_year}; {dxy}. {policy_news}. Rising yield and dollar momentum would tighten financial conditions "
            f"and pressure duration-sensitive risk assets; falling yields or a softer dollar would ease that cross-asset constraint. "
            f"Rates-source tone was {self._tone(rates)} across {len(rates)} tagged headlines.\n\n"
            f"EQUITIES & ECONOMIC CALENDAR — {spx}. S&P 500 index direction is a price proxy, not constituent advance/decline breadth; "
            f"earnings and broad equity headlines ({len(equities)}) read {self._tone(equities)}. Calendar watch: {calendar}. "
            f"Across all harvested headlines, cross-asset tone is {tone}; treat these observations as context and verify scheduled release times before event risk."
        )

    @staticmethod
    def _ai_briefing(deterministic: str, headlines: list[dict[str, Any]], market_data: dict[str, dict[str, Any]]) -> str:
        """Optionally refine the four factual pillars with the configured AI API."""
        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        if not api_key:
            return deterministic
        try:
            from openai import OpenAI
            client = OpenAI(api_key=api_key, timeout=9.0, max_retries=0)
            evidence = {
                "price_context": market_data,
                "headlines": [{"source": row["source"], "headline": row["headline"], "tags": row["tags"]}
                              for row in headlines[:50]],
                "rule_based_note": deterministic,
            }
            response = client.chat.completions.create(
                model=os.getenv("AEGIS_MACRO_MODEL", "gpt-4o-mini"),
                temperature=0.2,
                max_tokens=1100,
                messages=[
                    {"role": "system", "content": (
                        "Write an institutional morning market note in exactly four paragraphs. "
                        "Use these four paragraph headings in order: DIGITAL ASSETS, COMMODITIES & PRECIOUS METALS, "
                        "RATES & GLOBAL YIELDS, EQUITIES & ECONOMIC CALENDAR. Base all claims only on supplied evidence. "
                        "Never invent ETF flow amounts, dominance percentages, yield levels, price levels, breadth, or calendar dates. "
                        "State when a requested measurement is unavailable. Keep the tone concise, analytical, and non-promotional."
                    )},
                    {"role": "user", "content": json.dumps(evidence, ensure_ascii=False)},
                ],
            )
            text = str(response.choices[0].message.content or "").strip()
            paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
            return "\n\n".join(paragraphs) if len(paragraphs) == 4 else deterministic
        except Exception as exc:
            print(f"Macro AI synthesis unavailable; deterministic briefing retained: {exc}")
            return deterministic

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
        market_data = self._fetch_market_context()
        briefing = self._synthesize(headlines, market_data)
        briefing = self._ai_briefing(briefing, headlines, market_data)
        return {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "briefing": briefing,
            "market_data": market_data,
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
