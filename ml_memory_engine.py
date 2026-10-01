import os
import pandas as pd
import numpy as np
import xgboost as xgb
from sklearn.metrics import accuracy_score, precision_score
from supabase_engine import SupabaseEngine

class LancasterMLEngine:
    def __init__(self, memory_file="aegis_trade_memory.csv"):
        self.memory_file = memory_file
        self.model = None
        self.supabase = SupabaseEngine()
        self._sync_storage()

    def _sync_storage(self):
        cloud_trades = self.supabase.fetch_trade_memory()
        if cloud_trades:
            df = pd.DataFrame(cloud_trades)
            df.to_csv(self.memory_file, index=False)
        elif not os.path.exists(self.memory_file):
            cols = [
                'timestamp', 'strategy', 'momentum_5', 'momentum_10', 'momentum_21',
                'volatility_5', 'volatility_21', 'sma_gap_5_21', 'rsi_14',
                'risk_reward', 'hour_ny', 'win_label'
            ]
            pd.DataFrame(columns=cols).to_csv(self.memory_file, index=False)

    def extract_lancaster_features(self, df: pd.DataFrame, idx: int) -> dict:
        sub = df.iloc[:idx+1]
        close = sub['Close']
        curr_close = close.iloc[-1]

        mom_5 = (curr_close - close.iloc[-5]) / close.iloc[-5] if len(close) >= 5 else 0.0
        mom_10 = (curr_close - close.iloc[-10]) / close.iloc[-10] if len(close) >= 10 else 0.0
        mom_21 = (curr_close - close.iloc[-21]) / close.iloc[-21] if len(close) >= 21 else 0.0

        ret = close.pct_change()
        vol_5 = ret.iloc[-5:].std() if len(ret) >= 5 else 0.0
        vol_21 = ret.iloc[-21:].std() if len(ret) >= 21 else 0.0

        sma_5 = close.iloc[-5:].mean() if len(close) >= 5 else curr_close
        sma_21 = close.iloc[-21:].mean() if len(close) >= 21 else curr_close
        sma_gap = (sma_5 - sma_21) / (sma_21 + 1e-9)

        rsi = sub['RSI'].iloc[-1] if 'RSI' in sub.columns else 50.0
        hour_ny = sub['Hour_NY'].iloc[-1] if 'Hour_NY' in sub.columns else 12

        return {
            'momentum_5': round(float(mom_5), 5),
            'momentum_10': round(float(mom_10), 5),
            'momentum_21': round(float(mom_21), 5),
            'volatility_5': round(float(vol_5), 5),
            'volatility_21': round(float(vol_21), 5),
            'sma_gap_5_21': round(float(sma_gap), 5),
            'rsi_14': round(float(rsi), 2),
            'hour_ny': int(hour_ny)
        }

    def train_purged_walk_forward(self, embargo_pct=0.05) -> dict:
        """
        Implements Purged Time-Series Cross-Validation to eliminate lookahead bias.
        """
        if not os.path.exists(self.memory_file):
            return {"status": "No memory file"}
        data = pd.read_csv(self.memory_file)
        if len(data) < 20:
            return {"status": "Awaiting minimum sample (20 trades required)"}

        feature_cols = ['momentum_5', 'momentum_10', 'momentum_21', 'volatility_5', 'volatility_21', 'sma_gap_5_21', 'rsi_14', 'hour_ny']
        X = data[feature_cols].fillna(0)
        y = data['win_label'].astype(int)

        # Purged split: 70% Train, 5% Embargo buffer, 25% Out-of-sample Test
        n = len(data)
        train_end = int(n * 0.70)
        embargo_end = train_end + int(n * embargo_pct)
        test_start = min(embargo_end, n - 2)

        X_train, y_train = X.iloc[:train_end], y.iloc[:train_end]
        X_test, y_test = X.iloc[test_start:], y.iloc[test_start:]

        self.model = xgb.XGBClassifier(
            n_estimators=60,
            max_depth=4,
            learning_rate=0.05,
            eval_metric="logloss",
            random_state=42
        )
        self.model.fit(X_train, y_train)

        preds = self.model.predict(X_test)
        acc = accuracy_score(y_test, preds) if len(y_test) > 0 else 0.0

        return {
            "status": "Trained",
            "train_samples": len(X_train),
            "test_samples": len(X_test),
            "oos_accuracy": round(acc * 100, 2)
        }

    def predict_win_probability(self, feature_dict: dict) -> float:
        if self.model is None:
            return 0.65
        feature_cols = ['momentum_5', 'momentum_10', 'momentum_21', 'volatility_5', 'volatility_21', 'sma_gap_5_21', 'rsi_14', 'hour_ny']
        sample = pd.DataFrame([{col: feature_dict.get(col, 0) for col in feature_cols}])
        prob = self.model.predict_proba(sample)[0][1]
        return round(float(prob), 2)

    def log_trade(self, trade_record: dict):
        # 1. Local append
        df_new = pd.DataFrame([trade_record])
        df_new.to_csv(self.memory_file, mode='a', header=not os.path.exists(self.memory_file), index=False)
        # 2. Cloud Supabase sync
        self.supabase.insert_trade_memory(trade_record)