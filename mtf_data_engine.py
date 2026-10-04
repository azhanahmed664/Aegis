"""UTC closed-candle MTF data. Timestamp denotes candle OPEN time.
For causal backtests, join HTF data on Timestamp + its timeframe duration.
Gold uses GC=F, a futures proxy; 4h bins are anchored at UTC midnight.
"""
from concurrent.futures import ThreadPoolExecutor
from numbers import Integral
from threading import Lock
import time
import ccxt
import numpy as np
import pandas as pd
import yfinance as yf

TIMEFRAMES = ('4h', '1h', '15m', '5m')
COLUMNS = ['Timestamp', 'Open', 'High', 'Low', 'Close', 'Volume']
WARMUP = 250
_CLIENT = None
_CRYPTO_LOCK = Lock()
_GOLD_LOCK = Lock()

class MTFDataError(RuntimeError):
    """A complete, valid MTF block could not be obtained."""

def _retry(operation):
    for attempt in range(3):
        try:
            return operation()
        except (ccxt.NetworkError, ccxt.RateLimitExceeded,
                TimeoutError, ConnectionError) as exc:
            if attempt == 2:
                raise MTFDataError('Data request failed after three attempts') from exc
            time.sleep(2 ** (attempt + 1))

def _clean(frame, timeframe, cutoff):
    if frame.empty:
        raise MTFDataError(f'No candles for {timeframe}')
    frame = frame.loc[:, COLUMNS].copy()
    frame['Timestamp'] = pd.to_datetime(frame['Timestamp'], utc=True)
    for column in COLUMNS[1:]:
        frame[column] = pd.to_numeric(frame[column], errors='raise')
    frame = frame.sort_values('Timestamp').drop_duplicates('Timestamp', keep='last')
    if frame.isna().any().any() or not np.isfinite(
            frame[COLUMNS[1:]].to_numpy(dtype=float)).all():
        raise MTFDataError('Missing or non-finite OHLCV values')
    invalid = (
        (frame['Low'] > frame[['Open', 'Close']].min(axis=1))
        | (frame['High'] < frame[['Open', 'Close']].max(axis=1))
        | (frame['Low'] > frame['High']) | (frame['Volume'] < 0)
        | (frame[['Open', 'High', 'Low', 'Close']] <= 0).any(axis=1)
    )
    if invalid.any():
        raise MTFDataError('Invalid OHLCV candle geometry')
    return frame.loc[frame['Timestamp'] + pd.Timedelta(timeframe) <= cutoff
                     ].reset_index(drop=True)

def _indicators(frame):
    frame = frame.copy()
    close = frame['Close']
    for span in (50, 200):
        frame[f'EMA_{span}'] = close.ewm(
            span=span, adjust=False, min_periods=span).mean()
    delta = close.diff()
    gains = delta.clip(lower=0).to_numpy(dtype=float)
    losses = (-delta.clip(upper=0)).to_numpy(dtype=float)
    rsi = np.full(len(frame), np.nan)
    if len(frame) > 14:
        gain, loss = gains[1:15].mean(), losses[1:15].mean()
        for i in range(14, len(frame)):
            if i > 14:
                gain = (gain * 13 + gains[i]) / 14
                loss = (loss * 13 + losses[i]) / 14
            rsi[i] = (50.0 if gain == loss == 0 else 100.0 if loss == 0
                      else 100.0 - 100.0 / (1.0 + gain / loss))
    frame['RSI_14'] = rsi
    return frame

def _gold_history(interval, period, cutoff):
    def download():
        raw = yf.Ticker('GC=F').history(
            interval=interval, period=period, auto_adjust=False,
            actions=False, timeout=20, raise_errors=True)
        if raw.empty or not isinstance(raw.index, pd.DatetimeIndex):
            raise MTFDataError(f'No Gold data for {interval}')
        if raw.index.tz is None:
            raise MTFDataError('Gold timestamps must be timezone-aware')
        raw = raw.loc[:, COLUMNS[1:]].copy()
        raw.insert(0, 'Timestamp', raw.index.tz_convert('UTC'))
        return _clean(raw.reset_index(drop=True), interval, cutoff)
    return _retry(download)

