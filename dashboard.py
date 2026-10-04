"""Read-only Streamlit terminal for daemon-persisted Aegis state."""
from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from supabase_engine import SupabaseEngine


st.set_page_config(
    page_title="AEGIS // Institutional Terminal",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&display=swap');
* { font-family: 'JetBrains Mono', monospace !important; }
.stApp { background:#06090e; color:#8b9bb4; }
.block-container { padding: .8rem 1.1rem 1rem !important; max-width:100% !important; }
.terminal-header { display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid #141e2e; padding-bottom:8px; margin-bottom:12px; }
.terminal-title { color:#fff; font-size:15px; font-weight:700; letter-spacing:1.3px; }
.hud-card,.hud-card-green,.hud-card-red,.hud-card-yellow { background:#090e17; border:1px solid #141e2e; border-left:3px solid #00f0ff; padding:10px 14px; border-radius:2px; margin-bottom:8px; min-height:68px; overflow-wrap:anywhere; }
.hud-card-green { border-left-color:#00e676; } .hud-card-red { border-left-color:#ff2a5f; } .hud-card-yellow { border-left-color:#ffd600; }
.hud-label { font-size:10px; color:#71839e; text-transform:uppercase; letter-spacing:.8px; }
.hud-value { font-size:15px; font-weight:700; color:#e6f1ff; margin-top:4px; }
.section-label { color:#00f0ff; font-size:12px; font-weight:700; margin:8px 0; }
[data-testid="stDataFrame"] { max-width:100%; overflow-x:auto; }
.stTabs [data-baseweb="tab-list"] { gap:4px; border-bottom:1px solid #141e2e; }
.stTabs [data-baseweb="tab"] { background:#090e17; border:1px solid #141e2e; color:#8192ab; font-size:10px; padding:5px 10px; }
.stTabs [aria-selected="true"] { background:#0d1522 !important; color:#00f0ff !important; border-top:2px solid #00f0ff !important; }
@media (max-width:700px) { .block-container { padding-left:.4rem !important; padding-right:.4rem !important; } .stTabs [data-baseweb="tab"] { font-size:8px; padding:4px 5px; } }
</style>
""", unsafe_allow_html=True)

db = SupabaseEngine()


def _payload(row: dict[str, Any]) -> dict[str, Any]:
    value = row.get("payload", {})
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return {}
    return value if isinstance(value, dict) else {}


@st.cache_data(ttl=12, show_spinner=False)
def _load_state_rows(table: str) -> list[dict[str, Any]]:
    try:
        return db.load_states(table, limit=100)
    except Exception:
        return []


@st.cache_data(ttl=12, show_spinner=False)
def _load_active_trades() -> list[dict[str, Any]]:
    try:
        rows = db.load_active_trades()
        return rows if isinstance(rows, list) else []
    except Exception:
        return []


@st.cache_data(ttl=30, show_spinner=False)
def _load_trade_memory() -> list[dict[str, Any]]:
    try:
        rows = db.fetch_trade_memory()
        return rows if isinstance(rows, list) else []
    except Exception:
        return []


@st.cache_data(ttl=12, show_spinner=False)
def _load_dashboard_snapshot() -> dict[str, Any]:
    """Read independent REST resources concurrently on page load."""
    jobs = {
        "market": lambda: _load_state_rows("aegis_market_state"),
        "orderflow": lambda: _load_state_rows("aegis_orderflow_state"),
        "macro": lambda: _load_state_rows("aegis_macro_briefing"),
        "positions": _load_active_trades,
        "memory": _load_trade_memory,
    }
    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        futures = {key: pool.submit(call) for key, call in jobs.items()}
        return {key: future.result() for key, future in futures.items()}


def _asset_key(value: Any) -> str:
    text = str(value or "").strip().upper().replace(" PERP", "")
    return "XAU/USD" if text.startswith(("XAU", "GOLD")) else text.split(":", 1)[0]


def _metric_card(label: str, value: Any, style: str = "hud-card") -> None:
    st.markdown(
        f"<div class='{style}'><div class='hud-label'>{label}</div>"
        f"<div class='hud-value'>{value}</div></div>",
        unsafe_allow_html=True,
    )


def _rows_for_table(rows: list[dict[str, Any]], columns: list[str] | None = None) -> None:
    if not rows:
        st.info("No persisted records are available yet.")
        return
    frame = pd.DataFrame(rows)
    if columns:
        available = [column for column in columns if column in frame.columns]
        if available:
            frame = frame.loc[:, available]
    st.dataframe(frame, use_container_width=True, hide_index=True)


def _safe_float(value: Any) -> float | None:
    try:
        number = float(value)
        return number if np.isfinite(number) else None
    except (TypeError, ValueError):
        return None


snapshot = _load_dashboard_snapshot()


def _map_rows(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    states = {}
    for row in rows:
        key = str(row.get("state_key", "")).strip()
        value = _payload(row)
        if key and value and key not in states:
            value.setdefault("updated_at", row.get("updated_at"))
            states[key] = value
    return states


market_states = _map_rows(snapshot["market"])
orderflow_states = _map_rows(snapshot["orderflow"])
macro_rows = snapshot["macro"]
macro_state = _payload(macro_rows[0]) if macro_rows else {}
active_trades = snapshot["positions"]
trade_memory = snapshot["memory"]

symbols = sorted(set(market_states) | set(orderflow_states))
if not symbols:
    symbols = ["XAU/USD", "BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT", "ADA/USDT:USDT"]
selected_symbol = st.selectbox(
    "MARKET SNAPSHOT",
    symbols,
    index=symbols.index("XAU/USD") if "XAU/USD" in symbols else 0,
    label_visibility="collapsed",
)
market = market_states.get(selected_symbol, {})
flow = orderflow_states.get(selected_symbol, {})
matching_positions = [row for row in active_trades if _asset_key(row.get("asset")) == _asset_key(selected_symbol)]

st.markdown(f"""
<div class="terminal-header">
  <div class="terminal-title">AEGIS PRO // BINANCE INSTITUTIONAL COMMAND DESK <span style="color:#00f0ff;font-size:10px">V3</span></div>
  <div style="font-size:10px;color:#00e676">● READ-ONLY SNAPSHOTS · MARKET STATES {len(market_states)} · L2 STATES {len(orderflow_states)}</div>
</div>
""", unsafe_allow_html=True)

headline_cols = st.columns(4)
with headline_cols[0]: _metric_card("ACTIVE MARKET", selected_symbol)
with headline_cols[1]: _metric_card("4H MACRO BIAS", market.get("bias_4h", "AWAITING"), "hud-card-green" if market.get("bias_4h") == "LONG" else "hud-card-red" if market.get("bias_4h") == "SHORT" else "hud-card")
with headline_cols[2]: _metric_card("15M MSS", market.get("mss_15m_status", "AWAITING"))
with headline_cols[3]: _metric_card("OPEN POSITIONS", len(matching_positions))

tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
    "[ 01 // LIVE CHART ]", "[ 02 // MTF RADAR ]", "[ 03 // RISK MONITOR ]",
    "[ 04 // MACRO BRIEFING ]", "[ 05 // PROP MATRIX ]",
    "[ 06 // ORDER FLOW ]", "[ 07 // ML MEMORY ]",
])


with tab1:
    st.markdown("<div class='section-label'>LIVE BINANCE / GOLD-PROXY CANDLE FEED · 5M</div>", unsafe_allow_html=True)
    candle_rows = market.get("candles", [])
    if not candle_rows:
        st.info("No daemon candle snapshot has been persisted for this market yet.")
    else:
        candles = pd.DataFrame(candle_rows)
        required = {"Timestamp", "Open", "High", "Low", "Close"}
        if not required.issubset(candles.columns):
            st.warning("The saved market snapshot does not contain valid OHLC candles.")
        else:
            candles["Timestamp"] = pd.to_datetime(candles["Timestamp"], utc=True, errors="coerce")
            for column in ("Open", "High", "Low", "Close"):
                candles[column] = pd.to_numeric(candles[column], errors="coerce")
            candles = candles.dropna(subset=list(required)).sort_values("Timestamp")
            if candles.empty:
                st.info("The current market snapshot contains no valid candle rows.")
            else:
                fig = go.Figure(data=[go.Candlestick(
                    x=candles["Timestamp"], open=candles["Open"], high=candles["High"],
                    low=candles["Low"], close=candles["Close"], name=selected_symbol,
                    increasing_line_color="#00e676", decreasing_line_color="#ff2a5f",
                )])
                x0, x1 = candles["Timestamp"].iloc[0], candles["Timestamp"].iloc[-1]
                for zone in market.get("smc_levels", []) or []:
                    low, high = _safe_float(zone.get("lower")), _safe_float(zone.get("upper"))
                    if low is None or high is None:
                        continue
                    bullish = "bullish" in str(zone.get("type", "")).lower()
                    color = "rgba(0,230,118,0.16)" if bullish else "rgba(255,42,95,0.14)"
                    fig.add_shape(type="rect", xref="x", yref="y", x0=x0, x1=x1,
                                  y0=low, y1=high, fillcolor=color,
                                  line={"color": color, "width": 1})
                sweep = market.get("sweep_1h") or {}
                sweep_price = _safe_float(sweep.get("price"))
                if sweep_price is not None:
                    fig.add_hline(y=sweep_price, line_dash="dot", line_color="#ffd600",
                                  annotation_text=f"1H {sweep.get('label', 'LIQUIDITY SWEEP')}")
                setups = market.get("setups", []) or []
                for setup in setups:
                    for key, color, dash in (("entry", "#00f0ff", "solid"), ("sl", "#ff2a5f", "dash"), ("tp", "#00e676", "dash")):
                        price = _safe_float(setup.get(key))
                        if price is not None:
                            fig.add_hline(y=price, line_color=color, line_dash=dash,
                                          annotation_text=f"{setup.get('strategy', 'Setup')} {key.upper()}")
                for position in matching_positions:
                    for key, color in (("entry", "#00f0ff"), ("sl", "#ff2a5f"), ("tp", "#00e676")):
                        price = _safe_float(position.get(key))
                        if price is not None:
                            fig.add_hline(y=price, line_color=color, line_dash="dot",
                                          annotation_text=f"OPEN {key.upper()} · {position.get('strategy', '')}")
                fig.update_layout(
                    template="plotly_dark", height=590, paper_bgcolor="#06090e",
                    plot_bgcolor="#06090e", margin={"l": 30, "r": 20, "t": 24, "b": 30},
                    xaxis_rangeslider_visible=False, legend_orientation="h",
                    xaxis_title="UTC", yaxis_title="Price",
                )
                fig.update_xaxes(showgrid=True, gridcolor="#141e2e")
                fig.update_yaxes(showgrid=True, gridcolor="#141e2e", side="right")
                st.plotly_chart(fig, use_container_width=True, theme=None, config={"displayModeBar": False})
                st.caption(f"Snapshot {market.get('updated_at', 'time unavailable')} · candles and overlays are daemon-persisted.")


with tab2:
    st.markdown("<div class='section-label'>TOP-DOWN STRUCTURE · 4H → 1H → 15M → 5M</div>", unsafe_allow_html=True)
    cards = st.columns(4)
    with cards[0]: _metric_card("4H BIAS", market.get("bias_4h", "AWAITING"))
    with cards[1]: _metric_card("4H EMA 50 / 200", f"{market.get('ema_50_4h', '—')} / {market.get('ema_200_4h', '—')}")
    sweep = market.get("sweep_1h") or {}
    with cards[2]: _metric_card("1H LIQUIDITY", f"{sweep.get('label', 'No recent sweep')} · {sweep.get('price', '—')}")
    with cards[3]: _metric_card("15M MSS", market.get("mss_15m_status", "AWAITING"))
    st.markdown("**ACTIVE SETUPS**")
    setup_rows = market.get("setups", []) or []
    if setup_rows:
        st.dataframe(pd.DataFrame(setup_rows), use_container_width=True, hide_index=True)
    else:
        st.info("No confirmed top-down setups are currently persisted.")
    st.markdown("**OPEN POSITIONS · SUPABASE**")
    _rows_for_table(matching_positions)
    st.markdown("**MONITORED MARKETS**")
    radar_rows = []
    for symbol, state in market_states.items():
        radar_rows.append({
            "Symbol": symbol,
            "4H Bias": state.get("bias_4h", "—"),
            "1H Sweep": (state.get("sweep_1h") or {}).get("label", "—"),
            "15M MSS": state.get("mss_15m_status", "—"),
            "Setups": len(state.get("setups", []) or []),
            "Updated": state.get("updated_at", "—"),
        })
    _rows_for_table(radar_rows)


with tab3:
    st.markdown("<div class='section-label'>EMPIRICAL OUTCOME MONITOR · SUPABASE TRADE MEMORY</div>", unsafe_allow_html=True)
    outcomes = pd.DataFrame(trade_memory)
    if outcomes.empty or "win_label" not in outcomes:
        st.info("Risk statistics will populate after completed trade outcomes are stored.")
    else:
        outcomes["win_label"] = pd.to_numeric(outcomes["win_label"], errors="coerce")
        valid = outcomes.dropna(subset=["win_label"]).copy()
        valid["win_label"] = valid["win_label"].astype(int)
        total = len(valid)
        rate = 100 * valid["win_label"].mean() if total else 0
        cols = st.columns(4)
        with cols[0]: _metric_card("CLOSED TRADES", total)
        with cols[1]: _metric_card("EMPIRICAL WIN RATE", f"{rate:.1f}%", "hud-card-green")
        with cols[2]: _metric_card("WIN / LOSS", f"{int(valid.win_label.sum())} / {int(total-valid.win_label.sum())}")
        rr = pd.to_numeric(valid.get("risk_reward", pd.Series(dtype=float)), errors="coerce").dropna()
        with cols[3]: _metric_card("MEAN REALIZED R:R", f"{rr.mean():.2f}" if not rr.empty else "—")
        if total:
            equity = valid["win_label"].map(lambda value: 1.0 if value else -1.0).cumsum()
            st.line_chart(equity.reset_index(drop=True), height=240, color="#00f0ff")
        st.caption("This view summarizes recorded outcomes; the dashboard does not launch simulations or change risk state.")


with tab4:
    st.markdown("<div class='section-label'>DAEMON-SYNTHESIZED GLOBAL MARKET OBSERVATION</div>", unsafe_allow_html=True)
    if not macro_state:
        st.info("No macro briefing has been persisted yet. The daemon publishes a new observation every 30 minutes.")
    else:
        source_cols = st.columns(3)
        with source_cols[0]: _metric_card("UPDATED UTC", macro_state.get("updated_at", "—"))
        with source_cols[1]: _metric_card("SOURCES REACHABLE", f"{macro_state.get('reachable_sources', 0)} / {macro_state.get('source_count', 0)}")
        with source_cols[2]: _metric_card("HEADLINES", len(macro_state.get("headlines", []) or []))
        briefing = str(macro_state.get("briefing", "")).strip()
        if briefing:
            st.markdown(f"<div class='hud-card' style='white-space:pre-wrap;line-height:1.75;color:#e6f1ff'>{briefing}</div>", unsafe_allow_html=True)
        else:
            st.warning("The latest macro snapshot contains no executive briefing text.")
        st.markdown("**SOURCE HEALTH**")
        _rows_for_table(macro_state.get("sources", []) or [])
        st.markdown("**CATEGORIZED HEADLINES**")
        headline_rows = macro_state.get("headlines", []) or []
        if headline_rows:
            headlines = pd.DataFrame(headline_rows)
            st.dataframe(
                headlines,
                use_container_width=True,
                hide_index=True,
                column_config={"link": st.column_config.LinkColumn("Source link")},
            )
        else:
            st.info("No parseable macro headlines were returned in this cycle.")


with tab5:
    st.markdown("<div class='section-label'>READ-ONLY PROP PERFORMANCE MONITOR</div>", unsafe_allow_html=True)
    if not trade_memory:
        st.info("No completed trade history is available for prop-rule monitoring.")
    else:
        history = pd.DataFrame(trade_memory)
        if "timestamp" in history:
            history["timestamp"] = pd.to_datetime(history["timestamp"], utc=True, errors="coerce")
            history["date"] = history["timestamp"].dt.date
        wins = pd.to_numeric(history.get("win_label", pd.Series(dtype=float)), errors="coerce")
        losses = int((wins == 0).sum())
        n_wins = int((wins == 1).sum())
        cols = st.columns(4)
        with cols[0]: _metric_card("TRADING DAYS", history["date"].nunique() if "date" in history else "—")
        with cols[1]: _metric_card("CLOSED TRADES", n_wins + losses)
        with cols[2]: _metric_card("WIN RATE", f"{100*n_wins/max(1,n_wins+losses):.1f}%")
        with cols[3]: _metric_card("ACTIVE POSITIONS", len(active_trades))
        if "date" in history and "win_label" in history:
            daily = history.assign(result=wins).groupby("date")["result"].agg(["count", "mean"]).reset_index()
            st.dataframe(daily, use_container_width=True, hide_index=True)
        st.caption("Prop limits are displayed from completed-trade history only; no backtest is run in the web process.")


with tab6:
    st.markdown("<div class='section-label'>BINANCE L2 DEPTH PROFILE · DAEMON SNAPSHOT</div>", unsafe_allow_html=True)
    if not flow:
        st.info("No Binance order-flow snapshot has been persisted for this market yet.")
    elif flow.get("error"):
        st.warning(f"Latest order-book poll failed: {flow.get('error')}")
    else:
        bid_pct = float(np.clip(_safe_float(flow.get("bid_pressure_pct")) or 0, 0, 100))
        ask_pct = float(np.clip(_safe_float(flow.get("ask_pressure_pct")) or 0, 0, 100))
        cols = st.columns(3)
        with cols[0]: _metric_card("LIQUIDITY MAGNET", f"{(flow.get('liquidity_magnet') or {}).get('side', 'NONE')} · {((flow.get('liquidity_magnet') or {}).get('price', '—'))}", "hud-card-yellow")
        with cols[1]: _metric_card("TRAP & SQUEEZE RISK", flow.get("trap_squeeze_risk", "—"), "hud-card-red" if "RISK" in str(flow.get("trap_squeeze_risk", "")) else "hud-card-green")
        with cols[2]: _metric_card("VOLUME DELTA", f"{_safe_float(flow.get('volume_delta_pct')) or 0:+.2f} pp")
        bid_col, ask_col = st.columns(2)
        with bid_col:
            st.markdown(f"**BUY PRESSURE · {bid_pct:.2f}%**")
            st.progress(bid_pct / 100, text="Binance bid-side visible notional")
        with ask_col:
            st.markdown(f"**SELL PRESSURE · {ask_pct:.2f}%**")
            st.progress(ask_pct / 100, text="Binance ask-side visible notional")
        st.caption(f"{flow.get('source', 'Binance')} · book {flow.get('book_symbol', selected_symbol)} · updated {flow.get('timestamp', '—')}")
        wall_cols = st.columns(2)
        with wall_cols[0]:
            st.markdown("**BID DEPTH ANOMALIES · >4.5σ**")
            _rows_for_table(flow.get("spoof_walls_bids", []) or [])
        with wall_cols[1]:
            st.markdown("**ASK DEPTH ANOMALIES · >4.5σ**")
            _rows_for_table(flow.get("spoof_walls_asks", []) or [])
        with st.expander("Visible book levels"):
            left, right = st.columns(2)
            with left: st.dataframe(pd.DataFrame(flow.get("top_bids", []) or []), use_container_width=True, hide_index=True)
            with right: st.dataframe(pd.DataFrame(flow.get("top_asks", []) or []), use_container_width=True, hide_index=True)


with tab7:
    st.markdown("<div class='section-label'>LANCASTER ML MEMORY · DATABASE-RECORDED OUTCOMES</div>", unsafe_allow_html=True)
    vectors = pd.DataFrame(trade_memory)
    if vectors.empty:
        st.info("No trade vectors have been persisted to Supabase.")
    else:
        if "win_label" in vectors:
            vectors["win_label"] = pd.to_numeric(vectors["win_label"], errors="coerce")
            valid = vectors.dropna(subset=["win_label"])
        else:
            valid = pd.DataFrame()
        cols = st.columns(3)
        with cols[0]: _metric_card("RECORDED VECTORS", len(vectors))
        with cols[1]: _metric_card("CLASSIFICATION WIN RATE", f"{100*valid['win_label'].mean():.1f}%" if not valid.empty else "—", "hud-card-green")
        if not valid.empty and "strategy" in valid:
            perf = valid.groupby("strategy")["win_label"].agg(["count", "mean"]).reset_index()
            perf = perf[perf["count"] >= 2].sort_values("mean", ascending=False)
            top = str(perf.iloc[0]["strategy"]) if not perf.empty else "Insufficient samples"
        else:
            perf, top = pd.DataFrame(), "Insufficient samples"
        with cols[2]: _metric_card("TOP SETUP (≥2 TRADES)", top, "hud-card-yellow")
        st.markdown("**SETUP CLASSIFICATION PERFORMANCE**")
        _rows_for_table(perf.to_dict(orient="records"))
        st.markdown("**RECENT RECORDED VECTORS**")
        st.dataframe(vectors.tail(150), use_container_width=True, hide_index=True)
        st.caption("Model retraining runs in the background daemon; this page is a read-only view.")
