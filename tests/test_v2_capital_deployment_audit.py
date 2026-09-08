"""
🏛️ PRV CAPITAL | STRATEGY V2 CAPITAL DEPLOYMENT AUDIT & REGRESSION SUITE
Enforces:
1. FIX 1 - REGIME SEMANTIC PARITY:
   - V2 evaluates "BULL" as 75.0, "STRONG" as 75.0, "EXCEPTIONAL" as 95.0, and "NEUTRAL"/"BEAR" as 45.0.
   - V1 scoring remains bit-for-bit unchanged ("EXCEPTIONAL" = 95.0, "STRONG" = 75.0, else 45.0).
2. FIX 2 - CASH FLOOR DECOUPLING:
   - V1 strictly preserves the 45% cash reserve floor (£22,500) and 55% deployment cap (£27,500).
   - V2 dynamically allows deployment up to 95% of Core Capital (holding only 5% operational safety buffer £2,500).
3. NO FORCED TRADING:
   - Candidates below the 75% confidence hurdle are strictly rejected; cash remains preserved.
4. INVARIANT HASH INTEGRITY:
   - Parameter manifest hash remains strictly invariant.
"""
import unittest
from src.config.settings import settings
from src.ai.scoring_engine import ai_scoring
from src.agents.boardroom import boardroom
from src.portfolio.portfolio_constructor import portfolio_constructor
from src.portfolio.capital_manager import capital_manager


