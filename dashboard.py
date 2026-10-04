import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import numpy as np
import json
import os

from perpetuals_engine import PerpetualsEngine
from smc_engine import SmartMoneyEngine
from smt_engine import SMTDivergenceScanner
from ict_engine import ICTKillzoneEngine
from macro_engine import MacroHarvester
from chart_engine import render_streamlit_chart
from vpvr_engine import VolumeProfileEngine
from prop_engine import ProprietaryBacktester
from orderflow_engine import OrderFlowEngine
from ml_memory_engine import LancasterMLEngine
from supabase_engine import SupabaseEngine

st.set_page_config(
    page_title="AEGIS // Institutional Terminal",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Cyber-Desk Dark Monospace Styling
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&display=swap');
    * { font-family: 'JetBrains Mono', monospace !important; }
    
    .block-container {
        padding-top: 0.8rem !important;
        padding-bottom: 0rem !important;
        padding-left: 1.2rem !important;
        padding-right: 1.2rem !important;
        max-width: 100% !important;
    }
    
    .stApp {
        background-color: #06090e;
        color: #8b9bb4;
    }

    .terminal-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        border-bottom: 1px solid #141e2e;
        padding-bottom: 6px;
        margin-bottom: 10px;
    }
    .terminal-title {
        color: #ffffff;
        font-size: 15px;
        font-weight: 700;
        letter-spacing: 1.5px;
    }

    .hud-card {
        background: #090e17;
        border: 1px solid #141e2e;
        border-left: 3px solid #00f0ff;
        padding: 10px 14px;
        border-radius: 2px;
        margin-bottom: 8px;
    }
    .hud-card-red {
        background: #090e17;
        border: 1px solid #141e2e;
        border-left: 3px solid #ff2a5f;
        padding: 10px 14px;
        border-radius: 2px;
        margin-bottom: 8px;
    }
    .hud-card-green {
        background: #090e17;
        border: 1px solid #141e2e;
        border-left: 3px solid #00e676;
        padding: 10px 14px;
        border-radius: 2px;
        margin-bottom: 8px;
    }
    .hud-card-yellow {
        background: #090e17;
        border: 1px solid #141e2e;
        border-left: 3px solid #ffd600;
        padding: 10px 14px;
        border-radius: 2px;
        margin-bottom: 8px;
    }
    .hud-label {
        font-size: 10px;
        color: #556987;
        text-transform: uppercase;
        letter-spacing: 1px;
    }
    .hud-value {
        font-size: 16px;
        font-weight: 700;
        color: #e6f1ff;
        margin-top: 2px;
    }

    .stTabs [data-baseweb="tab-list"] {
        gap: 4px;
        border-bottom: 1px solid #141e2e;
    }
    .stTabs [data-baseweb="tab"] {
        background-color: #090e17;
        border: 1px solid #141e2e;
        border-bottom: none;
        color: #64748b;
        font-size: 11px;
        padding: 5px 14px;
        border-radius: 2px 2px 0 0;
    }
    .stTabs [aria-selected="true"] {
        background-color: #0d1522 !important;
        color: #00f0ff !important;
        border-top: 2px solid #00f0ff !important;
    }
    [data-testid="stDataFrame"] { max-width: 100%; overflow-x: auto; }
    @media (max-width: 700px) {
        .block-container { padding-left: .45rem !important; padding-right: .45rem !important; }
        .stTabs [data-baseweb="tab"] { font-size: 9px; padding: 4px 7px; }
    }
</style>
""", unsafe_allow_html=True)

# Top Bar Telemetry
st.markdown("""
<div class="terminal-header">
    <div class="terminal-title">🛡️ AEGIS PRO // INSTITUTIONAL COMMAND DESK <span style="color:#00f0ff; font-size:11px;">v2.8-PROD</span></div>
    <div style="font-size:11px; color:#00e676;">● CORE ENGINE ACTIVE | ML ADAPTIVE LAYER LOADED</div>
