"""Aegis background daemon: MTF market scans, Binance depth, and macro harvest."""
from __future__ import annotations

import math
import os
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

from macro_engine import MacroHarvester
from ml_memory_engine import LancasterMLEngine
from mtf_data_engine import MTFDataError, fetch_mtf_data, update_mtf_data
from mtf_strategy_engine import MTFStrategyEngine
from orderflow_engine import OrderFlowEngine
from outcome_tracker import TradeOutcomeTracker
from smc_engine import SmartMoneyEngine
from supabase_engine import SupabaseEngine
from telegram_engine import TelegramBroadcaster


TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = str(os.getenv("TELEGRAM_CHAT_ID", ""))
ML_CONFIDENCE_THRESHOLD = float(os.getenv("ML_CONFIDENCE_THRESHOLD", "0.55"))
POLL_INTERVAL_SECONDS = 5 * 60
MACRO_INTERVAL_SECONDS = 30 * 60
POST_CLOSE_GRACE_SECONDS = float(os.getenv("CANDLE_CLOSE_GRACE_SECONDS", "1.0"))
CRYPTO_SYMBOLS = [
    "BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT", "ADA/USDT:USDT",
]
SYMBOLS = ["XAU/USD", *CRYPTO_SYMBOLS]

# One full MTF fetch per asset at boot; later cycles roll each frame forward.
in_memory_cache: dict[str, dict[str, pd.DataFrame]] = {}


def seconds_until_next_close(now: float | None = None) -> float:
    current = time.time() if now is None else float(now)
    return POLL_INTERVAL_SECONDS - current % POLL_INTERVAL_SECONDS + POST_CLOSE_GRACE_SECONDS


def _asset_key(asset: Any) -> str:
    value = str(asset or "").strip().upper().replace(" PERP", "")
    if value.startswith("XAU/USD"):
        return "XAU/USD"
    return value.split(":", 1)[0]


def _clean_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _clean_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, deque)):
        return [_clean_json(v) for v in value]
    if isinstance(value, (pd.Timestamp, datetime)):
        stamp = pd.Timestamp(value)
        if stamp.tzinfo is None:
            stamp = stamp.tz_localize("UTC")
        return stamp.tz_convert("UTC").isoformat()
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if math.isfinite(float(value)) else None
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if pd.isna(value):
        return None
    return value


def _add_ml_compatibility_columns(frame: pd.DataFrame) -> pd.DataFrame:
    features_frame = frame.copy()
    if "RSI" not in features_frame.columns:
        features_frame["RSI"] = features_frame.get("RSI_14", 50.0)
    if "Hour_NY" not in features_frame.columns:
        timestamps = pd.to_datetime(features_frame["Timestamp"], utc=True)
        features_frame["Hour_NY"] = timestamps.dt.tz_convert("America/New_York").dt.hour
    return features_frame


def _evaluate_trades_for_symbol(
    tracker: TradeOutcomeTracker,
    symbol: str,
    high: float,
    low: float,
    broadcaster: TelegramBroadcaster,
    lock: threading.RLock,
) -> None:
    """Scope the existing outcome-tracker API to a single asset's OHLC."""
    with lock:
        original_load, original_save = tracker.load_active_trades, tracker.save_active_trades
        all_trades = original_load()
        key = _asset_key(symbol)
        selected = [row for row in all_trades if _asset_key(row.get("asset")) == key]
        if not selected:
            return
        unrelated = [row for row in all_trades if _asset_key(row.get("asset")) != key]
        tracker.load_active_trades = lambda: list(selected)
        tracker.save_active_trades = lambda remaining: original_save(unrelated + list(remaining))
        try:
            tracker.evaluate_open_trades(high, low, broadcaster=broadcaster)
        finally:
            tracker.load_active_trades, tracker.save_active_trades = original_load, original_save


