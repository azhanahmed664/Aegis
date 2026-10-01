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
            pairs = sorted(list(set(pairs)))
            if "XAU/USD" not in pairs:
                pairs.insert(0, "XAU/USD")
            return pairs
    except Exception:
        return ["XAU/USD", "BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT"]

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
    col_left, col_right = st.columns([1.2, 1.8])
    with col_left:
        st.markdown("<div style='color:#00f0ff; font-weight:700; font-size:12px; margin-bottom:8px;'>[ ICT KILLZONE TELEMETRY ]</div>", unsafe_allow_html=True)
        if st.button("EXECUTE SESSION TELEMETRY", use_container_width=True):
            df = PerpetualsEngine().fetch_futures_data(exchange.lower(), active_pair, timeframe="15m", limit=200)
            if not df.empty:
                tel = ICTKillzoneEngine(df).detect_asian_liquidity_sweeps()
                bias_class = "badge-bullish" if "Bullish" in tel.get("bias", "") else "badge-bearish" if "Bearish" in tel.get("bias", "") else "badge-neutral"
                st.markdown(f"<div class='hud-card'><div class='hud-label'>Algorithmic Session Bias</div><div style='margin-top:6px;'><span class='{bias_class}'>{tel.get('bias', 'NEUTRAL')}</span></div></div>", unsafe_allow_html=True)
                c_a, c_b = st.columns(2)
                with c_a: st.markdown(f"<div class='hud-card-green'><div class='hud-label'>Asian Session High</div><div class='hud-value'>${tel.get('asian_high', 0):,.2f}</div></div>", unsafe_allow_html=True)
                with c_b: st.markdown(f"<div class='hud-card-red'><div class='hud-label'>Asian Session Low</div><div class='hud-value'>${tel.get('asian_low', 0):,.2f}</div></div>", unsafe_allow_html=True)

        st.markdown("<div style='color:#00f0ff; font-weight:700; font-size:12px; margin:16px 0 8px 0;'>[ VOLUME PROFILE VISIBLE RANGE ]</div>", unsafe_allow_html=True)
        if st.button("CALCULATE LIQUIDITY NODES", use_container_width=True):
            df = PerpetualsEngine().fetch_futures_data(exchange.lower(), active_pair, timeframe=timeframe, limit=300)
            if not df.empty:
                prof = VolumeProfileEngine(df).calculate_profile()
                st.markdown(f"<div class='hud-card-yellow'><div class='hud-label'>Point of Control (POC)</div><div class='hud-value' style='color:#ffd600;'>${prof['poc']:,.2f}</div></div>", unsafe_allow_html=True)
                c_vah, c_val = st.columns(2)
                with c_vah: st.markdown(f"<div class='hud-card-green'><div class='hud-label'>VAH</div><div class='hud-value'>${prof['vah']:,.2f}</div></div>", unsafe_allow_html=True)
                with c_val: st.markdown(f"<div class='hud-card-red'><div class='hud-label'>VAL</div><div class='hud-value'>${prof['val']:,.2f}</div></div>", unsafe_allow_html=True)

        st.markdown("<div style='color:#00f0ff; font-weight:700; font-size:12px; margin:16px 0 8px 0;'>[ SMT DIVERGENCE SCANNER ]</div>", unsafe_allow_html=True)
        smt_bench = [p for p in universe if p != active_pair]
        smt_target = st.selectbox("BENCHMARK", smt_bench, label_visibility="collapsed")
        if st.button("SCAN SMT DIVERGENCE", use_container_width=True):
            df_a = PerpetualsEngine().fetch_futures_data(exchange.lower(), active_pair, timeframe="15m", limit=50)
            df_b = PerpetualsEngine().fetch_futures_data(exchange.lower(), smt_target, timeframe="15m", limit=50)
            if not df_a.empty and not df_b.empty:
                smt_result = SMTDivergenceScanner(active_pair.split(':')[0], df_a, smt_target.split(':')[0], df_b).scan()
                if "BEARISH SMT" in smt_result: st.markdown(f"<div class='hud-card-red'><div class='hud-label'>SMT Signal</div><div style='color:#ff2a5f; font-size:12px;'>{smt_result}</div></div>", unsafe_allow_html=True)
                elif "BULLISH SMT" in smt_result: st.markdown(f"<div class='hud-card-green'><div class='hud-label'>SMT Signal</div><div style='color:#00e676; font-size:12px;'>{smt_result}</div></div>", unsafe_allow_html=True)
                else: st.markdown(f"<div class='hud-card'><div class='hud-label'>SMT Status</div><div style='color:#8b9bb4; font-size:12px;'>{smt_result}</div></div>", unsafe_allow_html=True)

    with col_right:
        st.markdown("<div style='color:#00f0ff; font-weight:700; font-size:12px; margin-bottom:8px;'>[ STRUCTURAL ORDER BLOCKS & FAIR VALUE GAPS ]</div>", unsafe_allow_html=True)
        if st.button("RUN SMC STRUCTURAL SCAN", use_container_width=True):
            df = PerpetualsEngine().fetch_futures_data(exchange.lower(), active_pair, timeframe=timeframe, limit=120)
            if not df.empty:
                raw_zones = SmartMoneyEngine(df).scan_market()
                display_rows = []
                for _, r in raw_zones.tail(12).iterrows():
                    zone_type, zone_range = "ZONE", "-"
                    if r['Bullish_FVG']: zone_type, zone_range = "BULLISH FVG", f"${r['Prev_2_High']:,.2f} - ${r['Low']:,.2f}"
                    elif r['Bearish_FVG']: zone_type, zone_range = "BEARISH FVG", f"${r['High']:,.2f} - ${r['Prev_2_Low']:,.2f}"
                    elif r['Bullish_OB']: zone_type, zone_range = "BULLISH OB", f"Base Low: ${r['Low']:,.2f}"
                    elif r['Bearish_OB']: zone_type, zone_range = "BEARISH OB", f"Base High: ${r['High']:,.2f}"
                    display_rows.append({"TIMESTAMP": str(r['Timestamp'])[-8:-3], "TYPE": zone_type, "TRIGGER CLOSE": f"${r['Close']:,.2f}", "INEFFICIENCY BOUNDS": zone_range})
                st.dataframe(pd.DataFrame(display_rows), use_container_width=True, hide_index=True)

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
    st.markdown("<div style='color:#00f0ff; font-weight:700; font-size:12px; margin-bottom:8px;'>[ BLOOMBERG 'ECO' MACRO HARVESTER ]</div>", unsafe_allow_html=True)
    if st.button("INGEST GLOBAL RSS & EXECUTE 1.5B SYNTHESIS", use_container_width=True):
        with st.spinner("Scraping central bank news & querying local Qwen..."):
            harvester = MacroHarvester()
            briefing = harvester.generate_macro_briefing()
            st.markdown(f"""
            <div class="hud-card" style="border-left: 3px solid #00f0ff;">
                <div class="hud-label">Macro Volatility Executive Memo</div>
                <div style="color:#e6f1ff; font-size:13px; line-height:1.6; margin-top:8px;">{briefing}</div>
            </div>
            """, unsafe_allow_html=True)

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
                i1, i2 = st.columns(2)
                with i1: st.markdown(f"<div class='hud-card-green'><div class='hud-label'>Resting Bid (Buy) Delta</div><div class='hud-value'>{l2_data['bid_imbalance']}%</div></div>", unsafe_allow_html=True)
                with i2: st.markdown(f"<div class='hud-card-red'><div class='hud-label'>Resting Ask (Sell) Delta</div><div class='hud-value'>{l2_data['ask_imbalance']}%</div></div>", unsafe_allow_html=True)
                
                s1, s2 = st.columns(2)
                with s1:
                    st.markdown("<div style='color:#00e676; font-size:11px; margin-top:8px;'>SPOOF BID WALLS (FAKE SUPPORT)</div>", unsafe_allow_html=True)
                    if not l2_data['spoof_walls_bids'].empty:
                        st.dataframe(l2_data['spoof_walls_bids'], use_container_width=True, hide_index=True)
                    else: st.info("No abnormal buy depth clusters detected.")
                with s2:
                    st.markdown("<div style='color:#ff2a5f; font-size:11px; margin-top:8px;'>SPOOF ASK WALLS (FAKE RESISTANCE)</div>", unsafe_allow_html=True)
                    if not l2_data['spoof_walls_asks'].empty:
                        st.dataframe(l2_data['spoof_walls_asks'], use_container_width=True, hide_index=True)
                    else: st.info("No abnormal sell depth clusters detected.")

