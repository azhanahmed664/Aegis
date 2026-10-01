import json
import time
from openai import OpenAI
from data_engine import UniversalDataEngine
from risk_engine import QuantitativeRiskEngine

class AladdinAgent:
    def __init__(self, model_name: str = "qwen2.5-coder:1.5b"):
        self.model_name = model_name
        self.client = OpenAI(
            base_url="http://localhost:11434/v1",
            api_key="ollama"
        )
        self.data_engine = UniversalDataEngine()
        self.risk_engine = QuantitativeRiskEngine()

    def generate_risk_report(self, symbol: str, asset_type: str = "crypto", lookback_days: int = 365) -> str:
        print(f"\n==========================================")
        print(f"📊 Running Aladdin Risk Pipeline for {symbol.upper()}")
        print(f"==========================================")

        # 1. Fetch Data (0 Tokens)
        df = self.data_engine.fetch_data(symbol, asset_type=asset_type, lookback_days=lookback_days)

        # 2. Compute Risk Metrics (0 Tokens)
        raw_metrics = self.risk_engine.calculate_metrics(df)

        # Sanitize numpy floats to native Python floats for clean serialization
        clean_metrics = {k: float(v) if hasattr(v, 'item') else v for k, v in raw_metrics.items()}
        payload_str = json.dumps(clean_metrics, indent=2)

        print(f"✅ Quant Metrics Computed:\n{payload_str}\n")
        print("🧠 Passing payload to local Qwen model for synthesis...")

        # 3. Compact Institutional System Prompt
        system_prompt = (
            "You are the senior risk officer of an institutional multi-asset risk management engine (Aladdin). "
            "Analyze the pre-computed quant risk payload for the given asset. "
            "Deliver an executive briefing in under 120 words structured into: "
            "1. Risk Profile (VaR & Volatility interpretation) "
            "2. Stress Vulnerability (Drawdown context) "
            "3. Actionable Positioning / Hedging Directive. "
            "Do not output conversational greetings or filler text."
        )

        user_prompt = f"Asset: {symbol.upper()} ({asset_type.upper()})\nQuantitative Metrics:\n{payload_str}"

        # 4. Streamlined LLM Call
        start_time = time.time()
        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.2,
            max_tokens=250
        )
        elapsed = round(time.time() - start_time, 2)

        print(f"⚡ Synthesis completed in {elapsed}s.\n")
        return response.choices[0].message.content

if __name__ == "__main__":
    agent = AladdinAgent()

    # Test 1: Crypto (BTC/USDT)
    btc_report = agent.generate_risk_report("BTC/USDT", asset_type="crypto", lookback_days=365)
    print("----- BTC RISK REPORT -----")
    print(btc_report)
    print("---------------------------\n")

    # Test 2: Commodity (Gold Futures)
    gold_report = agent.generate_risk_report("GC=F", asset_type="commodity", lookback_days=365)
    print("----- GOLD RISK REPORT -----")
    print(gold_report)
    print("---------------------------")