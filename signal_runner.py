"""Aegis V3 five-minute multi-asset execution daemon."""
from __future__ import annotations

import os
import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from ml_memory_engine import LancasterMLEngine
from mtf_data_engine import MTFDataError, fetch_mtf_data, update_mtf_data
from mtf_strategy_engine import MTFStrategyEngine
from outcome_tracker import TradeOutcomeTracker
from telegram_engine import TelegramBroadcaster

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = str(os.getenv("TELEGRAM_CHAT_ID", ""))
ML_CONFIDENCE_THRESHOLD = float(os.getenv("ML_CONFIDENCE_THRESHOLD", "0.55"))
POLL_INTERVAL_SECONDS = 5 * 60
POST_CLOSE_GRACE_SECONDS = float(os.getenv("CANDLE_CLOSE_GRACE_SECONDS", "1.0"))
CRYPTO_SYMBOLS = [
    "BTC/USDT:USDT",
    "ETH/USDT:USDT",
    "SOL/USDT:USDT",
    "ADA/USDT:USDT",
]
SYMBOLS = ["XAU/USD", *CRYPTO_SYMBOLS]
# Full candle history is fetched once per process. Later cycles roll the cache
# forward using two-candle provider requests from mtf_data_engine.
in_memory_cache: dict[str, dict[str, pd.DataFrame]] = {}


def seconds_until_next_close(now: float | None = None) -> float:
    """Seconds until the next UTC five-minute boundary plus feed grace."""
    current = time.time() if now is None else float(now)
    remainder = current % POLL_INTERVAL_SECONDS
    return POLL_INTERVAL_SECONDS - remainder + POST_CLOSE_GRACE_SECONDS


def _asset_key(asset: Any) -> str:
    """Normalize historical display names and linear-perpetual symbols."""
    value = str(asset or "").strip().upper().replace(" PERP", "")
    if value.startswith("XAU/USD"):
        return "XAU/USD"
    return value.split(":", 1)[0]


def _evaluate_trades_for_symbol(
    tracker: TradeOutcomeTracker,
    symbol: str,
    high: float,
    low: float,
    broadcaster: TelegramBroadcaster,
    lock: threading.RLock,
) -> None:
    """Call the existing tracker API with only this asset's open trades.

    TradeOutcomeTracker currently evaluates all loaded trades against each OHLC
    pair and has no asset parameter. Scope its existing load/save methods for
    this call, then merge unrelated records back through its normal persistence
    method. The tracker and Supabase schemas/APIs remain unchanged.
    """
    with lock:
        original_load = tracker.load_active_trades
        original_save = tracker.save_active_trades
        all_trades = original_load()
        target_key = _asset_key(symbol)
        selected = [t for t in all_trades if _asset_key(t.get("asset")) == target_key]
        if not selected:
            return
        unrelated = [t for t in all_trades if _asset_key(t.get("asset")) != target_key]

        tracker.load_active_trades = lambda: list(selected)
        tracker.save_active_trades = lambda remaining: original_save(unrelated + list(remaining))
        try:
            tracker.evaluate_open_trades(high, low, broadcaster=broadcaster)
        finally:
            tracker.load_active_trades = original_load
            tracker.save_active_trades = original_save


def _add_ml_compatibility_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """Expose the MTF RSI and NY clock fields expected by Lancaster's extractor."""
    features_frame = frame.copy()
    if "RSI" not in features_frame.columns:
        features_frame["RSI"] = features_frame.get("RSI_14", 50.0)
    if "Hour_NY" not in features_frame.columns:
        timestamps = pd.to_datetime(features_frame["Timestamp"], utc=True)
        features_frame["Hour_NY"] = timestamps.dt.tz_convert(
            "America/New_York"
        ).dt.hour
    return features_frame


def _trade_summary(setups: list[dict], outcomes: list[tuple[dict, float | None, str]]) -> str:
    if not setups:
        return "No confirmed MTF setups."
    lines = []
    prob_by_identity = {(id(setup)): (prob, status) for setup, prob, status in outcomes}
    for setup in setups:
        probability, status = prob_by_identity.get(id(setup), (None, "not scored"))
        probability_text = f" | ML {probability:.0%}" if probability is not None else ""
        lines.append(
            f"{setup['symbol']} {setup['action']} | {setup['strategy']}"
            f" | entry {setup['entry']:.8g} | SL {setup['sl']:.8g}"
            f" | TP {setup['tp']:.8g} | RR 1:{setup['rr']:.2f}"
            f"{probability_text} [{status}]"
        )
    return "\n".join(lines)


