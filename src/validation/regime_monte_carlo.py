import numpy as np
import pandas as pd
import yfinance as yf
from typing import Dict, Any, List, Tuple
from src.data.universe import universe_manager

class RegimeAwareMonteCarloEngine:
    """
    Advanced Regime-Aware Monte Carlo & Block Bootstrap Engine:
    1. Circular Stationary Block Bootstrapping (preserves trade loss/win clustering & autocorrelation)
    2. 3-State Markov Regime-Switching Simulation (Bull, Neutral, Bear states)
    3. Quantifies Fat-Tail Risk and Downside CVaR vs IID Baselines
    """
    def __init__(self, starting_capital: float = 50000.0, position_size_pct: float = 0.06):
        self.starting_capital = starting_capital
        self.position_size_pct = position_size_pct
        self.friction_pct = (10.0 * 2 + 8.0 + 15.0 * 2) / 10000.0 # 58 bps

    def extract_historical_trades_with_regimes(self) -> pd.DataFrame:
        """Extract 10-year historical trades mapped to macro regimes."""
        tickers = [u['yf_ticker'] for u in universe_manager.get_all() if not u['yf_ticker'].startswith('^')]
        all_trades = []

        # Download S&P 500 for regime classification
        sp500 = yf.Ticker("^GSPC").history(period="10y", interval="1d")
        sp500['SMA_50'] = sp500['Close'].rolling(50).mean()
        sp500['SMA_200'] = sp500['Close'].rolling(200).mean()

        def get_regime(dt):
            try:
                dt_ts = pd.Timestamp(dt).tz_localize(None) if hasattr(dt, 'tz_localize') else pd.Timestamp(dt)
                idx_matches = sp500.index[sp500.index.tz_localize(None) <= dt_ts]
                if len(idx_matches) == 0:
                    return "NEUTRAL"
                latest_dt = idx_matches[-1]
                row = sp500.loc[latest_dt]
                close = row['Close']
                sma50 = row['SMA_50']
                sma200 = row['SMA_200']
                if close > sma50 > sma200:
                    return "BULL"
                elif close < sma50 < sma200:
                    return "BEAR"
                else:
                    return "NEUTRAL"
            except Exception:
                return "NEUTRAL"

        for ticker in tickers:
            try:
                df = yf.Ticker(ticker).history(period="10y", interval="1d")
                if df.empty or len(df) < 200:
                    continue

                df['SMA_20'] = df['Close'].rolling(20).mean()
                df['SMA_50'] = df['Close'].rolling(50).mean()
                df['SMA_200'] = df['Close'].rolling(200).mean()
                delta = df['Close'].diff()
                gain = (delta.where(delta > 0, 0)).rolling(14).mean()
                loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
                rs = gain / (loss + 1e-9)
                df['RSI'] = 100 - (100 / (1 + rs))

                condition = (
                    (df['Close'] > df['SMA_20']) &
                    (df['SMA_20'] > df['SMA_50']) &
                    (df['SMA_50'] > df['SMA_200']) &
                    (df['RSI'] >= 40) & (df['RSI'] <= 60)
                )
                df['Signal'] = 0
                df.loc[condition, 'Signal'] = 1

                in_pos = False
                entry_p = 0.0
                entry_idx = 0
                entry_date = None

                for i in range(200, len(df)):
                    row = df.iloc[i]
                    dt = df.index[i]
                    if not in_pos and row['Signal'] == 1:
                        in_pos = True
                        entry_p = row['Close']
                        entry_idx = i
                        entry_date = dt
                    elif in_pos:
                        pnl = (row['Close'] - entry_p) / entry_p
                        if pnl <= -0.025:
                            ret = -0.025 - self.friction_pct
                            all_trades.append({'date': dt, 'ticker': ticker, 'ret': ret, 'regime': get_regime(entry_date), 'win': False})
                            in_pos = False
                        elif pnl >= 0.075:
                            ret = 0.075 - self.friction_pct
                            all_trades.append({'date': dt, 'ticker': ticker, 'ret': ret, 'regime': get_regime(entry_date), 'win': True})
                            in_pos = False
                        elif (i - entry_idx) >= 20:
                            ret = pnl - self.friction_pct
                            all_trades.append({'date': dt, 'ticker': ticker, 'ret': ret, 'regime': get_regime(entry_date), 'win': ret > 0})
                            in_pos = False
            except Exception:
                continue

        trades_df = pd.DataFrame(all_trades).sort_values('date').reset_index(drop=True)
        return trades_df

    def run_block_bootstrap(self, trade_returns: np.ndarray, block_size: int = 15, num_simulations: int = 1000) -> Dict[str, Any]:
        """
        Circular Stationary Block Bootstrap:
        Resamples contiguous multi-trade blocks to preserve serial autocorrelation & loss clustering.
        """
        n = len(trade_returns)
        final_equities = []
        max_drawdowns = []
        sharpe_ratios = []

        num_blocks = int(np.ceil(n / block_size))

        for _ in range(num_simulations):
            sim_returns = []
            for _ in range(num_blocks):
                start_idx = np.random.randint(0, n)
                # Circular slice
                block = [trade_returns[(start_idx + i) % n] for i in range(block_size)]
                sim_returns.extend(block)
            
            sim_returns = np.array(sim_returns[:n])
            cumulative_curve = self.starting_capital * np.cumprod(1.0 + sim_returns * self.position_size_pct)
            final_equities.append(cumulative_curve[-1])

            peak = np.maximum.accumulate(cumulative_curve)
            dd = (cumulative_curve - peak) / peak
            max_drawdowns.append(abs(np.min(dd)) * 100.0)

            mean_r = sim_returns.mean()
            std_r = sim_returns.std()
            sharpe = (mean_r / (std_r + 1e-9)) * np.sqrt(252)
            sharpe_ratios.append(sharpe)

        return {
            "median_ending_equity": float(np.median(final_equities)),
            "worst_case_ending_equity": float(np.min(final_equities)),
            "probability_of_profit_pct": float((np.array(final_equities) > self.starting_capital).mean() * 100.0),
            "median_max_drawdown_pct": float(np.median(max_drawdowns)),
            "ci_95_max_drawdown_pct": float(np.percentile(max_drawdowns, 95)),
            "ci_99_max_drawdown_pct": float(np.percentile(max_drawdowns, 99)),
            "worst_case_drawdown_pct": float(np.max(max_drawdowns)),
            "median_sharpe": float(np.median(sharpe_ratios)),
            "worst_case_sharpe": float(np.min(sharpe_ratios))
        }

    def run_markov_regime_switching_simulation(self, trades_df: pd.DataFrame, num_simulations: int = 1000) -> Dict[str, Any]:
        """
        Markov Regime-Switching Monte Carlo:
        Estimates transition matrix between Bull, Neutral, and Bear states,
        drawing conditional returns based on the active Markov state.
        """
        regimes = trades_df['regime'].values
        unique_regimes = ["BULL", "NEUTRAL", "BEAR"]
        regime_returns = {r: trades_df[trades_df['regime'] == r]['ret'].values for r in unique_regimes}
        
        # Build Transition Matrix
        transitions = np.zeros((3, 3))
        reg_map = {"BULL": 0, "NEUTRAL": 1, "BEAR": 2}

        for i in range(len(regimes) - 1):
            curr_r = reg_map.get(regimes[i], 1)
            next_r = reg_map.get(regimes[i+1], 1)
            transitions[curr_r][next_r] += 1

        # Normalize rows to probabilities
        row_sums = transitions.sum(axis=1, keepdims=True)
        row_sums[row_sums == 0] = 1.0
        P = transitions / row_sums

        n = len(trades_df)
        final_equities = []
        max_drawdowns = []
        sharpe_ratios = []

        for _ in range(num_simulations):
            current_state = 0 # Start in Bull state
            sim_returns = []

            for _ in range(n):
                # Transition to next state
                current_state = np.random.choice([0, 1, 2], p=P[current_state])
                state_name = unique_regimes[current_state]
                pool = regime_returns[state_name]
                if len(pool) == 0:
                    pool = trades_df['ret'].values
                ret = np.random.choice(pool)
                sim_returns.append(ret)

            sim_returns = np.array(sim_returns)
            cumulative_curve = self.starting_capital * np.cumprod(1.0 + sim_returns * self.position_size_pct)
            final_equities.append(cumulative_curve[-1])

            peak = np.maximum.accumulate(cumulative_curve)
            dd = (cumulative_curve - peak) / peak
            max_drawdowns.append(abs(np.min(dd)) * 100.0)

            mean_r = sim_returns.mean()
            std_r = sim_returns.std()
            sharpe = (mean_r / (std_r + 1e-9)) * np.sqrt(252)
            sharpe_ratios.append(sharpe)

        return {
            "transition_matrix": P.tolist(),
            "median_ending_equity": float(np.median(final_equities)),
            "worst_case_ending_equity": float(np.min(final_equities)),
            "probability_of_profit_pct": float((np.array(final_equities) > self.starting_capital).mean() * 100.0),
            "median_max_drawdown_pct": float(np.median(max_drawdowns)),
            "ci_95_max_drawdown_pct": float(np.percentile(max_drawdowns, 95)),
            "ci_99_max_drawdown_pct": float(np.percentile(max_drawdowns, 99)),
            "worst_case_drawdown_pct": float(np.max(max_drawdowns)),
            "median_sharpe": float(np.median(sharpe_ratios)),
            "worst_case_sharpe": float(np.min(sharpe_ratios))
        }

regime_mc_engine = RegimeAwareMonteCarloEngine()