def _smc_levels(frame: pd.DataFrame) -> list[dict[str, Any]]:
    try:
        zones = SmartMoneyEngine(frame).scan_market()
    except Exception as exc:
        print(f"SMC chart overlay calculation failed: {exc}")
        return []
    levels: list[dict[str, Any]] = []
    for _, row in zones.tail(30).iterrows():
        kind, lower, upper = None, None, None
        is_bull_fvg = row.get("Bullish_FVG", False)
        is_bear_fvg = row.get("Bearish_FVG", False)
        is_bull_ob = row.get("Bullish_OB", False)
        is_bear_ob = row.get("Bearish_OB", False)
        is_bull_fvg = False if pd.isna(is_bull_fvg) else bool(is_bull_fvg)
        is_bear_fvg = False if pd.isna(is_bear_fvg) else bool(is_bear_fvg)
        is_bull_ob = False if pd.isna(is_bull_ob) else bool(is_bull_ob)
        is_bear_ob = False if pd.isna(is_bear_ob) else bool(is_bear_ob)
        if is_bull_fvg:
            kind, lower, upper = "Bullish FVG", row.get("Prev_2_High"), row.get("Low")
        elif is_bear_fvg:
            kind, lower, upper = "Bearish FVG", row.get("High"), row.get("Prev_2_Low")
        elif is_bull_ob:
            kind, lower, upper = "Bullish Order Block", row.get("Low"), row.get("High")
        elif is_bear_ob:
            kind, lower, upper = "Bearish Order Block", row.get("Low"), row.get("High")
        if kind and pd.notna(lower) and pd.notna(upper):
            levels.append({
                "type": kind,
                "lower": float(min(lower, upper)),
                "upper": float(max(lower, upper)),
                "timestamp": row.get("Timestamp"),
            })
    return _clean_json(levels[-20:])


def _candles_for_state(frame: pd.DataFrame, limit: int = 180) -> list[dict[str, Any]]:
    columns = [column for column in ("Timestamp", "Open", "High", "Low", "Close", "Volume")
               if column in frame.columns]
    return _clean_json(frame.loc[:, columns].tail(limit).to_dict(orient="records"))


def _market_payload(
    symbol: str,
    mtf_data: dict[str, pd.DataFrame],
    strategy: MTFStrategyEngine,
    setups: list[dict[str, Any]],
) -> dict[str, Any]:
    latest_4h = mtf_data["4h"].iloc[-1]
    sweep = None
    if strategy.sweep:
        idx, side, price, label = strategy.sweep
        sweep_row = mtf_data["1h"].iloc[int(idx)]
        sweep = {"side": side, "price": float(price), "label": str(label), "timestamp": sweep_row["Timestamp"]}
    mss = strategy.mss
    mss_state = None
    if mss:
        mss_state = {"level": mss.get("level"), "timestamp": mss.get("time"), "index": mss.get("index")}
    serialized_setups = []
    for setup in setups:
        serialized_setups.append({
            **setup,
            "symbol": symbol,
            "ml_probability": setup.get("ml_probability"),
            "ml_eligible": bool(setup.get("ml_eligible", False)),
            "active": True,
        })
    return _clean_json({
        "symbol": symbol,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "bias_4h": strategy.bias or "NEUTRAL",
        "ema_50_4h": latest_4h.get("EMA_50"),
        "ema_200_4h": latest_4h.get("EMA_200"),
        "price_4h": latest_4h.get("Close"),
        "sweep_1h": sweep,
        "mss_15m": mss_state,
        "mss_15m_status": "CONFIRMED" if mss else "AWAITING",
        "setups": serialized_setups,
        "smc_levels": _smc_levels(mtf_data["5m"]),
        "candles": _candles_for_state(mtf_data["5m"]),
    })