class TestV2CapitalDeploymentAudit(unittest.TestCase):

    def setUp(self):
        self.orig_entries = settings.PRACTICE_NEW_ENTRIES_ALLOWED
        settings.PRACTICE_NEW_ENTRIES_ALLOWED = True
        self.mock_snapshot = {
            "current_price": 100.0,
            "indicators": {
                "sma_20": 98.0,
                "sma_50": 95.0,
                "sma_200": 90.0,
                "rsi": 52.0,
                "macd": 1.5,
                "macd_signal": 1.0,
                "macd_hist": 0.5,
                "vol_ratio": 1.4,
                "obv_trending_up": True,
                "bb_width": 0.08,
                "bb_lower": 96.0,
                "bb_upper": 104.0
            }
        }

    def tearDown(self):
        settings.PRACTICE_NEW_ENTRIES_ALLOWED = self.orig_entries

    def test_1_manifest_hash_invariance(self):
        """Invariant: Settings parameter manifest hash must remain strictly unchanged."""
        expected_hash = "7c512be5bc26910c1c4ed81a3e650480a676cd750faa49bc8dbd8901360bc708"
        self.assertEqual(settings.get_parameter_manifest_hash(), expected_hash)

    def test_2_fix_1_v2_regime_semantic_parity(self):
        """
        Fix 1 Test: V2 recognizes 'BULL' as 75.0, matching 'STRONG'.
        NEUTRAL and BEAR remain at the 45.0 baseline.
        """
        factors_bull = ai_scoring.evaluate_factor_scores(self.mock_snapshot, "BULL", 30.0, 0.10, strategy_id="V2")
        factors_strong = ai_scoring.evaluate_factor_scores(self.mock_snapshot, "STRONG", 30.0, 0.10, strategy_id="V2")
        factors_exceptional = ai_scoring.evaluate_factor_scores(self.mock_snapshot, "EXCEPTIONAL", 30.0, 0.10, strategy_id="V2")
        factors_neutral = ai_scoring.evaluate_factor_scores(self.mock_snapshot, "NEUTRAL", 30.0, 0.10, strategy_id="V2")
        factors_bear = ai_scoring.evaluate_factor_scores(self.mock_snapshot, "BEAR", 30.0, 0.10, strategy_id="V2")

        self.assertEqual(factors_bull["market_regime"], 75.0)
        self.assertEqual(factors_strong["market_regime"], 75.0)
        self.assertEqual(factors_exceptional["market_regime"], 95.0)
        self.assertEqual(factors_neutral["market_regime"], 45.0)
        self.assertEqual(factors_bear["market_regime"], 45.0)

    def test_3_fix_1_v1_legacy_scoring_preserved(self):
        """
        Fix 1 Invariant: V1 scoring path remains bit-for-bit unchanged.
        'STRONG' -> 75.0, 'EXCEPTIONAL' -> 95.0, 'BULL' -> 45.0 (unrecognized in V1).
        """
        v1_strong = ai_scoring.evaluate_factor_scores(self.mock_snapshot, "STRONG", 30.0, 0.10, strategy_id="V1")
        v1_bull = ai_scoring.evaluate_factor_scores(self.mock_snapshot, "BULL", 30.0, 0.10, strategy_id="V1")
        v1_exceptional = ai_scoring.evaluate_factor_scores(self.mock_snapshot, "EXCEPTIONAL", 30.0, 0.10, strategy_id="V1")
        v1_neutral = ai_scoring.evaluate_factor_scores(self.mock_snapshot, "NEUTRAL", 30.0, 0.10, strategy_id="V1")

        self.assertEqual(v1_strong["market_regime"], 75.0)
        self.assertEqual(v1_bull["market_regime"], 45.0) # V1 does not recognize BULL
        self.assertEqual(v1_exceptional["market_regime"], 95.0)
        self.assertEqual(v1_neutral["market_regime"], 45.0)

    def test_4_fix_2_v1_enforces_legacy_45pct_cash_floor(self):
        """
        Fix 2 Invariant: V1 strictly enforces 45% cash floor / 55% deployment cap (£27,500 max).
        """
        core_capital = 50000.0
        active_capital = 20000.0 # 40% active

        # In BULL regime, V1 allows up to 55% (£27,500). Remaining allowance is £7,500.
        allowance, target_pct = capital_manager.calculate_deployment_allowance(
            core_capital, active_capital, "BULL", strategy_id="V1"
        )
        self.assertEqual(target_pct, 0.55)
        self.assertEqual(allowance, 7500.0)

        # Idle cash audit reflects the macro regime reserve
        audit = capital_manager.generate_idle_cash_audit(
            core_capital=core_capital,
            available_cash=30000.0,
            active_capital=active_capital,
            market_regime="BULL",
            strategy_id="V1"
        )
        self.assertEqual(len(audit), 3) # Buffer, Regime Reserve, Opportunity Queue
        self.assertEqual(audit[0]["amount"], 2500.0) # Buffer
        self.assertEqual(audit[1]["amount"], 20000.0) # 45% floor - 5% buffer = 40% = £20,000

    def test_5_fix_2_v2_removes_45pct_floor_and_deploys_up_to_95pct(self):
        """
        Fix 2 Invariant: V2 dynamically deploys up to 95% (£47,500) on qualifying setups.
        Only a 5% operational safety buffer (£2,500) is held.
        """
        core_capital = 50000.0
        active_capital = 20134.04 # Exact live deployed amount today (40.3% of NAV)

        allowance, target_pct = capital_manager.calculate_deployment_allowance(
            core_capital, active_capital, "BULL", strategy_id="V2"
        )
        self.assertEqual(target_pct, 0.95)
        expected_allowance = round(50000.0 * 0.95 - 20134.04, 2) # £27,365.96
        self.assertEqual(allowance, expected_allowance)

        audit = capital_manager.generate_idle_cash_audit(
            core_capital=core_capital,
            available_cash=29765.30,
            active_capital=active_capital,
            market_regime="BULL",
            strategy_id="V2"
        )
        # In V2, no unallocated regime reserve is withheld; entire excess cash goes to Opportunity Queue
        self.assertEqual(len(audit), 2) # Buffer + Opportunity Queue
        self.assertEqual(audit[0]["bucket"], "Cash Safety Buffer")
        self.assertEqual(audit[0]["amount"], 2500.0)
        self.assertEqual(audit[1]["bucket"], "High-Conviction Opportunity Queue")
        self.assertEqual(audit[1]["amount"], round(29765.30 - 2500.0, 2))

    def test_6_no_forced_trading_when_market_fails_hurdles(self):
        """
        NO-FORCED-TRADING TEST:
        When candidates fail technical/quality hurdles, V2 strictly rejects them and stays in cash.
        """
        weak_factors = {
            "trend_strength": 30.0,
            "relative_strength": 25.0,
            "momentum": 30.0,
            "volume_confirmation": 35.0,
            "volatility_condition": 30.0,
            "market_regime": 75.0, # Even in BULL regime
            "portfolio_exposure": 80.0,
            "trading_cost_impact": 60.0
        }
        low_confidence = 52.5

        approved, decision = boardroom.convene_boardroom(
            symbol="WEAK_ASSET",
            factors=weak_factors,
            technical_confidence=low_confidence,
            market_regime="BULL",
            risk_approved=True,
            cost_approved=True
        )

        self.assertFalse(approved, "V2 must reject low-confidence setup")
        self.assertIn("REJECTED", decision["reasoning"])
        self.assertLess(decision["overall_confidence"], settings.MIN_CONFIDENCE_THRESHOLD)

    def test_7_qualifying_market_deployment_approval(self):
        """
        QUALIFYING-MARKET DEPLOYMENT TEST:
        When candidates satisfy all technical, boardroom, risk, and cost requirements,
        V2 approves them and sizes them cleanly.
        """
        strong_factors = {
            "trend_strength": 90.0,
            "relative_strength": 85.0,
            "momentum": 90.0,
            "volume_confirmation": 80.0,
            "volatility_condition": 80.0,
            "market_regime": 75.0,
            "portfolio_exposure": 80.0,
            "trading_cost_impact": 95.0
        }
        high_confidence = 84.5

        approved, decision = boardroom.convene_boardroom(
            symbol="QUAL_ASSET",
            factors=strong_factors,
            technical_confidence=high_confidence,
            market_regime="BULL",
            risk_approved=True,
            cost_approved=True
        )

        self.assertTrue(approved, "V2 must approve high-confidence qualifying setup")
        self.assertIn("APPROVED", decision["reasoning"])
        self.assertGreaterEqual(decision["overall_confidence"], settings.MIN_CONFIDENCE_THRESHOLD)

    def test_8_dynamic_position_sizing_and_cash_preservation(self):
        """
        Verifies that portfolio constructor allocates healthy position size (3% - 8%)
        for a qualifying high-alpha candidate without violating cash safety buffer.
        """
        units, cost, meta = portfolio_constructor.calculate_optimal_position_size(
            symbol="QUAL_ASSET",
            price=50.0,
            atr=1.2,
            df=0.20,
            core_capital=50000.0,
            available_cash=32000.0,
            remaining_capacity=27000.0,
            alpha_score=85.0,
            current_holding_val=0.0,
            active_positions_dfs=[]
        )

        self.assertGreater(units, 0, "Units must be > 0 for qualifying candidate")
        self.assertGreaterEqual(cost, 1500.0, "Cost must be at least 3% min chunk (£1,500)")
        self.assertLessEqual(cost, 4500.0, "Cost must not exceed 8% max cap + buffer")


if __name__ == "__main__":
    unittest.main()