def _gold_block(cutoff):
    with _GOLD_LOCK, ThreadPoolExecutor(max_workers=3) as pool:
        jobs = {tf: pool.submit(_gold_history, tf, period, cutoff)
                for tf, period in [('1h', '1y'), ('15m', '60d'), ('5m', '60d')]}
        block = {tf: job.result() for tf, job in jobs.items()}
    hourly = block['1h'].set_index('Timestamp')
    groups = hourly.resample('4h', origin='epoch', closed='left', label='left')
    bars = groups.agg({'Open': 'first', 'High': 'max', 'Low': 'min',
                       'Close': 'last', 'Volume': 'sum'})
    aligned = pd.Series(hourly.index == hourly.index.floor('1h'),
                        index=hourly.index).resample('4h', origin='epoch').min().fillna(False)
    bars = bars.loc[(groups['Close'].count() == 4) & aligned]
    block['4h'] = _clean(bars.reset_index(), '4h', cutoff)
    return block

def _crypto_block(symbol, count, cutoff):
    global _CLIENT
    # A shared client preserves rate limiting across watchlist/thread calls.
    with _CRYPTO_LOCK:
        if _CLIENT is None:
            _CLIENT = ccxt.binanceusdm({'enableRateLimit': True, 'timeout': 20000})
        _retry(_CLIENT.load_markets)
        if ':' not in symbol:
            symbol = f"{symbol}:{symbol.split('/')[-1]}"
        market = _CLIENT.market(symbol)
        if not (market.get('swap') and market.get('linear')
                and market.get('active', True)):
            raise MTFDataError(f'Not an active linear perpetual: {symbol}')
        block = {}
        for tf in TIMEFRAMES:
            duration = int(pd.Timedelta(tf).total_seconds() * 1000)
            end = int(cutoff.timestamp() * 1000)
            since = (end // duration - count - 2) * duration
            rows = []
            while since < end:
                size = min(1000, (end - since) // duration + 1)
                page = _retry(lambda: _CLIENT.fetch_ohlcv(
                    symbol, timeframe=tf, since=since, limit=size))
                if not page:
                    break
                rows.extend(page)
                next_since = int(page[-1][0]) + duration
                if next_since <= since:
                    raise MTFDataError('Exchange pagination did not advance')
                since = next_since
            frame = pd.DataFrame(rows, columns=COLUMNS)
            frame['Timestamp'] = pd.to_datetime(frame['Timestamp'], unit='ms', utc=True)
            block[tf] = _clean(frame, tf, cutoff)
        return block

def fetch_mtf_data(symbol: str, limit: int = 150) -> dict[str, pd.DataFrame]:
    """Return exactly limit closed bars for 4h, 1h, 15m, 5m plus indicators.
    One UTC observation cutoff is captured before requests. Indicators are
    computed with 250 extra bars before trimming. Session gaps are preserved.
    Insufficient history or provider failures raise MTFDataError, never a
    partial block. Large Gold limits are constrained by Yahoo retention.
    UTC normalization does not make different asset calendars identical.
    """
    if isinstance(limit, bool) or not isinstance(limit, Integral) or limit < 1:
        raise ValueError('limit must be a positive integer')
    if not isinstance(symbol, str) or not symbol.strip():
        raise ValueError('symbol must be a nonempty string')
    symbol = symbol.strip().upper()
    if symbol != 'XAU/USD' and '/' not in symbol:
        raise ValueError('Use XAU/USD or a crypto pair such as BTC/USDT:USDT')
    cutoff = pd.Timestamp.now(tz='UTC')
    try:
        block = (_gold_block(cutoff) if symbol == 'XAU/USD'
                 else _crypto_block(symbol, int(limit) + WARMUP, cutoff))
        result = {}
        for tf in TIMEFRAMES:
            frame = block[tf]
            if len(frame) < limit + WARMUP:
                raise MTFDataError(f'{symbol} {tf}: need {limit + WARMUP} '
                                   f'closed bars, received {len(frame)}')
            frame = frame.tail(limit + WARMUP).reset_index(drop=True)
            seed = frame.iloc[:-limit].loc[:, COLUMNS].copy()
            frame = _indicators(frame)
            frame = frame.tail(limit).reset_index(drop=True)
            frame.attrs.update(symbol=symbol, timeframe=tf,
                               as_of_utc=cutoff.isoformat(), timestamp_semantics='open',
                               indicator_seed=_serialize_seed(seed))
            result[tf] = frame
        return result
    except MTFDataError:
        raise
    except Exception as exc:
        raise MTFDataError(f'Failed to fetch complete MTF data for {symbol}: {exc}') from exc


def _serialize_seed(frame):
    """Store the indicator warm-up bars in DataFrame attrs for rolling refreshes."""
    seed = frame.loc[:, COLUMNS].copy()
    seed['Timestamp'] = pd.to_datetime(seed['Timestamp'], utc=True).map(
        lambda value: value.isoformat())
    return seed.to_dict(orient='records')


def _recent_gold(timeframe, cutoff, hours):
    """Fetch a bounded recent Gold window (Yahoo has no candle-count option)."""
    start = cutoff - pd.Timedelta(hours=hours)

    def download():
        raw = yf.Ticker('GC=F').history(
            interval=timeframe, start=start.to_pydatetime(),
            end=cutoff.to_pydatetime(), auto_adjust=False,
            actions=False, timeout=20, raise_errors=True)
        # Yahoo returns an empty frame while the futures market is closed.
        # Treat that as "no new candles" so a weekend refresh can retain the
        # last complete cached session instead of turning into a data error.
        if raw.empty:
            return pd.DataFrame(columns=COLUMNS)
        if not isinstance(raw.index, pd.DatetimeIndex):
            raise MTFDataError(f'No recent Gold data for {timeframe}')
        if raw.index.tz is None:
            raise MTFDataError('Gold timestamps must be timezone-aware')
        raw = raw.loc[:, COLUMNS[1:]].copy()
        raw.insert(0, 'Timestamp', raw.index.tz_convert('UTC'))
        return _clean(raw.reset_index(drop=True), timeframe, cutoff)

    return _retry(download)


def _recent_gold_block(cutoff):
    # A short hourly window supplies enough constituent bars for two complete
    # UTC-anchored 4h candles; finer intervals need only their latest bars.
    with _GOLD_LOCK, ThreadPoolExecutor(max_workers=3) as pool:
        jobs = {
            '1h': pool.submit(_recent_gold, '1h', cutoff, 16),
            '15m': pool.submit(_recent_gold, '15m', cutoff, 2),
            '5m': pool.submit(_recent_gold, '5m', cutoff, 1),
        }
        block = {tf: job.result() for tf, job in jobs.items()}
    if block['1h'].empty:
        block['4h'] = pd.DataFrame(columns=COLUMNS)
        return block
    hourly = block['1h'].set_index('Timestamp')
    groups = hourly.resample('4h', origin='epoch', closed='left', label='left')
    bars = groups.agg({'Open': 'first', 'High': 'max', 'Low': 'min',
                       'Close': 'last', 'Volume': 'sum'})
    complete = groups['Close'].count() == 4
    complete_bars = bars.loc[complete].reset_index()
    block['4h'] = (_clean(complete_bars, '4h', cutoff) if not complete_bars.empty
                   else pd.DataFrame(columns=COLUMNS))
    return block


def _recent_crypto_block(symbol, cutoff):
    """Request only the latest two possible bars for each exchange timeframe."""
    global _CLIENT
    with _CRYPTO_LOCK:
        if _CLIENT is None:
            _CLIENT = ccxt.binanceusdm({'enableRateLimit': True, 'timeout': 20000})
        _retry(_CLIENT.load_markets)
        if ':' not in symbol:
            symbol = f"{symbol}:{symbol.split('/')[-1]}"
        market = _CLIENT.market(symbol)
        if not (market.get('swap') and market.get('linear')
                and market.get('active', True)):
            raise MTFDataError(f'Not an active linear perpetual: {symbol}')
        block = {}
        for timeframe in TIMEFRAMES:
            raw = _retry(lambda: _CLIENT.fetch_ohlcv(
                symbol, timeframe=timeframe, limit=2))
            if not raw:
                raise MTFDataError(f'No recent candles for {symbol} {timeframe}')
            frame = pd.DataFrame(raw, columns=COLUMNS)
            frame['Timestamp'] = pd.to_datetime(frame['Timestamp'], unit='ms', utc=True)
            # The common cutoff excludes the still-forming last candle.
            block[timeframe] = _clean(frame, timeframe, cutoff)
    return block


def update_mtf_data(cached_data: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Incrementally refresh an MTF block with at most two provider candles.

    Existing closed bars are retained, duplicate/unfinished bars are ignored,
    and each timeframe stays at its cached length (normally 150). Indicator
    warm-up bars travel in frame attrs so EMA/RSI values remain stable when the
    visible window rolls forward.
    """
    if not isinstance(cached_data, dict) or any(tf not in cached_data for tf in TIMEFRAMES):
        raise ValueError('cached_data must contain 4h, 1h, 15m, and 5m DataFrames')
    first = cached_data['5m']
    symbol = str(first.attrs.get('symbol', '')).strip().upper()
    if not symbol:
        raise ValueError('Cached MTF frames must carry their source symbol attrs')
    if any(not isinstance(cached_data[tf], pd.DataFrame) or cached_data[tf].empty
           for tf in TIMEFRAMES):
        raise ValueError('Cached MTF frames must be nonempty DataFrames')
    cutoff = pd.Timestamp.now(tz='UTC')
    try:
        recent = (_recent_gold_block(cutoff) if symbol == 'XAU/USD'
                  else _recent_crypto_block(symbol, cutoff))
        if symbol == 'XAU/USD' and all(recent[tf].empty for tf in TIMEFRAMES):
            print('XAU/USD: Weekend/Market closed - retaining previous session cache')
            return cached_data
        limit = min(len(cached_data[tf]) for tf in TIMEFRAMES)
        if limit < 1:
            raise ValueError('Cached MTF frames have no rows')
        result = {}
        for timeframe in TIMEFRAMES:
            old = cached_data[timeframe]
            limit_for_tf = len(old)
            existing = _clean(old.loc[:, COLUMNS], timeframe, cutoff)
            latest_time = existing['Timestamp'].max()
            additions = (pd.DataFrame(columns=COLUMNS) if recent[timeframe].empty
                         else _clean(recent[timeframe], timeframe, cutoff))
            additions = additions.loc[additions['Timestamp'] > latest_time]
            combined = pd.concat([existing, additions], ignore_index=True)
            combined = combined.sort_values('Timestamp').drop_duplicates(
                'Timestamp', keep='last').reset_index(drop=True)

            seed_records = old.attrs.get('indicator_seed', [])
            seed = pd.DataFrame(seed_records, columns=COLUMNS) if seed_records else pd.DataFrame(columns=COLUMNS)
            if not seed.empty:
                seed['Timestamp'] = pd.to_datetime(seed['Timestamp'], utc=True)
            if len(combined) > limit_for_tf:
                dropped_count = len(combined) - limit_for_tf
                dropped = combined.iloc[:dropped_count].loc[:, COLUMNS]
                seed = pd.concat([seed, dropped], ignore_index=True)
                combined = combined.iloc[dropped_count:].reset_index(drop=True)
            if len(combined) < limit_for_tf:
                # Sparse provider history should not silently shrink the cache.
                missing = limit_for_tf - len(combined)
                if seed.empty or len(seed) < missing:
                    raise MTFDataError(f'{symbol} {timeframe}: insufficient rows to retain cache')
                restored = seed.tail(missing)
                seed = seed.iloc[:-missing].reset_index(drop=True)
                combined = pd.concat([restored, combined], ignore_index=True)

            seed = seed.tail(WARMUP).reset_index(drop=True)
            working = pd.concat([seed.loc[:, COLUMNS], combined], ignore_index=True)
            with_indicators = _indicators(working)
            frame = with_indicators.tail(limit_for_tf).reset_index(drop=True)
            frame.attrs.update(
                symbol=symbol, timeframe=timeframe,
                as_of_utc=cutoff.isoformat(), timestamp_semantics='open',
                indicator_seed=_serialize_seed(seed),
            )
            result[timeframe] = frame
        return result
    except MTFDataError:
        raise
    except Exception as exc:
        raise MTFDataError(f'Failed to update cached MTF data for {symbol}: {exc}') from exc

