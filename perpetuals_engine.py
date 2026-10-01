import ccxt
import pandas as pd
import yfinance as yf

class PerpetualsEngine:
    def __init__(self):
        self.binance = ccxt.binanceusdm({'enableRateLimit': True})
        self.mexc = ccxt.mexc({
            'enableRateLimit': True,
            'options': {'defaultType': 'swap'}
        })

    def fetch_futures_data(self, exchange: str, symbol: str, timeframe: str = '15m', limit: int = 100) -> pd.DataFrame:
        exchange_clean = exchange.lower()
        
        # 1. AUTOMATIC COMMODITY ROUTE FOR GOLD (XAU)
        if "XAU" in symbol.upper() or exchange_clean == "oanda":
            print(f"📡 COMMODITY FEED | Fetching XAU/USD ({timeframe})...")
            try:
                yf_interval = timeframe
                if timeframe == '1h': yf_interval = '60m'
                elif timeframe == '4h': yf_interval = '1h'
                elif timeframe == '1d': yf_interval = '1d'

                period = "5d" if timeframe in ['5m', '15m'] else ("1mo" if timeframe in ['1h', '4h'] else "1y")

                ticker = yf.Ticker("GC=F")
                df = ticker.history(period=period, interval=yf_interval)
                if df.empty:
                    return pd.DataFrame()

                df = df.reset_index()
                time_col = 'Datetime' if 'Datetime' in df.columns else 'Date'
                df.rename(columns={
                    time_col: 'Timestamp',
                    'Open': 'Open',
                    'High': 'High',
                    'Low': 'Low',
                    'Close': 'Close',
                    'Volume': 'Volume'
                }, inplace=True)
                df['Timestamp'] = pd.to_datetime(df['Timestamp']).dt.tz_localize(None)
                return df[['Timestamp', 'Open', 'High', 'Low', 'Close', 'Volume']].tail(limit).reset_index(drop=True)
            except Exception as e:
                print(f"❌ Error fetching XAU data: {e}")
                return pd.DataFrame()

        # 2. CRYPTO PERPETUALS ROUTE (BINANCE / MEXC)
        client = self.binance if exchange_clean == 'binance' else self.mexc
        target_symbol = symbol if ":" in symbol else f"{symbol.upper()}:USDT"
        
        print(f"📡 {exchange.upper()} | Fetching {target_symbol} Perpetuals ({timeframe})...")
        try:
            ohlcv = client.fetch_ohlcv(target_symbol, timeframe=timeframe, limit=limit)
            df = pd.DataFrame(ohlcv, columns=['Timestamp', 'Open', 'High', 'Low', 'Close', 'Volume'])
            df['Timestamp'] = pd.to_datetime(df['Timestamp'], unit='ms')
            return df
        except Exception as e:
            print(f"❌ Error connecting to {exchange.upper()}: {e}")
            return pd.DataFrame()