def run_aegis_signal_loop() -> None:
    """Train once, start Telegram commands, then scan each closed 5m candle."""
    if not 0 <= ML_CONFIDENCE_THRESHOLD <= 1:
        raise ValueError("ML_CONFIDENCE_THRESHOLD must be between 0 and 1")

    print("AEGIS MTF DAEMON ONLINE | XAU/USD + Binance USD-M perpetuals")
    broadcaster = TelegramBroadcaster(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
    ml_engine = LancasterMLEngine()
    try:
        training = ml_engine.train_purged_walk_forward()
        print(f"ML startup training: {training}")
    except Exception as exc:
        print(f"ML startup training unavailable; model fallback remains active: {exc}")
    tracker = TradeOutcomeTracker()

    # Warm the complete universe once at startup. Failed symbols are retried by
    # the normal scan cycle without preventing healthy markets from starting.
    for symbol in SYMBOLS:
        try:
            in_memory_cache[symbol] = fetch_mtf_data(symbol, limit=150)
            print(f"{symbol}: primed MTF cache ({len(in_memory_cache[symbol]['5m'])} bars/timeframe)")
        except MTFDataError as exc:
            print(f"{symbol}: initial MTF cache unavailable; will retry on scan: {exc}")
        except Exception as exc:
            print(f"{symbol}: initial cache error; will retry on scan: {exc}")

    scan_lock = threading.RLock()
    tracker_lock = threading.RLock()
    last_dispatched: set[tuple[str, str, str, str]] = set()
    dispatch_order: deque[tuple[str, str, str, str]] = deque()
    latest_gold_bias = {"value": "UNKNOWN (awaiting first scan)"}

    def get_status_summary() -> str:
        try:
            active = tracker.load_active_trades()
            return (
                f"● Open Positions: {len(active)}\n"
                f"● Gold 4h Bias: {latest_gold_bias['value']}\n"
                f"● Active Markets: {', '.join(SYMBOLS)}"
            )
        except Exception as exc:
            return f"Status temporarily unavailable: {exc}"

    def get_recent_trades_summary() -> str:
        try:
            rows = tracker.ml_engine.supabase.fetch_trade_memory()
            if not rows:
                return "No completed trade outcomes are available yet."
            recent = rows[-5:]
            lines = []
            for row in reversed(recent):
                outcome = "WIN" if int(row.get("win_label", 0)) == 1 else "LOSS"
                lines.append(
                    f"{row.get('timestamp', 'time n/a')} | "
                    f"{row.get('strategy', 'strategy n/a')} | {outcome}"
                )
            return "\n".join(lines)
        except Exception as exc:
            return f"Trade history temporarily unavailable: {exc}"

    def run_scan_cycle(source: str) -> str:
        reports: list[str] = []
        with scan_lock:
            for symbol in SYMBOLS:
                try:
                    if symbol not in in_memory_cache:
                        in_memory_cache[symbol] = fetch_mtf_data(symbol, limit=150)
                    else:
                        try:
                            in_memory_cache[symbol] = update_mtf_data(
                                in_memory_cache[symbol]
                            )
                        except MTFDataError as exc:
                            # Keep the valid cache intact, but do not evaluate a
                            # stale candle or manage positions against old OHLC.
                            print(f"{symbol}: incremental refresh failed; retaining cache for retry: {exc}")
                            reports.append(f"{symbol}: refresh unavailable")
                            continue
                    mtf_data = in_memory_cache[symbol]
                except MTFDataError as exc:
                    print(f"{symbol}: MTF data unavailable: {exc}")
                    reports.append(f"{symbol}: data unavailable")
                    continue
                except Exception as exc:
                    print(f"{symbol}: unexpected data error: {exc}")
                    reports.append(f"{symbol}: scan error")
                    continue

                try:
                    latest_5m = mtf_data["5m"].iloc[-1]
                    _evaluate_trades_for_symbol(
                        tracker,
                        symbol,
                        float(latest_5m["High"]),
                        float(latest_5m["Low"]),
                        broadcaster,
                        tracker_lock,
                    )

                    strategy_engine = MTFStrategyEngine(mtf_data)
                    if symbol == "XAU/USD":
                        latest_gold_bias["value"] = strategy_engine.bias or "NEUTRAL"
                    setups = strategy_engine.scan_all_setups()
                    if not setups:
                        reports.append(f"{symbol}: 0 setups")
                        continue

                    feature_frame = _add_ml_compatibility_columns(mtf_data["5m"])
                    features = ml_engine.extract_lancaster_features(
                        feature_frame, len(feature_frame) - 1
                    )
                    accepted = 0
                    ml_eligible = 0
                    outcomes = []
                    for setup in setups:
                        setup["symbol"] = symbol
                        try:
                            win_prob = float(ml_engine.predict_win_probability(features))
                        except Exception as exc:
                            print(f"{symbol} ML scoring failed; setup suppressed: {exc}")
                            outcomes.append((setup, None, "ML scoring error"))
                            continue
                        if not (0.0 <= win_prob <= 1.0):
                            print(f"{symbol} returned invalid ML probability {win_prob}; setup suppressed")
                            outcomes.append((setup, None, "invalid ML probability"))
                            continue
                        if win_prob < ML_CONFIDENCE_THRESHOLD:
                            outcomes.append((setup, win_prob, "below ML threshold"))
                            continue

                        setup["confluences"].append(
                            f"ML Probability of Success: {win_prob:.0%}"
                        )
                        ml_eligible += 1
                        candle_time = pd.Timestamp(latest_5m["Timestamp"]).tz_convert("UTC").isoformat()
                        dispatch_key = (
                            symbol,
                            setup["strategy"],
                            setup["action"],
                            candle_time,
                        )
                        if dispatch_key in last_dispatched:
                            outcomes.append((setup, win_prob, "already processed this candle"))
                            continue

                        tracker.register_trade(
                            symbol, setup["strategy"], setup["action"],
                            setup["entry"], setup["sl"], setup["tp"], features,
                        )
                        asset_label = "XAU/USD (Gold)" if symbol == "XAU/USD" else f"{symbol} Perp"
                        message = broadcaster.format_signal(
                            asset_label,
                            setup["strategy"],
                            setup["entry"],
                            setup["sl"],
                            setup["tp"],
                            setup["confluences"],
                        )
                        broadcaster.send_alert(message)
                        last_dispatched.add(dispatch_key)
                        dispatch_order.append(dispatch_key)
                        if len(dispatch_order) > 10000:
                            expired = dispatch_order.popleft()
                            last_dispatched.discard(expired)
                        accepted += 1
                        outcomes.append((setup, win_prob, "registered and alerted"))

                    status = (
                        "ML accepted"
                        if accepted
                        else "already processed this candle"
                        if ml_eligible
                        else f"below {ML_CONFIDENCE_THRESHOLD:.0%} ML threshold"
                    )
                    reports.append(f"{symbol}: {accepted}/{len(setups)} accepted ({status})")
                    reports.append(_trade_summary(setups, outcomes))
                    print(f"{source} {symbol}: {accepted}/{len(setups)} setup(s) passed ML gate")
                except Exception as exc:
                    print(f"{symbol}: evaluation/dispatch error: {exc}")
                    reports.append(f"{symbol}: evaluation error")

        return "\n".join(reports) if reports else "No markets scanned."

    def trigger_scan() -> str:
        return run_scan_cycle("Telegram /scan")

    broadcaster.start_command_listener(
        status_callback=get_status_summary,
        scan_callback=trigger_scan,
        trades_callback=get_recent_trades_summary,
    )

    while True:
        pause = seconds_until_next_close()
        print(f"Next closed-candle scan in {pause:.1f}s")
        time.sleep(pause)
        try:
            run_scan_cycle("scheduled")
        except Exception as exc:
            # Isolate a failed full cycle and keep the 24/7 worker alive.
            print(f"Daemon cycle error: {exc}")
            time.sleep(5)


if __name__ == "__main__":
    try:
        run_aegis_signal_loop()
    except KeyboardInterrupt:
        print("AEGIS MTF daemon stopped by operator.")
