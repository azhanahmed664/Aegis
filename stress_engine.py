import numpy as np

class CrossMarginStressTester:
    def __init__(self, initial_capital=10000.0, target_risk_pct=0.005, win_rate=0.45, risk_reward=2.0, flash_crash_prob=0.01):
        self.initial_capital = initial_capital
        self.target_risk_pct = target_risk_pct  # Intended 0.5% stop-loss risk
        self.win_rate = win_rate
        self.risk_reward = risk_reward
        
        # Cross Margin Danger: Probability of a wick jumping the stop-loss 
        # and drawing from the shared wallet balance due to max leverage.
        self.flash_crash_prob = flash_crash_prob 
        
    def run_simulation(self, num_simulations=10000, trades_per_sim=500):
        print(f"🎲 Running {num_simulations:,} Cross Margin paths for {trades_per_sim} trades...")
        print(f"⚠️ Warning: Modeling Max Leverage Stop-Loss Slippage (Probability: {self.flash_crash_prob*100}%)")
        
        # 1. Base trade outcomes
        random_outcomes = np.random.rand(num_simulations, trades_per_sim)
        wins = random_outcomes <= self.win_rate
        
        # 2. Flash Crash / Slippage Events
        crash_events = np.random.rand(num_simulations, trades_per_sim) <= self.flash_crash_prob
        
        # Randomize slippage severity (draining between 2% and 100% of the shared cross wallet)
        slippage_severity = np.random.uniform(0.02, 1.0, size=(num_simulations, trades_per_sim))
        
        # 3. Build Multipliers
        win_multiplier = 1 + (self.target_risk_pct * self.risk_reward)
        normal_loss_multiplier = 1 - self.target_risk_pct
        
        # Apply severe slippage if a loss coincides with a flash crash
        multipliers = np.where(wins, win_multiplier, normal_loss_multiplier)
        multipliers = np.where(~wins & crash_events, 1 - slippage_severity, multipliers)
        
        # 4. Calculate Equity
        equity_paths = self.initial_capital * np.cumprod(multipliers, axis=1)
        equity_paths = np.maximum(equity_paths, 0) # Cap floor at $0 (Total Liquidation)
        
        terminal_equities = equity_paths[:, -1]
        
        # 5. Drawdowns
        running_max = np.maximum.accumulate(equity_paths, axis=1)
        running_max = np.where(running_max == 0, 1, running_max) 
        drawdowns = (equity_paths - running_max) / running_max
        max_drawdowns = np.min(drawdowns, axis=1)
        
        print("\n📊 Cross Margin Stress Test Results:")
        print(f"Average Terminal Equity: ${np.mean(terminal_equities):,.2f}")
        print(f"Median Terminal Equity: ${np.median(terminal_equities):,.2f}")
        print(f"Worst Case (99th Percentile Drawdown): {np.percentile(max_drawdowns, 1) * 100:.2f}%")
        print(f"Probability of Severe Ruin (>50% Loss): {np.mean(max_drawdowns <= -0.50) * 100:.2f}%")
        print(f"Total Account Liquidations (0 balance): {np.mean(terminal_equities == 0) * 100:.2f}%\n")

if __name__ == "__main__":
    # Simulate a strategy with 0.5% wallet risk target, 45% win rate, 1% chance of severe slippage
    tester = CrossMarginStressTester(initial_capital=10000, target_risk_pct=0.005, win_rate=0.45, risk_reward=2.0, flash_crash_prob=0.01)
    tester.run_simulation()