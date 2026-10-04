"""Top-down SMC/ICT strategy matrix for synchronized OHLCV frames.

The scanner is deliberately confirmation-only: it evaluates closed, UTC-stamped
bars and requires a 4h structural/EMA bias, a 1h context, and 15m confirmation
before a 5m trigger can produce a setup. Signals are research candidates, not
orders; execution costs and venue-specific spread should be supplied by caller.
"""
from __future__ import annotations

from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

TIMEFRAMES = ("4h", "1h", "15m", "5m")
REQUIRED = {"Timestamp", "Open", "High", "Low", "Close", "Volume"}
RR_FLOOR = 2.5
PIVOT_RADIUS = 2


class MTFStrategyEngine:
    """Scan one asset's aligned MTF data and return confirmed setup candidates."""

    def __init__(self, mtf_data: dict[str, pd.DataFrame]):
        missing = set(TIMEFRAMES) - set(mtf_data)
        if missing:
            raise ValueError(f"Missing timeframes: {sorted(missing)}")
        self.data = {}
        for tf in TIMEFRAMES:
            frame = mtf_data[tf].copy()
            absent = REQUIRED - set(frame.columns)
            if absent:
                raise ValueError(f"{tf} missing columns: {sorted(absent)}")
            frame["Timestamp"] = pd.to_datetime(frame["Timestamp"], utc=True, errors="raise")
            frame = frame.sort_values("Timestamp").drop_duplicates("Timestamp", keep="last")
            frame = frame.reset_index(drop=True)
            if len(frame) < 30 or not np.isfinite(
                frame[["Open", "High", "Low", "Close"]].to_numpy(dtype=float)
            ).all():
                raise ValueError(f"{tf} needs at least 30 valid OHLC candles")
            self.data[tf] = frame
        symbols = [f.attrs.get("symbol") for f in mtf_data.values() if f.attrs.get("symbol")]
        self.symbol = symbols[0] if symbols else str(mtf_data.get("symbol", "UNKNOWN"))
        self.spread_buffer = self._read_spread_buffer(mtf_data)
        self.bias = self._macro_bias()
        self.sweep = self._latest_sweep()
        self.mss = self._mss_after_sweep()

    def _read_spread_buffer(self, source):
        """Prefer caller's quoted spread; absent quote, use conservative range proxy."""
        for frame in source.values():
            if isinstance(frame, pd.DataFrame) and frame.attrs.get("spread") is not None:
                try:
                    value = float(frame.attrs["spread"])
                    if np.isfinite(value) and value >= 0:
                        return value
                except (TypeError, ValueError):
                    pass
        f = self.data["5m"].tail(50)
        # OHLC does not contain bid/ask; a modest volatility-scaled buffer is explicit fallback.
        return float((f["High"] - f["Low"]).median() * 0.05)

    @staticmethod
    def _pivots(frame, radius=PIVOT_RADIUS):
        high = frame["High"].to_numpy(float)
        low = frame["Low"].to_numpy(float)
        highs, lows = [], []
        for i in range(radius, len(frame) - radius):
            if high[i] == np.max(high[i-radius:i+radius+1]) and np.count_nonzero(
                high[i-radius:i+radius+1] == high[i]
            ) == 1:
                highs.append((i, float(high[i])))
            if low[i] == np.min(low[i-radius:i+radius+1]) and np.count_nonzero(
                low[i-radius:i+radius+1] == low[i]
            ) == 1:
                lows.append((i, float(low[i])))
        return highs, lows

    @staticmethod
    def _atr(frame, period=14):
        previous = frame["Close"].shift(1)
        tr = pd.concat([
            frame["High"] - frame["Low"],
            (frame["High"] - previous).abs(),
            (frame["Low"] - previous).abs(),
        ], axis=1).max(axis=1)
        return tr.rolling(period, min_periods=period).mean()

    def _macro_bias(self):
        f = self.data["4h"]
        highs, lows = self._pivots(f)
        if len(highs) < 2 or len(lows) < 2:
            return None
        higher_highs = highs[-1][1] > highs[-2][1]
        higher_lows = lows[-1][1] > lows[-2][1]
        lower_highs = highs[-1][1] < highs[-2][1]
        lower_lows = lows[-1][1] < lows[-2][1]
        row = f.iloc[-1]
        ema50 = row.get("EMA_50", f["Close"].ewm(span=50, adjust=False).mean().iloc[-1])
        ema200 = row.get("EMA_200", f["Close"].ewm(span=200, adjust=False).mean().iloc[-1])
        if higher_highs and higher_lows and row.Close > ema50 > ema200:
            return "LONG"
        if lower_highs and lower_lows and row.Close < ema50 < ema200:
            return "SHORT"
        return None

    def _major_levels(self, frame, lookback=50):
        highs, lows = self._pivots(frame.tail(lookback).reset_index(drop=True))
        offset = max(0, len(frame) - lookback)
        return ([(i + offset, p) for i, p in highs],
                [(i + offset, p) for i, p in lows])

    def _session_levels(self, frame):
        f = frame.copy()
        dates = f.Timestamp.dt.date
        latest_date = dates.iloc[-1]
        prior = f.loc[dates < latest_date]
        if prior.empty:
            return None, None
        session = prior.loc[dates.loc[prior.index] == prior.Timestamp.dt.date.max()]
        return float(session.High.max()), float(session.Low.min())

    def _latest_sweep(self):
        f = self.data["1h"]
        highs, lows = self._major_levels(f)
        prev_high, prev_low = self._session_levels(f)
        # Search a recent, bounded window; retain last sweep that closed back inside.
        start = max(1, len(f) - 36)
        events = []
        for i in range(start, len(f)):
            row = f.iloc[i]
            # A radius-2 swing is only knowable once its two right bars close.
            candidate_lows = [p for j, p in lows if j <= i-PIVOT_RADIUS and i-j <= 50]
            candidate_highs = [p for j, p in highs if j <= i-PIVOT_RADIUS and i-j <= 50]
            levels_low = candidate_lows[-3:] + ([prev_low] if prev_low is not None else [])
            levels_high = candidate_highs[-3:] + ([prev_high] if prev_high is not None else [])
            swept_low = [x for x in levels_low if row.Low < x and row.Close > x]
            swept_high = [x for x in levels_high if row.High > x and row.Close < x]
            if swept_low:
                events.append((i, "LONG", max(swept_low), "1h Sweep of Liquidity Low"))
            if swept_high:
                events.append((i, "SHORT", min(swept_high), "1h Sweep of Liquidity High"))
        return events[-1] if events else None

    def _mss_after_sweep(self):
        if not self.sweep:
            return None
        sweep_i, side, _, _ = self.sweep
        f = self.data["15m"]
        # The 1h candle's open timestamp is not when the sweep becomes known.
        sweep_time = self.data["1h"].iloc[sweep_i].Timestamp + pd.Timedelta("1h")
        start = int(f.Timestamp.searchsorted(sweep_time, side="left"))
        if start >= len(f) - 1:
            return None
        atr = self._atr(f)
        highs, lows = self._pivots(f)
        for i in range(start, len(f)):
            row = f.iloc[i]
            prior_highs = [p for j, p in highs if j <= i-PIVOT_RADIUS and j >= max(0, start-64)]
            prior_lows = [p for j, p in lows if j <= i-PIVOT_RADIUS and j >= max(0, start-64)]
            body = abs(float(row.Close - row.Open))
            threshold = float(atr.iloc[i]) * 0.8 if pd.notna(atr.iloc[i]) else 0
            if side == "LONG" and prior_highs and row.Close > max(prior_highs) and row.Close > row.Open and body >= threshold:
                return {"index": i, "level": max(prior_highs), "time": row.Timestamp}
            if side == "SHORT" and prior_lows and row.Close < min(prior_lows) and row.Close < row.Open and body >= threshold:
                return {"index": i, "level": min(prior_lows), "time": row.Timestamp}
        return None

    def _fvg(self, frame, side, start=0):
        f = frame
        for i in range(len(f)-1, max(1, start+1), -1):
            if side == "LONG" and f.Low.iloc[i] > f.High.iloc[i-2]:
                low, high = float(f.High.iloc[i-2]), float(f.Low.iloc[i])
            elif side == "SHORT" and f.High.iloc[i] < f.Low.iloc[i-2]:
                low, high = float(f.High.iloc[i]), float(f.Low.iloc[i-2])
            else:
                continue
            later = f.iloc[i+1:]
            mitigated = (later.Low <= high).any() if side == "LONG" else (later.High >= low).any()
            if not mitigated:
                return (i, low, high)
        return None

    def _ob(self, frame, side, end=None, start=0):
        stop = min(len(frame), end if end is not None else len(frame))
        for i in range(stop-2, max(start, 0)-1, -1):
            row = frame.iloc[i]
            if side == "LONG" and row.Close < row.Open:
                return (i, float(row.Low), float(row.High))
            if side == "SHORT" and row.Close > row.Open:
                return (i, float(row.Low), float(row.High))
        return None

    def _five_min_trigger(self, kind, side, zone=None, since=0):
        f = self.data["5m"]
        row = f.iloc[-1]
        prev = f.iloc[-2]
        if kind == "fvg":
            zone = self._fvg(f.iloc[:-1].reset_index(drop=True), side, since)
            if zone:
                _, low, high = zone
                touched = row.Low <= high and row.High >= low
                rejected = row.Close > row.Open if side == "LONG" else row.Close < row.Open
                if touched and rejected and ((side == "LONG" and row.Close >= low) or (side == "SHORT" and row.Close <= high)):
                    return float(row.Close), low, high, "5m FVG Mitigation"
        if kind in ("ob", "breaker") and zone:
            _, low, high = zone
            touched = row.Low <= high and row.High >= low
            rejected = row.Close > row.Open if side == "LONG" else row.Close < row.Open
            if touched and rejected:
                return float(row.Close), low, high, "5m Breaker Retest" if kind == "breaker" else "5m Unmitigated Order Block Retest"
        if kind == "rejection":
            if side == "LONG" and row.Low < prev.Low and row.Close > prev.Close and row.Close > row.Open:
                return float(row.Close), float(row.Low), float(row.High), "5m Rejection Confirmed"
            if side == "SHORT" and row.High > prev.High and row.Close < prev.Close and row.Close < row.Open:
                return float(row.Close), float(row.Low), float(row.High), "5m Rejection Confirmed"
        if kind == "ote" and zone:
            _, low, high = zone
            if row.Low <= high and row.High >= low and ((side == "LONG" and row.Close > row.Open) or (side == "SHORT" and row.Close < row.Open)):
                return float(row.Close), float(row.Low), float(row.High), "5m OTE Rejection"
        return None

    def _divergence(self, frame, side):
        f = frame
        rsi = f["RSI_14"] if "RSI_14" in f else self._rsi(f.Close)
        highs, lows = self._pivots(f, radius=2)
        points = lows if side == "LONG" else highs
        if len(points) < 2:
            return False
        (i1, _), (i2, _) = points[-2:]
        if side == "LONG":
            return f.Low.iloc[i2] < f.Low.iloc[i1] and rsi.iloc[i2] > rsi.iloc[i1]
        return f.High.iloc[i2] > f.High.iloc[i1] and rsi.iloc[i2] < rsi.iloc[i1]

    @staticmethod
    def _rsi(close, period=14):
        delta = close.diff()
        gain, loss = delta.clip(lower=0), -delta.clip(upper=0)
        avg_gain = gain.ewm(alpha=1/period, adjust=False, min_periods=period).mean()
        avg_loss = loss.ewm(alpha=1/period, adjust=False, min_periods=period).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        return (100 - 100/(1+rs)).where(avg_loss.ne(0), 100)

    def _one_hour_zone(self, side):
        f = self.data["1h"]
        ob = self._ob(f, side)
        fvg = self._fvg(f, side)
        px = float(f.Close.iloc[-1])
        for zone in (ob, fvg):
            if zone and zone[1] <= px <= zone[2]:
                return zone
        return ob or fvg

    def _level_flip(self, side):
        f = self.data["1h"]
        highs, lows = self._major_levels(f)
        row = f.iloc[-1]
        for idx, level in reversed(highs if side == "LONG" else lows):
            if len(f)-idx > 12:
                break
            prior = f.iloc[idx-1].Close if idx else level
            if side == "LONG" and prior <= level and row.Close > level and row.Low <= level:
                return level
            if side == "SHORT" and prior >= level and row.Close < level and row.High >= level:
                return level
        return None

    def _ote_zone(self, side):
        f = self.data["1h"].tail(48).reset_index(drop=True)
        highs, lows = self._pivots(f)
        if side == "LONG":
            for low_i, low_price in reversed([(i, p) for i, p in lows if i < len(f)-3]):
                later_highs = [(i, p) for i, p in highs if i > low_i]
                if later_highs:
                    high_i, high_price = later_highs[-1]
                    prior_range_high = f.High.iloc[max(0, low_i-20):low_i].max()
                    if high_price > low_price and high_price > prior_range_high:
                        return (None, high_price - .786*(high_price-low_price),
                                high_price - .618*(high_price-low_price))
        else:
            for high_i, high_price in reversed([(i, p) for i, p in highs if i < len(f)-3]):
                later_lows = [(i, p) for i, p in lows if i > high_i]
                if later_lows:
                    low_price = later_lows[-1][1]
                    prior_range_low = f.Low.iloc[max(0, high_i-20):high_i].min()
                    if high_price > low_price and low_price < prior_range_low:
                        return (None, low_price + .618*(high_price-low_price),
                                low_price + .786*(high_price-low_price))
        return None

    def _recent_mss(self, side):
        """Find fresh displacement MSS for POIs that are independent of sweeps."""
        f = self.data["15m"]
        atr = self._atr(f)
        highs, lows = self._pivots(f)
        floor = max(0, len(f)-32)
        for i in range(len(f)-1, floor, -1):
            row = f.iloc[i]
            body = abs(float(row.Close-row.Open))
            threshold = float(atr.iloc[i])*.8 if pd.notna(atr.iloc[i]) else 0
            prior_highs = [p for j, p in highs if floor <= j <= i-PIVOT_RADIUS]
            prior_lows = [p for j, p in lows if floor <= j <= i-PIVOT_RADIUS]
            if side == "LONG" and prior_highs and row.Close > max(prior_highs) and row.Close > row.Open and body >= threshold:
                return {"index": i, "level": max(prior_highs), "time": row.Timestamp}
            if side == "SHORT" and prior_lows and row.Close < min(prior_lows) and row.Close < row.Open and body >= threshold:
                return {"index": i, "level": min(prior_lows), "time": row.Timestamp}
        return None

    def _risk_target(self, side, entry, invalidation):
        buffer = self.spread_buffer
        sl = invalidation - buffer if side == "LONG" else invalidation + buffer
        risk = entry - sl if side == "LONG" else sl - entry
        if not np.isfinite(risk) or risk <= 0:
            return None
        f = self.data["1h"]
        highs, lows = self._major_levels(f, 80)
        pools = [p for _, p in (highs if side == "LONG" else lows)]
        valid = [p for p in pools if (p >= entry + RR_FLOOR*risk if side == "LONG" else p <= entry - RR_FLOOR*risk)]
        tp = min(valid) if side == "LONG" and valid else max(valid) if side == "SHORT" and valid else entry + RR_FLOOR*risk if side == "LONG" else entry - RR_FLOOR*risk
        rr = (tp-entry)/risk if side == "LONG" else (entry-tp)/risk
        return float(sl), float(tp), float(rr)

    def _emit(self, strategy, side, trigger, confluences, invalidation=None):
        if not trigger or side != self.bias:
            return None
        entry, zone_low, zone_high, trigger_note = trigger
        if invalidation is None:
            invalidation = zone_low if side == "LONG" else zone_high
        # Include recent execution swing when it provides the more conservative invalidation.
        f5 = self.data["5m"].tail(12)
        invalidation = min(float(invalidation), float(f5.Low.min())) if side == "LONG" else max(float(invalidation), float(f5.High.max()))
        levels = self._risk_target(side, entry, invalidation)
        if not levels:
            return None
        sl, tp, rr = levels
        notes = [f"4h {self.bias.title()} Trend", *confluences, trigger_note]
        return {"symbol": self.symbol, "strategy": strategy, "action": side,
                "entry": float(entry), "sl": sl, "tp": tp, "rr": float(rr),
                "confluences": notes,
                "timestamp": pd.Timestamp(self.data['5m'].iloc[-1].Timestamp).tz_convert('UTC').isoformat()}

    def _scan_sweep_fvg(self, side):
        if not self.sweep or self.sweep[1] != side or not self.mss:
            return None
        t = self._five_min_trigger("fvg", side)
        return self._emit("Liquidity Sweep + MSS + FVG", side, t,
                          [self.sweep[3], "15m Displacement MSS Confirmed"])

    def _scan_breaker(self, side):
        if not self.sweep or self.sweep[1] != side or not self.mss:
            return None
        f = self.data["15m"]
        ob = self._ob(f, side, end=self.mss["index"])
        trigger = self._five_min_trigger("breaker", side, ob)
        return self._emit("Liquidity Grab + Breaker Block", side, trigger,
                          [self.sweep[3], "15m Order Block Broken into Breaker", "15m MSS Confirmed"])

    def _scan_sr_ob(self, side):
        level = self._level_flip(side)
        if level is None or not (self.mss or self._recent_mss(side)):
            return None
        ob = self._ob(self.data["5m"], side)
        trigger = self._five_min_trigger("ob", side, ob)
        return self._emit("S/R Flip + Order Block", side, trigger,
                          [f"1h S/R Flip at {level:.8g}", "15m Structural Confirmation"])

    def _scan_ote(self, side):
        zone = self._ote_zone(side)
        if zone is None or not (self.mss or self._recent_mss(side)):
            return None
        trigger = self._five_min_trigger("ote", side, zone)
        return self._emit("Fibonacci / PD Array Confluence", side, trigger,
                          ["1h Dealing Range Expansion", "15m OTE 61.8%-78.6% Retracement", "15m MSS Confirmed"])

    def _scan_divergence(self, side):
        zone = self._one_hour_zone(side)
        if not zone or not (self.mss or self._recent_mss(side)):
            return None
        if not (self._divergence(self.data["15m"], side) or self._divergence(self.data["5m"], side)):
            return None
        trigger = self._five_min_trigger("rejection", side)
        return self._emit("RSI Divergence + Supply/Demand", side, trigger,
                          ["1h Supply/Demand Reaction", "15m/5m Wilder RSI Divergence", "15m Structural Confirmation"])

    def _scan_silver_bullet(self, side):
        row = self.data["5m"].iloc[-1]
        local = row.Timestamp.tz_convert(ZoneInfo("America/New_York"))
        if (local.hour, local.minute) < (10, 0) or (local.hour, local.minute) >= (11, 0):
            return None
        if not (self.mss or self._recent_mss(side)):
            return None
        trigger = self._five_min_trigger("fvg", side)
        return self._emit("ICT Silver Bullet", side, trigger,
                          ["New York Silver Bullet 10:00-11:00", "15m MSS Confirmed", "Internal Liquidity Draw"])

    def scan_all_setups(self) -> list[dict]:
        """Return only setups with 4h bias and complete 1h/15m/5m confluence."""
        if self.bias not in ("LONG", "SHORT"):
            return []
        side = self.bias
        scanners = (self._scan_sweep_fvg, self._scan_breaker, self._scan_sr_ob,
                    self._scan_ote, self._scan_divergence, self._scan_silver_bullet)
        results = []
        for scanner in scanners:
            try:
                candidate = scanner(side)
                if candidate is not None:
                    results.append(candidate)
            except (IndexError, KeyError, ValueError, TypeError, ZeroDivisionError):
                # Malformed or insufficient local structure cannot authorize a trade.
                continue
        return results

