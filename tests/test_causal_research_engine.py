"""
🏛️ PRV CAPITAL | CAUSAL RESEARCH ENGINE RATIFICATION & MUTATION TEST SUITE
Proves that impossible information timing, same-bar lookahead, and reverse-time fills
are structurally and irrevocably prevented by the engine architecture.
"""
import unittest
import pandas as pd
import numpy as np
from datetime import datetime, date, time, timedelta

from src.research.cost_schedule import (
    CostScheduleRepository,
    Jurisdiction,
    InstrumentClass
)
from src.research.causal_engine import (
    CausalBar,
    CausalFeature,
    CausalDecision,
    CausalMarketDatabase,
    CausalIndicatorEngine,
    CausalPreEntryCostGate,
    CausalExecutionEngine,
    CausalityViolationError,
    PreEntryCostAssessment
)


class TestCausalTemporalInvariants(unittest.TestCase):
    """
    Mandatory mutation test suite asserting zero temporal lookahead leaks.
    """

    def test_feature_observation_timestamp_cannot_exceed_as_of(self):
        """MUTATION TEST: Feature observed in future relative to decision timestamp must fail."""
        as_of = pd.Timestamp("2026-09-08 09:30:00")
        future_obs = pd.Timestamp("2026-09-08 10:00:00")  # 30 mins in future

        with self.assertRaises(CausalityViolationError) as ctx:
            CausalFeature(
                name="LEAKY_MOMENTUM",
                value=105.5,
                feature_observation_timestamp=future_obs,
                as_of_timestamp=as_of
            )
        self.assertIn("FAIL-CLOSED CAUSALITY LEAK", str(ctx.exception))
        self.assertIn("exceeds decision as_of_timestamp", str(ctx.exception))

    def test_completed_eod_bar_cannot_produce_same_day_morning_fill(self):
        """MUTATION TEST: Completed 16:30 EOD bar cannot execute at 08:00 same-day open."""
        exec_sim = CausalExecutionEngine()
        
        # Decision formed at 16:30 EOD
        as_of = pd.Timestamp("2026-09-08 16:30:00")
        decision = CausalDecision(
            decision_id="DEC_001",
            as_of_timestamp=as_of,
            decision_type="ENTER",
            symbol="CSP1.L",
            features={}
        )

        # 1D bar for 2026-09-08
        daily_bar = CausalBar(
            symbol="CSP1.L",
            bar_start_timestamp=pd.Timestamp("2026-09-08 08:00:00"),
            bar_end_timestamp=pd.Timestamp("2026-09-08 16:30:00"),
            published_timestamp=pd.Timestamp("2026-09-08 16:30:00"),
            open_price=613.12,
            high_price=619.46,
            low_price=607.13,
            close_price=612.37,
            volume=14500,
            timeframe="1d"
        )

        # Attempt to fill at same day 08:00 Open
        illegal_fill_time = pd.Timestamp("2026-09-08 08:00:00")

        with self.assertRaises(CausalityViolationError) as ctx:
            exec_sim.execute_order(
                decision=decision,
                execution_bar=daily_bar,
                fill_timestamp=illegal_fill_time
            )
        self.assertIn("FAIL-CLOSED", str(ctx.exception))

    def test_fill_timestamp_cannot_precede_decision_timestamp(self):
        """MUTATION TEST: Fill timestamp earlier than decision timestamp must fail."""
        exec_sim = CausalExecutionEngine()
        decision_time = pd.Timestamp("2026-09-08 10:15:00")
        illegal_fill_time = pd.Timestamp("2026-09-08 10:14:59")  # 1 second before

        decision = CausalDecision(
            decision_id="DEC_002",
            as_of_timestamp=decision_time,
            decision_type="ENTER",
            symbol="ISF.L",
            features={}
        )

        bar_5m = CausalBar(
            symbol="ISF.L",
            bar_start_timestamp=pd.Timestamp("2026-09-08 10:10:00"),
            bar_end_timestamp=pd.Timestamp("2026-09-08 10:15:00"),
            published_timestamp=pd.Timestamp("2026-09-08 10:15:00"),
            open_price=10.55,
            high_price=10.58,
            low_price=10.54,
            close_price=10.57,
            volume=5000,
            timeframe="5m"
        )

        with self.assertRaises(CausalityViolationError) as ctx:
            exec_sim.execute_order(
                decision=decision,
                execution_bar=bar_5m,
                fill_timestamp=illegal_fill_time
            )
        self.assertIn("prior to decision as_of_timestamp", str(ctx.exception))

    def test_market_database_does_not_return_uncompleted_or_future_bars(self):
        """MUTATION TEST: Querying database at 10:00 must NEVER return 10:00-10:05 bar or 16:30 bar."""
        db = CausalMarketDatabase()
        
        bars = [
            CausalBar(
                symbol="CSP1.L",
                bar_start_timestamp=pd.Timestamp("2026-09-08 09:50:00"),
                bar_end_timestamp=pd.Timestamp("2026-09-08 09:55:00"),
                published_timestamp=pd.Timestamp("2026-09-08 09:55:00"),
                open_price=612.0, high_price=613.0, low_price=611.5, close_price=612.8, volume=100
            ),
            CausalBar(
                symbol="CSP1.L",
                bar_start_timestamp=pd.Timestamp("2026-09-08 09:55:00"),
                bar_end_timestamp=pd.Timestamp("2026-09-08 10:00:00"),
                published_timestamp=pd.Timestamp("2026-09-08 10:00:00"),
                open_price=612.8, high_price=613.5, low_price=612.6, close_price=613.2, volume=150
            ),
            CausalBar(
                symbol="CSP1.L",
                bar_start_timestamp=pd.Timestamp("2026-09-08 10:00:00"),
                bar_end_timestamp=pd.Timestamp("2026-09-08 10:05:00"),
                published_timestamp=pd.Timestamp("2026-09-08 10:05:00"),  # Published at 10:05!
                open_price=613.2, high_price=614.0, low_price=613.0, close_price=613.9, volume=200
            )
        ]
        db.register_bars("CSP1.L", bars)

        # Query at 10:00:00
        visible_bars = db.get_completed_bars_up_to("CSP1.L", pd.Timestamp("2026-09-08 10:00:00"))
        self.assertEqual(len(visible_bars), 2)
        # Bar 3 (published at 10:05) must not be in visible bars!
        self.assertNotIn(pd.Timestamp("2026-09-08 10:05:00"), visible_bars.index)
        self.assertEqual(visible_bars.iloc[-1]["Close"], 613.2)

    def test_tod_rvol_strictly_compares_same_time_of_day(self):
        """VERIFICATION: TOD-RVOL compares 10:00 cumulative volume against historical 10:00 volume."""
        # Current day: 08:00 to 10:00 volume = 2,500 shares (5 bars of 500)
        times_today = pd.date_range("2026-09-08 08:00", "2026-09-08 10:00", freq="30min")
        df_today = pd.DataFrame({"Volume": [500, 500, 500, 500, 500]}, index=times_today)

        # Historical 20 days: each day has 1,500 shares up to 10:00, and 10,000 full day
        hist_days = []
        for d in range(1, 21):
            date_str = f"2026-08-{d:02d}"
            morning_idx = pd.date_range(f"{date_str} 08:00", f"{date_str} 10:00", freq="30min")
            afternoon_idx = pd.date_range(f"{date_str} 10:30", f"{date_str} 16:30", freq="30min")
            
            vols = [300] * len(morning_idx) + [653] * len(afternoon_idx)
            full_idx = morning_idx.append(afternoon_idx)
            df_hist = pd.DataFrame({"Volume": vols}, index=full_idx)
            hist_days.append(df_hist)

        as_of = pd.Timestamp("2026-09-08 10:00:00")
        tod_feature = CausalIndicatorEngine.compute_tod_rvol(
            intraday_bars=df_today,
            historical_days=hist_days,
            current_time_of_day=time(10, 0),
            as_of_timestamp=as_of
        )

        # Current 10:00 cum vol = 2500, Mean hist 10:00 cum vol = 1500
        # Expected TOD-RVOL = 2500 / 1500 = 1.67
        self.assertEqual(tod_feature.value, 1.67)
        self.assertEqual(tod_feature.feature_observation_timestamp, as_of)

    def test_pre_entry_economic_cost_gate_rejects_negative_net_trades(self):
        """VERIFICATION: Pre-entry economic gate rejects trade where friction exceeds gross expectancy."""
        cost_repo = CostScheduleRepository()
        gate = CausalPreEntryCostGate(cost_repo)

        # Scenario: Tiny target (+0.10%), but UK Equity paying 0.50% SDRT + spread + slippage
        assessment = gate.assess_candidate(
            symbol="NWG.L",
            jurisdiction=Jurisdiction.UK,
            instrument_class=InstrumentClass.EQUITY,
            entry_price_gbp=3.50,
            target_price_gbp=3.5035,        # +0.10% target (£25 gross on £25k)
            stop_price_gbp=3.486,           # -0.40% stop
            nominal_position_gbp=25000.0,
            expected_win_rate=0.55,
            trade_date=date(2026, 9, 8),
            spread_bps=3.0,
            slippage_bps=2.0
        )

        # Total friction: 0.50% SDRT (£125) + PTM (£3) + spread (£15) + slippage (£10) = £153
        self.assertFalse(assessment.passed_economic_gate)
        self.assertIn("REJECTED", assessment.rejection_reason)
        self.assertGreater(assessment.total_friction_gbp, 100.0)

    def test_pre_entry_economic_cost_gate_approves_positive_net_trades(self):
        """VERIFICATION: Pre-entry economic gate approves trade with solid net edge after all costs."""
        cost_repo = CostScheduleRepository()
        gate = CausalPreEntryCostGate(cost_repo)

        # High-expectancy setup in SDRT-exempt ETF: +1.50% target, -0.75% stop, 60% win rate
        assessment = gate.assess_candidate(
            symbol="CSP1.L",
            jurisdiction=Jurisdiction.UK,
            instrument_class=InstrumentClass.ETF,
            entry_price_gbp=612.0,
            target_price_gbp=621.18,        # +1.50% target (£525 gain on £35k)
            stop_price_gbp=607.41,          # -0.75% stop (£262.50 loss)
            nominal_position_gbp=35000.0,
            expected_win_rate=0.60,
            trade_date=date(2026, 9, 8),
            spread_bps=2.0,
            slippage_bps=2.0
        )

        # Expected Gross: 0.60 * 525 - 0.40 * 262.50 = 315 - 105 = £210.00
        # Friction (ETF: 0 SDRT, PTM £3, spread £14, slippage £14 = £31)
        # Expected Net: ~£179.00 > 0
        self.assertTrue(assessment.passed_economic_gate)
        self.assertIn("PASSED", assessment.rejection_reason)
        self.assertGreater(assessment.expected_net_profit_gbp, 150.0)

    def test_valid_causal_next_day_execution_passes(self):
        """VERIFICATION: Signal observed at 16:30 EOD executing on Day T+1 08:00 Open succeeds causally."""
        exec_sim = CausalExecutionEngine()
        
        # Decision formed at 16:30 EOD on 2026-09-08
        decision_time = pd.Timestamp("2026-09-08 16:30:00")
        decision = CausalDecision(
            decision_id="DEC_VALID",
            as_of_timestamp=decision_time,
            decision_type="ENTER",
            symbol="VUSA.L",
            features={}
        )

        # Day T+1 bar starting at 08:00 Open on 2026-09-09
        next_day_bar = CausalBar(
            symbol="VUSA.L",
            bar_start_timestamp=pd.Timestamp("2026-09-09 08:00:00"),
            bar_end_timestamp=pd.Timestamp("2026-09-09 16:30:00"),
            published_timestamp=pd.Timestamp("2026-09-09 16:30:00"),
            open_price=108.50,
            high_price=109.20,
            low_price=108.30,
            close_price=108.90,
            volume=25000,
            timeframe="1d"
        )

        fill_time = pd.Timestamp("2026-09-09 08:00:00")
        result = exec_sim.execute_order(
            decision=decision,
            execution_bar=next_day_bar,
            fill_timestamp=fill_time,
            position_size_gbp=35000.0
        )

        self.assertEqual(result["status"], "CAUSALLY_FILLED")
        self.assertEqual(result["fill_timestamp"], fill_time)
        self.assertEqual(result["fill_price_gbp"], 108.50)
        self.assertLessEqual(result["notional_gbp"], 35000.0)

    def test_uncompleted_bar_cannot_be_observed_before_published_timestamp(self):
        """MUTATION TEST: Bar close is not observable prior to its published timestamp."""
        bar = CausalBar(
            symbol="CSP1.L",
            bar_start_timestamp=pd.Timestamp("2026-09-08 08:00:00"),
            bar_end_timestamp=pd.Timestamp("2026-09-08 16:30:00"),
            published_timestamp=pd.Timestamp("2026-09-08 16:30:00"),
            open_price=613.12,
            high_price=619.46,
            low_price=607.13,
            close_price=612.37,
            volume=14500,
            timeframe="1d"
        )
        # At 10:00, the bar is NOT completed or observable
        self.assertFalse(bar.is_observable_at(pd.Timestamp("2026-09-08 10:00:00")))
        # At 16:29:59, the bar is NOT completed
        self.assertFalse(bar.is_observable_at(pd.Timestamp("2026-09-08 16:29:59")))
        # At 16:30:00, the bar IS observable
        self.assertTrue(bar.is_observable_at(pd.Timestamp("2026-09-08 16:30:00")))

    def test_orb_cannot_be_established_before_range_end_time(self):
        """MUTATION TEST: ORB cannot be established before the opening range window has fully closed."""
        idx = pd.date_range("2026-09-08 08:00", "2026-09-08 08:15", freq="5min")
        df_early = pd.DataFrame({
            "Open": [612.0, 612.5, 613.0, 613.2],
            "High": [612.8, 613.2, 613.8, 614.0],
            "Low": [611.8, 612.2, 612.9, 613.0],
            "Close": [612.5, 613.0, 613.2, 613.9],
            "Volume": [100, 150, 200, 180]
        }, index=idx)

        # Query at 08:15: ORB end is 08:30 -> MUST NOT be established
        as_of = pd.Timestamp("2026-09-08 08:15:00")
        h, l, feat = CausalIndicatorEngine.compute_opening_range(
            intraday_bars=df_early,
            open_time=time(8, 0),
            range_end_time=time(8, 30),
            as_of_timestamp=as_of
        )
        self.assertIsNone(h)
        self.assertIsNone(l)
        self.assertFalse(feat.value)

    def test_pre_entry_cost_gate_rejects_us_equity_with_high_fx_drag(self):
        """VERIFICATION: US Equity setup with thin gross gain is rejected due to 0.15% round-trip FX."""
        cost_repo = CostScheduleRepository()
        gate = CausalPreEntryCostGate(cost_repo)

        # Thin US trade: +0.30% target on $30,000 (£23,077) position
        assessment = gate.assess_candidate(
            symbol="AAPL",
            jurisdiction=Jurisdiction.US,
            instrument_class=InstrumentClass.EQUITY,
            entry_price_gbp=175.0,
            target_price_gbp=175.525,       # +0.30% target (£69 gross on £23,077)
            stop_price_gbp=174.475,         # -0.30% stop
            nominal_position_gbp=23077.0,
            expected_win_rate=0.55,
            trade_date=date(2026, 9, 8),
            spread_bps=2.0,
            slippage_bps=2.0
        )
        # Round-trip FX is 0.30% (£69.23), which immediately wipes out the entire edge!
        self.assertFalse(assessment.passed_economic_gate)
        self.assertIn("REJECTED", assessment.rejection_reason)
        self.assertGreater(assessment.fx_friction_gbp, 60.0)

    def test_causal_auditor_detects_lookahead_leaks(self):
        """AUDIT TEST: CausalAuditor fails closed when presented with lookahead or reverse-time trades."""
        from src.research.causal_auditor import CausalAuditor

        flawed_trades = [
            {
                "trade_id": "TRD_LEAK_01",
                "symbol": "CSP1.L",
                "decision_time": "2026-09-08 16:30:00",
                "entry_time": "2026-09-08 08:00:00",  # Same day morning open!
                "exit_time": "2026-09-09 08:00:00",
                "notional_gbp": 35000.0,
                "total_friction_gbp": 31.0
            }
        ]
        report = CausalAuditor.audit_trade_execution_history(flawed_trades)
        self.assertFalse(report.passed)
        self.assertFalse(report.audit_results["TIMESTAMP_CAUSALITY"])
        self.assertFalse(report.audit_results["ANTI_SAME_BAR_LOOKAHEAD"])
        self.assertGreater(len(report.violations), 0)

    def test_causal_auditor_passes_clean_causal_trades(self):
        """AUDIT TEST: CausalAuditor passes cleanly when all trades are forward-causal."""
        from src.research.causal_auditor import CausalAuditor

        clean_trades = [
            {
                "trade_id": "TRD_CLEAN_01",
                "symbol": "VUSA.L",
                "decision_time": "2026-09-08 16:30:00",
                "entry_time": "2026-09-09 08:00:00",  # Day T+1 morning open!
                "exit_time": "2026-09-10 08:00:00",
                "notional_gbp": 35000.0,
                "total_friction_gbp": 31.0
            }
        ]
        report = CausalAuditor.audit_trade_execution_history(clean_trades)
        self.assertTrue(report.passed)
        self.assertTrue(report.audit_results["TIMESTAMP_CAUSALITY"])
        self.assertTrue(report.audit_results["ANTI_SAME_BAR_LOOKAHEAD"])
        self.assertEqual(len(report.violations), 0)


if __name__ == "__main__":
    unittest.main()