# -------------------------------------------------------------
# TAB 7: ML MEMORY BRAIN & REINFORCEMENT
# -------------------------------------------------------------
with tab7:
    st.markdown("<div style='color:#00f0ff; font-weight:700; font-size:12px; margin-bottom:8px;'>[ LANCASTER ML MEMORY & WALK-FORWARD BRAIN ]</div>", unsafe_allow_html=True)
    memory_file = "aegis_trade_memory.csv"
    active_file = "aegis_active_trades.json"
    
    col_m1, col_m2 = st.columns([1.5, 1])
    
    with col_m1:
        st.markdown("<div style='color:#ffffff; font-size:11px;'>RECORDED TRADE OUTCOMES MATRIX</div>", unsafe_allow_html=True)
        if os.path.exists(memory_file):
            mem_df = pd.read_csv(memory_file)
            if not mem_df.empty:
                st.dataframe(mem_df.tail(15), use_container_width=True, hide_index=True)
                
                # Performance breakdown
                total_logged = len(mem_df)
                win_rate = (mem_df['win_label'].sum() / total_logged) * 100 if total_logged > 0 else 0.0
                
                k1, k2, k3 = st.columns(3)
                with k1: st.markdown(f"<div class='hud-card'><div class='hud-label'>Total Logged Trades</div><div class='hud-value'>{total_logged}</div></div>", unsafe_allow_html=True)
                with k2: st.markdown(f"<div class='hud-card-green'><div class='hud-label'>Empirical Win Rate</div><div class='hud-value'>{win_rate:.1f}%</div></div>", unsafe_allow_html=True)
                with k3:
                    top_strat = mem_df.groupby('strategy')['win_label'].mean().idxmax() if total_logged >= 3 else "N/A"
                    st.markdown(f"<div class='hud-card-yellow'><div class='hud-label'>Dominant Setup</div><div class='hud-value' style='font-size:12px;'>{top_strat}</div></div>", unsafe_allow_html=True)
            else:
                st.info("No trades completed yet. Active runner will log outcomes here automatically.")
        else:
            st.info("Memory database not initialized yet. Run signal_runner.py to begin logging.")

    with col_m2:
        st.markdown("<div style='color:#ffffff; font-size:11px;'>ACTIVE MONITORED POSITIONS</div>", unsafe_allow_html=True)
        if os.path.exists(active_file):
            try:
                with open(active_file, "r") as f:
                    open_trades = json.load(f)
                if open_trades:
                    st.dataframe(pd.DataFrame(open_trades)[["id", "strategy", "action", "entry", "sl", "tp"]], use_container_width=True, hide_index=True)
                else:
                    st.markdown("<div class='hud-card'><div class='hud-label'>Position Status</div><div style='color:#556987; font-size:12px;'>No active positions awaiting TP/SL.</div></div>", unsafe_allow_html=True)
            except Exception:
                st.info("Active trades file idle.")
        
        st.markdown("---")
        if st.button("TRIGGER WALK-FORWARD RETRAINING", use_container_width=True):
            ml_eng = LancasterMLEngine()
            trained = ml_eng.train_model()
            if trained:
                st.success("✅ Model weights re-optimized across recorded outcomes.")
            else:
                st.warning("Minimum 20 trades required in memory before activating walk-forward fitting.")