def run_aegis_signal_loop() -> None:
    """Start nonblocking macro harvesting and run aligned five-minute scans."""
    if not 0 <= ML_CONFIDENCE_THRESHOLD <= 1:
        raise ValueError("ML_CONFIDENCE_THRESHOLD must be between 0 and 1")

    print("AEGIS DAEMON ONLINE | Binance USD-M + Gold proxy | market/orderflow 5m, macro 30m")
    db = SupabaseEngine(service_role=True)
    orderflow_engine = OrderFlowEngine("binance")
    macro_harvester = MacroHarvester()

    stop_event = threading.Event()
    scan_lock = threading.RLock()
    tracker_lock = threading.RLock()
    last_dispatched: set[tuple[str, str, str, str]] = set()
    dispatch_order: deque[tuple[str, str, str, str]] = deque()
    latest_gold_bias = {"value": "UNKNOWN (awaiting first scan)"}
    state_write_warning = {"shown": False}

    def persist_state(table: str, key: str, payload: dict[str, Any]) -> bool:
        try:
            saved = db.save_state(table, key, payload)
        except Exception as exc:
            saved = False
            print(f"Supabase state write failed for {table}/{key}: {exc!r}")
        if not saved:
            print(f"Supabase state write failed for {table}/{key}: save_state returned False")
        if not saved and not state_write_warning["shown"]:
            print("State snapshots are not persisting; configure SUPABASE_SERVICE_ROLE_KEY and apply supabase_state_tables.sql")
            state_write_warning["shown"] = True
        return saved

    def persist_states(table: str, rows: list[dict[str, Any]]) -> bool:
        try:
            saved = db.save_states(table, rows)
        except Exception as exc:
            saved = False
            print(f"Supabase state batch write failed for {table}: {exc!r}")
        if not saved:
            print(f"Supabase state batch write failed for {table}: save_states returned False")
        if not saved and not state_write_warning["shown"]:
            print("State snapshots are not persisting; configure SUPABASE_SERVICE_ROLE_KEY and apply supabase_state_tables.sql")
            state_write_warning["shown"] = True
        return saved

    # Publish nonempty startup state immediately so the read-only terminal has
    # an explicit warming-up state even while upstream providers are responding.
    startup_time = datetime.now(timezone.utc).isoformat()
    startup_writes = [
        ("aegis_market_state", [{
            "state_key": symbol, "payload": {
                "symbol": symbol, "updated_at": startup_time, "status": "STARTING",
                "bias_4h": "AWAITING", "mss_15m_status": "AWAITING",
                "setups": [], "smc_levels": [], "candles": [],
            }} for symbol in SYMBOLS]),
        ("aegis_orderflow_state", [{
            "state_key": symbol, "payload": {
                "symbol": symbol, "timestamp": startup_time,
                "status": "STARTING", "error": "Initial Binance depth poll is queued.",
            }} for symbol in SYMBOLS]),
    ]
    macro_startup_payload = {
        "updated_at": startup_time, "source_count": len(macro_harvester.SOURCES),
        "reachable_sources": 0, "sources": [], "headlines": [],
        "briefing": (
            "Digital assets: the daemon is collecting current Bitcoin, ETF-flow, and dominance headlines.\n\n"
            "Commodities and precious metals: Gold, Silver, Crude Oil, and Natural Gas coverage is being harvested.\n\n"
            "Rates and global yields: US Treasury, DXY, Federal Reserve, and ECB sources are being polled.\n\n"
            "Equities and economic calendar: S&P 500, earnings, CPI, NFP, and JOLTS coverage is being collected."
        ),
    }
    with ThreadPoolExecutor(max_workers=3) as pool:
        startup_futures = [pool.submit(persist_states, table, rows) for table, rows in startup_writes]
        startup_futures.append(pool.submit(persist_state, "aegis_macro_briefing", "latest", macro_startup_payload))
        for future in startup_futures:
            try:
                future.result()
            except Exception as exc:
                print(f"Supabase startup state prime failed: {exc}")

    def macro_loop() -> None:
        # The first harvest is run synchronously below before the daemon enters
        # its polling loop. Keep this worker on the 30-minute cadence thereafter.
        if stop_event.wait(MACRO_INTERVAL_SECONDS):
            return
        while not stop_event.is_set():
            try:
                payload = macro_harvester.run_cycle()
                saved = persist_state("aegis_macro_briefing", "latest", payload)
                if saved:
                    print(
                        "Macro briefing persisted: "
                        f"{payload.get('reachable_sources', 0)}/{payload.get('source_count', 0)} sources reachable"
                    )
                else:
                    print("Macro briefing generated; Supabase snapshot write unavailable")
            except Exception as exc:
                print(f"Macro harvest cycle failed: {exc}")
            if stop_event.wait(MACRO_INTERVAL_SECONDS):
                break

    macro_thread = threading.Thread(target=macro_loop, name="aegis-macro-harvester", daemon=True)

    broadcaster = TelegramBroadcaster(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
    # Both constructors perform a Supabase history read; overlap those waits
    # so startup scanning is not serialized behind two connection timeouts.
    with ThreadPoolExecutor(max_workers=2) as pool:
        ml_future = pool.submit(LancasterMLEngine)
        tracker_future = pool.submit(TradeOutcomeTracker)
        ml_engine = ml_future.result()
        tracker = tracker_future.result()

    def train_ml_in_background() -> None:
        try:
            print(f"ML startup training: {ml_engine.train_purged_walk_forward()}")
        except Exception as exc:
            print(f"ML startup training unavailable; fallback remains active: {exc}")

    threading.Thread(target=train_ml_in_background, name="aegis-ml-training", daemon=True).start()

    def get_status_summary() -> str:
        try:
            active = tracker.load_active_trades()
            return (f"● Open Positions: {len(active)}\n● Gold 4h Bias: {latest_gold_bias['value']}\n"
                    f"● Markets: {', '.join(SYMBOLS)}")
        except Exception as exc:
            return f"Status temporarily unavailable: {exc}"

    def get_recent_trades_summary() -> str:
        try:
            rows = tracker.ml_engine.supabase.fetch_trade_memory()
            if not rows:
                return "No completed trade outcomes are available yet."
            return "\n".join(
                f"{row.get('timestamp', 'time n/a')} | {row.get('strategy', 'strategy n/a')} | "
                f"{'WIN' if int(row.get('win_label', 0)) == 1 else 'LOSS'}"
                for row in reversed(rows[-5:])
            )
        except Exception as exc:
            return f"Trade history temporarily unavailable: {exc}"

    def scan_orderflow() -> None:
        for symbol in SYMBOLS:
            try:
                payload = orderflow_engine.scan_l2_book(symbol, limit=500)
                payload.setdefault("symbol", symbol)
                if "error" in payload:
                    payload.setdefault("updated_at", datetime.now(timezone.utc).isoformat())
                    print(f"{symbol}: orderflow unavailable: {payload['error']}")
                persist_state("aegis_orderflow_state", symbol, payload)
            except Exception as exc:
                print(f"{symbol}: orderflow persistence error: {exc}")

    def orderflow_loop() -> None:
        # The first depth scan is run synchronously before the polling loop.
        if stop_event.wait(seconds_until_next_close()):
            return
        while not stop_event.is_set():
            try:
                scan_orderflow()
            except Exception as exc:
                print(f"Orderflow cycle failed; worker remains active: {exc}")
            delay = seconds_until_next_close()
            if stop_event.wait(delay):
                break

    orderflow_thread = threading.Thread(
        target=orderflow_loop, name="aegis-binance-orderflow", daemon=True
    )

    def run_scan_cycle(source: str) -> str:
        reports: list[str] = []
        with scan_lock:
            for symbol in SYMBOLS:
                try:
                    if symbol not in in_memory_cache:
                        in_memory_cache[symbol] = fetch_mtf_data(symbol, limit=150)
                    else:
                        in_memory_cache[symbol] = update_mtf_data(in_memory_cache[symbol])
                    mtf_data = in_memory_cache[symbol]
                except MTFDataError as exc:
                    print(f"{symbol}: MTF refresh unavailable: {exc}")
                    reports.append(f"{symbol}: data unavailable")
                    continue
                except Exception as exc:
                    print(f"{symbol}: unexpected MTF error: {exc}")
                    reports.append(f"{symbol}: scan error")
                    continue

                try:
                    latest_5m = mtf_data["5m"].iloc[-1]
                    _evaluate_trades_for_symbol(
                        tracker, symbol, float(latest_5m["High"]),
                        float(latest_5m["Low"]), broadcaster, tracker_lock,
                    )
                    strategy = MTFStrategyEngine(mtf_data)
                    if symbol == "XAU/USD":
                        latest_gold_bias["value"] = strategy.bias or "NEUTRAL"
                    setups = strategy.scan_all_setups()

                    features = None
                    if setups:
                        feature_frame = _add_ml_compatibility_columns(mtf_data["5m"])
                        try:
                            features = ml_engine.extract_lancaster_features(feature_frame, len(feature_frame) - 1)
                        except Exception as exc:
                            print(f"{symbol}: ML feature extraction unavailable: {exc}")

                    for setup in setups:
                        setup["symbol"] = symbol
                        probability = None
                        if features is not None:
                            try:
                                probability = float(ml_engine.predict_win_probability(features))
                                if not 0 <= probability <= 1:
                                    probability = None
                            except Exception as exc:
                                print(f"{symbol}: ML scoring failed: {exc}")
                        setup["ml_probability"] = probability
                        setup["ml_eligible"] = probability is not None and probability >= ML_CONFIDENCE_THRESHOLD
                        setup["confluences"] = list(setup.get("confluences", []))
                        if probability is not None:
                            setup["confluences"].append(f"ML Probability of Success: {probability:.0%}")

                    state = _market_payload(symbol, mtf_data, strategy, setups)
                    state["open_positions"] = [
                        trade for trade in tracker.load_active_trades()
                        if _asset_key(trade.get("asset")) == _asset_key(symbol)
                    ]
                    state = _clean_json(state)
                    persist_state("aegis_market_state", symbol, state)

                    for setup in setups:
                        if not setup["ml_eligible"]:
                            continue
                        candle_time = pd.Timestamp(latest_5m["Timestamp"]).tz_convert("UTC").isoformat()
                        dispatch_key = (symbol, setup["strategy"], setup["action"], candle_time)
                        if dispatch_key in last_dispatched:
                            continue
                        tracker.register_trade(
                            symbol, setup["strategy"], setup["action"],
                            setup["entry"], setup["sl"], setup["tp"], features or {},
                        )
                        message = broadcaster.format_signal(
                            "XAU/USD (Gold)" if symbol == "XAU/USD" else f"{symbol} Perp",
                            setup["strategy"], setup["entry"], setup["sl"], setup["tp"],
                            setup["confluences"],
                        )
                        broadcaster.send_alert(message)
                        last_dispatched.add(dispatch_key)
                        dispatch_order.append(dispatch_key)
                        if len(dispatch_order) > 10000:
                            last_dispatched.discard(dispatch_order.popleft())

                    eligible = sum(bool(row.get("ml_eligible")) for row in setups)
                    reports.append(f"{symbol}: {len(setups)} setups, {eligible} ML eligible")
                    print(f"{source} {symbol}: {len(setups)} setup(s), {eligible} ML eligible")
                except Exception as exc:
                    print(f"{symbol}: strategy/state/dispatch failure: {exc}")
                    reports.append(f"{symbol}: evaluation error")

        return "\n".join(reports) if reports else "No markets scanned."

    broadcaster.start_command_listener(
        status_callback=get_status_summary,
        scan_callback=lambda: run_scan_cycle("Telegram /scan"),
        trades_callback=get_recent_trades_summary,
    )

    # Prime every dashboard data source before entering the timed market loop.
    try:
        run_scan_cycle("startup")
    except Exception as exc:
        print(f"Startup market scan failed; scheduled worker remains active: {exc}")
    try:
        scan_orderflow()
    except Exception as exc:
        print(f"Startup orderflow scan failed; scheduled worker remains active: {exc}")
    try:
        payload = macro_harvester.run_cycle()
        if not isinstance(payload, dict):
            raise TypeError("MacroHarvester.run_cycle() must return a dictionary payload")
        if persist_state("aegis_macro_briefing", "latest", payload):
            print(
                "Startup macro briefing persisted: "
                f"{payload.get('reachable_sources', 0)}/{payload.get('source_count', 0)} sources reachable"
            )
        else:
            print("Startup macro briefing generated, but Supabase write returned False")
    except Exception as exc:
        print(f"Startup macro harvest/persistence failed: {exc!r}")

    # Start periodic workers only after all three first-pulse tasks have run.
    macro_thread.start()
    orderflow_thread.start()

    try:
        while True:
            delay = seconds_until_next_close()
            print(f"Next Binance market/depth update in {delay:.1f}s")
            time.sleep(delay)
            try:
                run_scan_cycle("scheduled")
            except Exception as exc:
                print(f"Daemon cycle error; worker remains active: {exc}")
                time.sleep(5)
    except KeyboardInterrupt:
        stop_event.set()
        print("AEGIS daemon stopped by operator")


if __name__ == "__main__":
    run_aegis_signal_loop()