</div>
""", unsafe_allow_html=True)

@st.cache_data
def load_universe():
    try:
        with open("aegis_universe.json", "r") as f:
            data = json.load(f)
            pairs = data.get("BINANCE_USDT_PERP", []) + data.get("MEXC_USDT_PERP", [])
            defaults = ["XAU/USD", "BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT", "ADA/USDT:USDT", "XRP/USDT:USDT", "BNB/USDT:USDT", "DOGE/USDT:USDT", "LINK/USDT:USDT", "MATIC/USDT:USDT", "DOT/USDT:USDT"]
            return list(dict.fromkeys(["XAU/USD", *sorted(set(pairs)), *defaults[1:]]))
    except Exception:
            return ["XAU/USD", "BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT", "ADA/USDT:USDT", "XRP/USDT:USDT", "BNB/USDT:USDT", "DOGE/USDT:USDT", "LINK/USDT:USDT", "MATIC/USDT:USDT", "DOT/USDT:USDT"]

universe = load_universe()
default_idx = universe.index("XAU/USD") if "XAU/USD" in universe else 0

# Command Ribbon
c1, c2, c3, c4 = st.columns([2, 1.2, 1.2, 2.2])
with c1: active_pair = st.selectbox("ACTIVE CONTRACT", universe, index=default_idx, label_visibility="collapsed")
with c2: exchange = st.selectbox("EXCHANGE", ["BINANCE", "MEXC", "OANDA"], label_visibility="collapsed")
with c3: timeframe = st.selectbox("TIMEFRAME", ["5m", "15m", "1h", "4h", "1d"], index=1, label_visibility="collapsed")
with c4: mode = st.radio("CHART ENGINE", ["Advanced WebGL", "Local SMC Engine"], horizontal=True, label_visibility="collapsed")

# 7-Tab Matrix
tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
    "[ 01 // CHART FEED ]", 
    "[ 02 // ICT & SMC RADAR ]", 
    "[ 03 // ALADDIN STRESS LAB ]", 
    "[ 04 // MACRO CATALYST ]",
    "[ 05 // PROP BACKTESTER ]",
    "[ 06 // L2 ORDER FLOW ]",
    "[ 07 // ML MEMORY BRAIN ]"
])

# -------------------------------------------------------------
# TAB 1: CHART FEED
# -------------------------------------------------------------
with tab1:
    if mode == "Advanced WebGL":
        if "XAU" in active_pair.upper() or "GOLD" in active_pair.upper():
            tv_symbol = "OANDA:XAUUSD"
        else:
            clean_pair = active_pair.replace("/USDT:USDT", "USDT.P").replace("/", "")
            tv_symbol = f"{exchange}:{clean_pair}"
        
        tv_html = f"""
        <div class="tradingview-widget-container" style="height:550px;width:100%;">
          <div id="tv_chart" style="height:550px;width:100%;"></div>
          <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
          <script type="text/javascript">
          new TradingView.widget({{
            "autosize": true,
            "symbol": "{tv_symbol}",
            "interval": "{timeframe.replace('m', '').replace('h', '60').replace('1d', 'D')}",
            "timezone": "Etc/UTC",
            "theme": "dark",
            "style": "1",
            "locale": "en",
            "toolbar_bg": "#06090e",
            "enable_publishing": false,
            "hide_side_toolbar": false,
            "allow_symbol_change": true,
            "container_id": "tv_chart"
          }});
          </script>
        </div>
        """
        components.html(tv_html, height=560)
    else:
        with st.spinner("Rendering Native Local Chart..."):
            render_streamlit_chart(exchange.lower(), active_pair, timeframe=timeframe, limit=300)

# -------------------------------------------------------------
# TAB 2: ICT, SMC & VPVR RADAR
# -------------------------------------------------------------
with tab2:
    st.markdown("<div style='color:#00f0ff;font-weight:700;font-size:12px'>[ LIVE TOP-DOWN ANALYSIS // 4H → 1H → 15M → 5M ]</div>", unsafe_allow_html=True)
    if st.button("RUN LIVE MTF ANALYSIS", key="mtf_radar", use_container_width=True, type="primary"):
        try:
            from mtf_data_engine import fetch_mtf_data
            from mtf_strategy_engine import MTFStrategyEngine
            mtf = fetch_mtf_data(active_pair, limit=150)
            engine = MTFStrategyEngine(mtf)
            st.session_state["mtf_result"] = (mtf, engine.scan_all_setups(), engine.bias, engine.sweep, engine.mss)
        except Exception as exc:
            st.session_state["mtf_error"] = str(exc)
    if st.session_state.get("mtf_error"):
        st.error(f"MTF scan unavailable: {st.session_state.pop('mtf_error')}")
    if st.session_state.get("mtf_result"):
        mtf, setups, bias, sweep, mss = st.session_state["mtf_result"]
        last4h = mtf["4h"].iloc[-1]
        cols = st.columns(4)
        with cols[0]: st.markdown(f"<div class='hud-card'><div class='hud-label'>4H MACRO BIAS</div><div class='hud-value'>{bias or 'NEUTRAL'}</div></div>", unsafe_allow_html=True)
        with cols[1]: st.markdown(f"<div class='hud-card'><div class='hud-label'>4H EMA 50 / 200</div><div class='hud-value'>{last4h.get('EMA_50', np.nan):,.5g} / {last4h.get('EMA_200', np.nan):,.5g}</div></div>", unsafe_allow_html=True)
        with cols[2]: st.markdown(f"<div class='hud-card'><div class='hud-label'>1H LIQUIDITY SWEEP</div><div class='hud-value'>{sweep[3]} @ {sweep[2]:.8g}</div></div>", unsafe_allow_html=True) if sweep else st.info("No recent 1h sweep")
        with cols[3]: st.markdown(f"<div class='hud-card'><div class='hud-label'>15M MSS</div><div class='hud-value'>{'CONFIRMED' if mss else 'AWAITING'}</div></div>", unsafe_allow_html=True)
        st.markdown(f"**Qualifying 5m setups: {len(setups)}**")
        if setups: st.dataframe(pd.DataFrame(setups), use_container_width=True, hide_index=True)
        else: st.info("No setup passes all top-down confirmations.")
    st.markdown("<div style='color:#00f0ff;font-weight:700;font-size:12px;margin-top:14px'>[ OPEN POSITIONS // SUPABASE ]</div>", unsafe_allow_html=True)
    if st.button("REFRESH SUPABASE POSITIONS", key="refresh_supabase_positions"):
        try:
            from supabase_engine import SupabaseEngine
            positions = SupabaseEngine().load_active_trades()
            st.session_state["active_positions"] = positions or []
        except Exception as exc:
            st.session_state["positions_error"] = str(exc)
    if st.session_state.get("positions_error"):
        st.warning(f"Supabase positions unavailable: {st.session_state.pop('positions_error')}")
    positions = st.session_state.get("active_positions", [])
    if positions: st.dataframe(pd.DataFrame(positions), use_container_width=True, hide_index=True)
    else: st.info("No open positions loaded. Use Refresh to query Supabase.")

# -------------------------------------------------------------
# TAB 3: ALADDIN STRESS LAB
# -------------------------------------------------------------
with tab3:
    st.markdown("<div style='color:#00f0ff; font-weight:700; font-size:12px; margin-bottom:8px;'>[ MONTE CARLO LIQUIDATION & RUIN ENGINE ]</div>", unsafe_allow_html=True)
    margin_type = st.radio("MARGIN ARCHITECTURE", ["Isolated Margin (0.5% Hard Stop)", "Cross Margin (Shared Wallet Risk)"], horizontal=True)
    
    col_p1, col_p2, col_p3 = st.columns(3)
    with col_p1: trades_count = st.slider("SIMULATED TRADES", 100, 1000, 500)
    with col_p2: win_rate = st.slider("STRATEGY WIN RATE (%)", 30, 70, 45) / 100
    with col_p3: rr_ratio = st.slider("RISK TO REWARD RATIO", 1.0, 4.0, 2.0)
        
    if st.button("RUN 10,000 PATH SIMULATION", use_container_width=True):
        with st.spinner("Computing tail-risk simulation..."):
            rand = np.random.rand(10000, trades_count)
            wins = rand <= win_rate
            
            if "Cross" in margin_type:
                crashes = np.random.rand(10000, trades_count) <= 0.01
                slip = np.random.uniform(0.02, 1.0, size=(10000, trades_count))
                multipliers = np.where(wins, 1 + (0.005 * rr_ratio), 1 - 0.005)
                multipliers = np.where(~wins & crashes, 1 - slip, multipliers)
            else:
                multipliers = np.where(wins, 1 + (0.005 * rr_ratio), 1 - 0.005)
                
            equities = 10000 * np.cumprod(multipliers, axis=1)
            term = equities[:, -1]
            running_max = np.maximum.accumulate(equities, axis=1)
            running_max = np.where(running_max == 0, 1, running_max)
            drawdowns = (equities - running_max) / running_max
            max_dd = np.min(drawdowns, axis=1)
            
            r1, r2, r3 = st.columns(3)
            with r1: st.markdown(f"<div class='hud-card'><div class='hud-label'>Median Terminal Equity</div><div class='hud-value'>${np.median(term):,.2f}</div></div>", unsafe_allow_html=True)
            with r2: st.markdown(f"<div class='hud-card-red'><div class='hud-label'>Worst 99th Percentile Drawdown</div><div class='hud-value'>{np.percentile(max_dd, 1)*100:.2f}%</div></div>", unsafe_allow_html=True)
            with r3:
                ruin_pct = np.mean(max_dd <= -0.50) * 100
                st.markdown(f"<div class='hud-card-red'><div class='hud-label'>Probability of Ruin (>50% DD)</div><div class='hud-value'>{ruin_pct:.2f}%</div></div>", unsafe_allow_html=True)

# -------------------------------------------------------------
# TAB 4: MACRO CATALYST
# -------------------------------------------------------------
with tab4:
    st.markdown("<div style='color:#00f0ff;font-weight:700;font-size:12px'>[ GLOBAL MACRO & MARKET BRIEFING ]</div>", unsafe_allow_html=True)
    feeds = {
        "Federal Reserve": "https://www.federalreserve.gov/feeds/press_all.xml",
        "ECB": "https://www.ecb.europa.eu/rss/press.html",
        "Yahoo Finance BTC": "https://feeds.finance.yahoo.com/rss/2.0/headline?s=BTC-USD&region=US&lang=en-US",
        "Yahoo Finance S&P 500": "https://feeds.finance.yahoo.com/rss/2.0/headline?s=%5EGSPC&region=US&lang=en-US",
        "CoinTelegraph": "https://cointelegraph.com/rss",
        "CoinDesk": "https://www.coindesk.com/arc/outboundfeeds/rss/",
        "CNBC Business": "https://www.cnbc.com/id/10001147/device/rss/rss.html",
        "Reuters Business": "https://feeds.reuters.com/reuters/businessNews",
        "CoinMarketCal": "https://coinmarketcal.com/en/events",
        "CoinMarketCap": "https://coinmarketcap.com/headlines/news/rss/",
        "ZeroHedge": "https://feeds.feedburner.com/zerohedge/feed",
        "Trading Economics": "https://tradingeconomics.com/rss/news.aspx",
        "TheStreet": "https://www.thestreet.com/.rss/full/",
        "WatcherGuru": "https://watcher.guru/news/rss",
        "Investing.com": "https://www.investing.com/rss/news_14.rss",
        "Saxo": "https://www.home.saxo/en-gb/insights/content-hub/rss",
        "Tickmill": "https://www.tickmill.com/blog/feed/",
        "Rio Times": "https://www.riotimesonline.com/feed/",
    }
    fallback_pages = {
        "CoinMarketCal": "https://coinmarketcal.com/en/events",
        "CoinMarketCap": "https://coinmarketcap.com/headlines/news/",
        "ZeroHedge": "https://www.zerohedge.com/",
        "Trading Economics": "https://tradingeconomics.com/",
        "TheStreet": "https://www.thestreet.com/",
        "WatcherGuru": "https://watcher.guru/news",
        "Investing.com": "https://www.investing.com/news/",
        "Saxo": "https://www.home.saxo/en-gb/insights",
        "Tickmill": "https://www.tickmill.com/blog/",
        "Rio Times": "https://www.riotimesonline.com/",
    }
    categories = {
        "Crypto": {"BTC", "BITCOIN", "CRYPTO", "ETF", "DOMINANCE", "ETH", "ETHEREUM", "ALTCOIN", "TOKEN", "BLOCKCHAIN"},
        "Commodities": {"GOLD", "XAU", "SILVER", "XAG", "OIL", "CRUDE", "NATURAL GAS", "COPPER", "COMMODITY"},
        "Rates": {"YIELD", "TREASURY", "10-YEAR", "10 YEAR", "FED", "POWELL", "RATE", "HIKE", "INFLATION", "FOMC", "ECB"},
        "Equities": {"S&P", "SP500", "EQUITY", "EQUITIES", "STOCKS", "EARNINGS", "NASDAQ", "DOW JONES", "SHARES", "WALL STREET"},
    }
    positive_words = {"GAIN", "RISE", "RALLY", "SURGE", "BEAT", "GROWTH", "RECORD HIGH", "UPGRADE", "EASE", "INFLOWS"}
    negative_words = {"FALL", "DROP", "SLUMP", "MISS", "LOSS", "SELL-OFF", "FEAR", "WEAK", "DOWNGRADE", "CRISIS"}
    hawkish_words = {"HIKE", "HAWKISH", "TIGHTEN", "INFLATION", "HIGHER RATES", "RATE INCREASE"}
    dovish_words = {"CUT", "DOVISH", "EASING", "LOWER RATES", "RATE REDUCTION", "PAUSE"}

    def harvest_macro_feeds():
        import feedparser
        import requests
        from html.parser import HTMLParser
        from urllib.parse import urljoin

        stories, source_rows = [], []

        def classify(headline, link, published, source):
            headline = str(headline or "").strip()
            if not headline:
                return None
            text = headline.upper()
            tags = [name for name, words in categories.items()
                    if any(word in text for word in words)]
            up = sum(word in text for word in positive_words)
            down = sum(word in text for word in negative_words)
            hawk = sum(word in text for word in hawkish_words)
            dove = sum(word in text for word in dovish_words)
            try:
                published_text = pd.to_datetime(published, utc=True).strftime("%Y-%m-%d %H:%M UTC")
            except Exception:
                published_text = "Time unavailable"
            return {
                "Published": published_text, "Source": source,
                "Headline": headline, "Tags": ", ".join(tags) if tags else "General",
                "Keyword Hits": len(tags),
                "Headline Tone": "Positive" if up > down else "Negative" if down > up else "Neutral",
                "Rates Tone": "Hawkish" if hawk > dove else "Dovish" if dove > hawk else "Mixed",
                "Link": str(link or ""),
            }

        def scrape_page(url, source, session):
            response = session.get(url, timeout=(3, 7), headers={
                "User-Agent": "Mozilla/5.0 (compatible; AegisMacroBrief/3.0; +https://localhost)"
            })
            response.raise_for_status()
            html = response.text[:2_000_000]
            candidates = []
            try:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(html, "html.parser")
                selectors = "article h1, article h2, article h3, article a, h1 a, h2 a, h3 a, [class*=title] a"
                for node in soup.select(selectors):
                    title = node.get_text(" ", strip=True)
                    anchor = node if getattr(node, "name", "") == "a" else node.find("a", href=True)
                    href = (anchor.get("href") if anchor else "") or ""
                    if 24 <= len(title) <= 240:
                        candidates.append((title, urljoin(url, href)))
            except ImportError:
                class AnchorParser(HTMLParser):
                    def __init__(self):
                        super().__init__()
                        self.items, self.href, self.parts = [], "", []
                    def handle_starttag(self, tag, attrs):
                        if tag.lower() == "a":
                            self.href = dict(attrs).get("href", "")
                            self.parts = []
                    def handle_data(self, data):
                        if self.href:
                            self.parts.append(data)
                    def handle_endtag(self, tag):
                        if tag.lower() == "a" and self.href:
                            title = " ".join(" ".join(self.parts).split())
                            if 24 <= len(title) <= 240:
                                self.items.append((title, urljoin(url, self.href)))
                            self.href, self.parts = "", []
                parser = AnchorParser()
                parser.feed(html)
                candidates.extend(parser.items)

            output, seen = [], set()
            for title, link in candidates:
                key = title.casefold()
                if key in seen or not link.startswith(("http://", "https://")):
                    continue
                seen.add(key)
                output.append({"title": title, "link": link, "published": ""})
                if len(output) >= 20:
                    break
            return output

        session = requests.Session()
        for source, url in feeds.items():
            try:
                provider_items = []
                api_key = os.getenv("COINMARKETCAL_API_KEY", "").strip()
                if source == "CoinMarketCal" and api_key:
                    api_response = session.get(
                        "https://api.coinmarketcal.com/v2/events",
                        params={"limit": 25, "sortBy": "date_asc"},
                        headers={"x-api-key": api_key, "Accept": "application/json"},
                        timeout=(3, 8),
                    )
                    api_response.raise_for_status()
                    payload = api_response.json()
                    for event in payload.get("data", []):
                        provider_items.append({
                            "title": event.get("title", ""),
                            "link": event.get("sourceUrl") or f"https://coinmarketcal.com/en/event/{event.get('slug', '')}",
                            "published": event.get("displayedDate") or event.get("date", ""),
                        })
                    status = "API ONLINE"
                elif source == "CoinMarketCal":
                    # The public event calendar is scraped when no API key is configured.
                    provider_items = scrape_page(fallback_pages[source], source, session)
                    status = "HTML FALLBACK (API key unset)"
                else:
                    response = session.get(url, timeout=(3, 8), headers={
                        "User-Agent": "AegisTerminal/3 RSS reader"
                    })
                    response.raise_for_status()
                    parsed = feedparser.parse(response.content)
                    provider_items = [{
                        "title": getattr(item, "title", ""),
                        "link": item.get("link", ""),
                        "published": item.get("published", item.get("updated", "")),
                    } for item in parsed.entries[:25] if getattr(item, "title", "").strip()]
                    status = "RSS ONLINE"

                if not provider_items and source in fallback_pages:
                    provider_items = scrape_page(fallback_pages[source], source, session)
                    status = "HTML FALLBACK" if provider_items else "RSS EMPTY; FALLBACK EMPTY"
                source_rows.append({"Source": source, "Status": status, "Items": len(provider_items)})
                for item in provider_items[:25]:
                    story = classify(item.get("title"), item.get("link"),
                                     item.get("published"), source)
                    if story:
                        stories.append(story)
            except Exception as exc:
                fallback_error = ""
                if source in fallback_pages:
                    try:
                        fallback_items = scrape_page(fallback_pages[source], source, session)
                        if fallback_items:
                            source_rows.append({"Source": source, "Status": "HTML FALLBACK", "Items": len(fallback_items)})
                            for item in fallback_items:
                                story = classify(item["title"], item["link"], item["published"], source)
                                if story:
                                    stories.append(story)
                            continue
                    except Exception as scrape_exc:
                        fallback_error = f"; fallback: {str(scrape_exc)[:55]}"
                source_rows.append({"Source": source, "Status": f"OFFLINE: {str(exc)[:70]}{fallback_error}", "Items": 0})
        return stories, source_rows

    if st.button("HARVEST LIVE RSS & BUILD DAILY OBSERVATION", key="macro_harvest", type="primary", use_container_width=True):
        with st.spinner("Polling each market and central-bank source..."):
            st.session_state["macro_result"] = harvest_macro_feeds()
    if "macro_result" not in st.session_state:
        st.info("Poll the central-bank, market-news, crypto-event, broker-research and macro-source universe. CoinMarketCal uses COINMARKETCAL_API_KEY when configured; site scraping is the no-key fallback. RSS and HTML fallback outcomes are reported source by source.")
    else:
        stories, source_rows = st.session_state["macro_result"]
        st.dataframe(pd.DataFrame(source_rows), use_container_width=True, hide_index=True)
        if not stories:
            st.warning("No parseable headlines arrived. Review source status and retry.")
        else:
            news = pd.DataFrame(stories).sort_values(["Keyword Hits", "Published"], ascending=[False, False])
            tagged = news[news["Keyword Hits"] > 0]
            vol_score = min(100, int(100 * tagged["Keyword Hits"].clip(upper=4).sum() / max(1, len(news) * 2)))
            hawk_n = int((news["Rates Tone"] == "Hawkish").sum())
            dove_n = int((news["Rates Tone"] == "Dovish").sum())
            a,b,c,d = st.columns(4)
            with a: st.markdown(f"<div class='hud-card-yellow'><div class='hud-label'>MACRO ATTENTION</div><div class='hud-value'>{vol_score}/100</div></div>", unsafe_allow_html=True)
            with b: st.markdown(f"<div class='hud-card'><div class='hud-label'>POLICY TONE</div><div class='hud-value'>{'Hawkish' if hawk_n>dove_n else 'Dovish' if dove_n>hawk_n else 'Mixed'}</div></div>", unsafe_allow_html=True)
            with c: st.markdown(f"<div class='hud-card'><div class='hud-label'>HEADLINE BALANCE</div><div class='hud-value'>{len(tagged)} tagged / {len(news)} total</div></div>", unsafe_allow_html=True)
            reachable = sum(
                "ONLINE" in row["Status"] or
                (row["Status"].startswith("HTML FALLBACK") and row["Items"] > 0)
                for row in source_rows
            )
            with d: st.markdown(f"<div class='hud-card'><div class='hud-label'>SOURCES REACHABLE</div><div class='hud-value'>{reachable}/{len(source_rows)}</div></div>", unsafe_allow_html=True)

            def subset(category): return news[news["Tags"].str.contains(category, regex=False)]
            def directional(frame):
                if frame.empty: return "no fresh directional headline signal"
                up = int((frame["Headline Tone"] == "Positive").sum())
                down = int((frame["Headline Tone"] == "Negative").sum())
                return "headline tone leans constructive" if up > down else "headline tone leans defensive" if down > up else "headline tone is mixed"

            crypto = subset("Crypto")
            gold = news[news["Headline"].str.contains(r"gold|XAU", case=False, regex=True)]
            silver = news[news["Headline"].str.contains(r"silver|XAG", case=False, regex=True)]
            metals = pd.concat([gold, silver]).drop_duplicates()
            rates = subset("Rates")
            yields = rates[rates["Headline"].str.contains(r"10.?year|treasury|yield", case=False, regex=True)]
            equities = subset("Equities")
            dominance = news[news["Headline"].str.contains(r"dominance|BTC.D|bitcoin share", case=False, regex=True)]
            dom_read = directional(dominance) if not dominance.empty else "no direct dominance headline; " + directional(crypto)
            yield_read = directional(yields)
            if hawk_n > dove_n: yield_read += "; policy text is net hawkish"
            elif dove_n > hawk_n: yield_read += "; policy text is net dovish"
            risk_off = sum("CRISIS" in x or "SELL-OFF" in x or "RECESSION" in x for x in news["Headline"].str.upper())
            risk_on = sum("RALLY" in x or "RECORD HIGH" in x or "INFLOWS" in x for x in news["Headline"].str.upper())
            broad = "risk-off" if risk_off > risk_on else "risk-on" if risk_on > risk_off else "two-way"
            st.markdown("### Daily Market Observation")
            st.markdown(
                f"**Digital assets.** {len(crypto)} crypto headlines were captured. Bitcoin dominance: {dom_read}. ETF and flow mentions are headline signals, not a computed dominance series.\n\n"
                f"**Gold and Silver.** Gold: {directional(gold)} across {len(gold)} headlines; Silver: {directional(silver)} across {len(silver)}. Combined metals tone: {directional(metals)}. Oil and Natural Gas are included in the commodity taxonomy; these are headline cues, not price trendlines.\n\n"
                f"**Rates and duration.** US 10-Year Yield pressure: {yield_read}. {len(rates)} rates-tagged headlines were found; this is not a live Treasury quote.\n\n"
                f"**Equities and positioning.** S&P 500 and broad equity sentiment {directional(equities)} across {len(equities)} headlines, including earnings. Cross-asset headline balance is {broad}; keyword attention score is {vol_score}/100."
            )
            st.caption("Deterministic keyword-based morning note; headlines do not substitute for live price or yield data.")
            st.dataframe(news.head(75), use_container_width=True, hide_index=True, column_config={"Link": st.column_config.LinkColumn("Source link")})

# -------------------------------------------------------------
# TAB 5: PROP BACKTESTER
# -------------------------------------------------------------
with tab5:
    st.markdown("<div style='color:#00f0ff; font-weight:700; font-size:12px; margin-bottom:8px;'>[ VECTORBT PROPRIETARY STRATEGY MATRIX ]</div>", unsafe_allow_html=True)
    backtest_lookback = st.slider("HISTORICAL CANDLES TO BACKTEST", 500, 5000, 1000)
    
    if st.button("▶ EXECUTE STRATEGY MATRIX", use_container_width=True, type="primary"):
        with st.spinner("Fetching data and computing VectorBT Numba arrays..."):
            df = PerpetualsEngine().fetch_futures_data(exchange.lower(), active_pair, timeframe=timeframe, limit=backtest_lookback)
            if not df.empty:
                tester = ProprietaryBacktester(df, initial_cash=10000, fee_rate=0.0004)
                results = tester.execute_backtest()
                if results is None:
                    st.warning("No trades triggered. Adjust custom entry filters in prop_engine.py.")
                else:
                    b1, b2, b3, b4 = st.columns(4)
                    with b1: st.markdown(f"<div class='hud-card-green'><div class='hud-label'>Win Rate</div><div class='hud-value'>{results['win_rate']}%</div></div>", unsafe_allow_html=True)
                    with b2: st.markdown(f"<div class='hud-card-green'><div class='hud-label'>Profit Factor</div><div class='hud-value'>{results['profit_factor']}</div></div>", unsafe_allow_html=True)
                    with b3: st.markdown(f"<div class='hud-card-red'><div class='hud-label'>Max Drawdown</div><div class='hud-value'>{results['max_dd']}%</div></div>", unsafe_allow_html=True)
                    with b4: st.markdown(f"<div class='hud-card'><div class='hud-label'>Total Trades</div><div class='hud-value'>{results['total_trades']}</div></div>", unsafe_allow_html=True)
                    st.line_chart(results['equity_curve'], use_container_width=True, color="#00f0ff")

# -------------------------------------------------------------
# TAB 6: L2 ORDER FLOW & SPOOFING
# -------------------------------------------------------------
with tab6:
    st.markdown("<div style='color:#00f0ff; font-weight:700; font-size:12px; margin-bottom:8px;'>[ LEVEL 2 LIQUIDITY & SPOOFING RADAR ]</div>", unsafe_allow_html=True)
    if st.button("SCAN ORDER BOOK DEPTH", use_container_width=True, type="primary"):
        with st.spinner("Analyzing Limit Order Book for Manipulated Depth..."):
            flow_engine = OrderFlowEngine(exchange.lower())
            l2_data = flow_engine.scan_l2_book(active_pair, limit=500)
            
            if "error" in l2_data:
                st.error(f"Orderbook feed unavailable: {l2_data['error']}")
            else:
                bid_pct = float(np.clip(l2_data.get("bid_imbalance", 0), 0, 100))
                ask_pct = float(np.clip(l2_data.get("ask_imbalance", 0), 0, 100))
                delta = bid_pct - ask_pct
                bid_walls = l2_data.get("spoof_walls_bids", pd.DataFrame())
                ask_walls = l2_data.get("spoof_walls_asks", pd.DataFrame())
                all_walls = []
                for wall_df in (bid_walls, ask_walls):
                    if isinstance(wall_df, pd.DataFrame) and not wall_df.empty and {"Price", "Volume", "Type"}.issubset(wall_df.columns):
                        all_walls.extend(wall_df.to_dict("records"))
                magnet = max(all_walls, key=lambda row: float(row.get("Volume", 0))) if all_walls else None
                magnet_text = f"{magnet['Type']} @ {float(magnet['Price']):,.8g} · size {float(magnet['Volume']):,.4g}" if magnet else "No >4.5σ wall detected"
                if delta >= 20:
                    trap_text, trap_style = f"Short squeeze risk elevated · bid delta +{delta:.1f} pp", "hud-card-green"
                elif delta <= -20:
                    trap_text, trap_style = f"Long trap / downside squeeze risk · ask delta {delta:.1f} pp", "hud-card-red"
                else:
                    trap_text, trap_style = f"Balanced book · delta {delta:+.1f} pp", "hud-card-yellow"
                st.markdown("<style>[data-testid='stHorizontalBlock']:has([data-testid='stProgress']) [data-testid='column']:first-child [data-testid='stProgress'] [role='progressbar']>div{background:#00e676!important}[data-testid='stHorizontalBlock']:has([data-testid='stProgress']) [data-testid='column']:nth-child(2) [data-testid='stProgress'] [role='progressbar']>div{background:#ff2a5f!important}</style>", unsafe_allow_html=True)
                buy_col, sell_col = st.columns(2)
                with buy_col:
                    st.markdown(f"**BUY PRESSURE · {bid_pct:.2f}%**")
                    st.progress(bid_pct / 100, text="Bid-side visible depth")
                with sell_col:
                    st.markdown(f"**SELL PRESSURE · {ask_pct:.2f}%**")
                    st.progress(ask_pct / 100, text="Ask-side visible depth")
                m1, m2, m3 = st.columns(3)
                with m1: st.markdown(f"<div class='hud-card-yellow'><div class='hud-label'>LIQUIDITY MAGNET</div><div class='hud-value'>{magnet_text}</div></div>", unsafe_allow_html=True)
                with m2: st.markdown(f"<div class='{trap_style}'><div class='hud-label'>TRAP & SQUEEZE RISK</div><div class='hud-value'>{trap_text}</div></div>", unsafe_allow_html=True)
                with m3: st.markdown(f"<div class='hud-card'><div class='hud-label'>BOOK SOURCE</div><div class='hud-value'>{l2_data.get('source', 'Unknown')}</div></div>", unsafe_allow_html=True)
                
                s1, s2 = st.columns(2)
                with s1:
                    st.markdown("<div style='color:#00e676; font-size:11px; margin-top:8px;'>SPOOF BID WALLS (FAKE SUPPORT)</div>", unsafe_allow_html=True)
                    if not bid_walls.empty:
                        st.dataframe(bid_walls, use_container_width=True, hide_index=True)
                    else: st.info("No abnormal buy depth clusters detected.")
                with s2:
                    st.markdown("<div style='color:#ff2a5f; font-size:11px; margin-top:8px;'>SPOOF ASK WALLS (FAKE RESISTANCE)</div>", unsafe_allow_html=True)
                    if not ask_walls.empty:
                        st.dataframe(ask_walls, use_container_width=True, hide_index=True)
                    else: st.info("No abnormal sell depth clusters detected.")

# -------------------------------------------------------------
# TAB 7: ML MEMORY BRAIN & REINFORCEMENT
# -------------------------------------------------------------
with tab7:
    st.markdown("<div style='color:#00f0ff;font-weight:700;font-size:12px'>[ LANCASTER ML MEMORY & WALK-FORWARD BRAIN ]</div>", unsafe_allow_html=True)
    memory_file = "aegis_trade_memory.csv"
    active_file = "aegis_active_trades.json"
    left, right = st.columns([1.5, 1])
    with left:
        st.markdown("**RECORDED TRADE OUTCOMES // SUPABASE**")
        try:
            records = SupabaseEngine().fetch_trade_memory()
            mem_df = pd.DataFrame(records) if records else (pd.read_csv(memory_file) if os.path.exists(memory_file) else pd.DataFrame())
        except Exception:
            mem_df = pd.read_csv(memory_file) if os.path.exists(memory_file) else pd.DataFrame()
        if mem_df.empty:
            st.info("No completed trade vectors returned by Supabase or local storage.")
        else:
            if "win_label" in mem_df:
                mem_df["win_label"] = pd.to_numeric(mem_df["win_label"], errors="coerce")
                valid = mem_df.dropna(subset=["win_label"])
            else:
                valid = pd.DataFrame()
            total = len(valid)
            win_rate = float(valid["win_label"].mean()) * 100 if total else 0.0
            a,b,c = st.columns(3)
            with a: st.markdown(f"<div class='hud-card'><div class='hud-label'>COMPLETED TRADES</div><div class='hud-value'>{total}</div></div>", unsafe_allow_html=True)
            with b: st.markdown(f"<div class='hud-card-green'><div class='hud-label'>EMPIRICAL WIN RATE</div><div class='hud-value'>{win_rate:.1f}%</div></div>", unsafe_allow_html=True)
            with c:
                top = "N/A"
                if total >= 2 and "strategy" in valid:
                    rates = valid.groupby("strategy")["win_label"].agg(["mean", "count"])
                    rates = rates[rates["count"] >= 2]
                    if not rates.empty: top = str(rates["mean"].idxmax())
                st.markdown(f"<div class='hud-card-yellow'><div class='hud-label'>TOP STRATEGY (≥2)</div><div class='hud-value' style='font-size:12px'>{top}</div></div>", unsafe_allow_html=True)
            st.dataframe(mem_df.tail(100), use_container_width=True, hide_index=True)
    with right:
        st.markdown("**ACTIVE MONITORED POSITIONS // SUPABASE**")
        try:
            positions = SupabaseEngine().load_active_trades()
            if not positions and os.path.exists(active_file):
                with open(active_file, "r", encoding="utf-8") as stream: positions = json.load(stream)
            if positions: st.dataframe(pd.DataFrame(positions), use_container_width=True, hide_index=True)
            else: st.info("No active positions.")
        except Exception as exc: st.warning(f"Position query unavailable: {exc}")
        st.markdown("---")
        if st.button("RUN PURGED WALK-FORWARD RETRAINING", key="memory_retrain", use_container_width=True):
            try:
                result = LancasterMLEngine().train_purged_walk_forward()
                if result.get("status") == "Trained":
                    st.success(f"OOS accuracy {result.get('oos_accuracy', 0):.2f}% · train {result.get('train_samples', 0)} · test {result.get('test_samples', 0)}")
                else: st.warning(str(result.get("status", result)))
            except Exception as exc: st.error(f"Retraining unavailable: {exc}")
