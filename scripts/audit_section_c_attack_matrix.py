import sys
import os
from unittest.mock import patch
from typing import Dict, Any, List
from src.config.settings import settings
from src.ai.scoring_engine import ai_scoring
from src.agents.boardroom import boardroom
from src.portfolio.portfolio_constructor import portfolio_constructor
from src.portfolio.capital_manager import capital_manager
from src.risk.risk_engine import risk_engine

def get_valid_snapshot(price: float):
    return {
        "current_price": price,
        "indicators": {
            "sma_20": price * 0.98,
            "sma_50": price * 0.95,
            "sma_200": price * 0.90,
            "rsi": 52.0,
            "macd": 1.5,
            "macd_signal": 1.0,
            "macd_hist": 0.5,
            "vol_ratio": 1.4,
            "obv_trending_up": True,
            "bb_width": 0.08,
            "bb_lower": price * 0.96,
            "bb_upper": price * 1.04,
            "atr": price * 0.02
        }
    }

def run_scenario(
    scenario_id: int,
    name: str,
    candidates_data: List[Dict[str, Any]],
    core_capital: float = 50000.0,
    available_cash: float = 50000.0,
    active_capital: float = 0.0,
    existing_positions: List[Dict[str, Any]] = None,
    market_regime: str = "BULL",
    day_drawdown_pct: float = 0.0,
    strategy_id: str = "V2"
) -> Dict[str, Any]:
    existing_positions = existing_positions or []
    allowance, target_pct = capital_manager.calculate_deployment_allowance(
        core_capital, active_capital, market_regime, strategy_id=strategy_id
    )
    
    qualified_count = 0
    approved_count = 0
    rejected_reasons = []
    orders_placed = 0
    capital_deployed_run = 0.0
    current_cash = available_cash
    current_active = active_capital
    held_positions = list(existing_positions)
    
    min_cash_floor = core_capital * (settings.REQUIRED_CASH_RESERVE_PCT / 100.0) if strategy_id == "V1" else core_capital * settings.MIN_CASH_BUFFER_PCT
    min_chunk = core_capital * (settings.MIN_POSITION_SIZE_PCT / 100.0)
    
    binding_constraint = "NONE"
    
    if day_drawdown_pct >= 0.05:
        return {
            "scenario": f"{scenario_id}. {name}",
            "qualified": len(candidates_data),
            "approved": 0,
            "rejected": f"ALL rejected: Circuit breaker tripped ({day_drawdown_pct*100:.1f}%)",
            "orders": 0,
            "capital_deployed": 0.0,
            "cash": available_cash,
            "utilisation_pct": round((active_capital / core_capital) * 100.0, 1),
            "binding_constraint": "PORTFOLIO_CIRCUIT_BREAKER_5PCT"
        }
        
    for cand in candidates_data:
        sym = cand["symbol"]
        price = cand["price"]
        sector = cand.get("sector", "Technology")
        raw_tech = cand["tech_score"]
        
        # Technical & Boardroom Gating
        snap = cand.get("snapshot", get_valid_snapshot(price))
        factors = ai_scoring.evaluate_factor_scores(
            snap,
            market_regime, 
            portfolio_exposure_pct=(current_active / core_capital)*100.0,
            cost_friction_pct=0.10,
            strategy_id=strategy_id
        )
        
        approved_board, b_decision = boardroom.convene_boardroom(
            symbol=sym,
            factors=factors,
            technical_confidence=raw_tech,
            market_regime=market_regime,
            risk_approved=True,
            cost_approved=True
        )
        
        if not approved_board:
            rejected_reasons.append(f"{sym}: Failed Boardroom Gate ({b_decision['overall_confidence']:.1f}% < 75.0%)")
            continue
            
        qualified_count += 1
        
        # Position Sizing
        units, nominal_cost, meta = portfolio_constructor.calculate_optimal_position_size(
            symbol=sym,
            price=price,
            atr=price * 0.02,
            df=cand.get("vol", 0.20),
            core_capital=core_capital,
            available_cash=current_cash,
            remaining_capacity=allowance,
            alpha_score=raw_tech,
            current_holding_val=0.0,
            active_positions_dfs=cand.get("active_positions_dfs", {})
        )
        
        if units <= 0 or nominal_cost < min_chunk:
            rejected_reasons.append(f"{sym}: Sizing below min chunk (£{nominal_cost:.2f} < £{min_chunk:.2f})")
            binding_constraint = "MIN_POSITION_CHUNK_OR_CAPACITY"
            continue
            
        # Exposure Risk Gate
        with patch("src.risk.risk_engine.db.get_trades", return_value=[]):
            risk_ok, risk_msg = risk_engine.validate_exposure_order(
                symbol=sym,
                t212_ticker=cand.get("ticker", f"{sym}_EQ"),
                sector=sector,
                order_cost=nominal_cost,
                core_capital=core_capital,
                available_cash=current_cash,
                current_positions=held_positions,
                remaining_regime_allowance=allowance
            )
        
        if not risk_ok:
            rejected_reasons.append(f"{sym}: Risk Veto - {risk_msg}")
            if "sector" in risk_msg.lower():
                binding_constraint = "SECTOR_CONCENTRATION_30PCT"
            elif "max concurrent positions" in risk_msg.lower():
                binding_constraint = "MAX_CONCURRENT_POSITIONS_15"
            elif "cash" in risk_msg.lower():
                binding_constraint = "CASH_SAFETY_BUFFER_5PCT"
            else:
                binding_constraint = "RISK_ENGINE_VETO"
            continue
            
        # Capital Allocation Floor Check
        if allowance < min_chunk or (current_cash - nominal_cost) < min_cash_floor:
            rejected_reasons.append(f"{sym}: Cash floor limit reached")
            binding_constraint = "REGIME_ALLOWANCE_OR_CASH_FLOOR"
            continue
            
        # Order Approved & Placed
        approved_count += 1
        orders_placed += 1
        capital_deployed_run += nominal_cost
        current_cash -= nominal_cost
        current_active += nominal_cost
        allowance -= nominal_cost
        held_positions.append({
            "ticker": cand.get("ticker", f"{sym}_EQ"),
            "symbol": sym,
            "quantity": units,
            "currentPrice": price,
            "market_value_gbp": nominal_cost,
            "sector": sector
        })

    utilization = round((current_active / core_capital) * 100.0, 1)
    if binding_constraint == "NONE" and approved_count > 0:
        binding_constraint = "POSITION_SIZING_ALGORITHM"
    elif binding_constraint == "NONE" and qualified_count == 0:
        binding_constraint = "QUALITY_HURDLE_75PCT"

    return {
        "scenario": f"{scenario_id}. {name}",
        "qualified": qualified_count,
        "approved": approved_count,
        "rejected": "; ".join(rejected_reasons[:2]) if rejected_reasons else "NONE",
        "orders": orders_placed,
        "capital_deployed": round(capital_deployed_run, 2),
        "cash": round(current_cash, 2),
        "utilisation_pct": utilization,
        "binding_constraint": binding_constraint
    }

# 15 Deterministic Scenarios
scenarios = [
    (1, "Zero qualifying securities", [{"symbol": f"WEAK_{i}", "price": 50.0, "tech_score": 60.0} for i in range(10)], 50000, 50000, 0, []),
    (2, "One qualifying security", [{"symbol": "QUAL_1", "price": 100.0, "tech_score": 85.0}], 50000, 50000, 0, []),
    (3, "Five qualifying securities", [{"symbol": f"QUAL_{i}", "price": 50.0, "tech_score": 82.0, "sector": f"Sector_{i}"} for i in range(5)], 50000, 50000, 0, []),
    (4, "More qualifying securities than capacity", [{"symbol": f"QUAL_{i}", "price": 50.0, "tech_score": 82.0, "sector": f"Sec_{i%6}"} for i in range(20)], 50000, 50000, 0, []),
    (5, "Qualifying across many sectors", [{"symbol": f"QUAL_{i}", "price": 50.0, "tech_score": 82.0, "sector": f"Sector_{i}"} for i in range(10)], 50000, 50000, 0, []),
    (6, "All qualifying in one sector", [{"symbol": f"FIN_{i}", "price": 50.0, "tech_score": 82.0, "sector": "Financials"} for i in range(8)], 50000, 50000, 0, []),
    (7, "Highly correlated qualifying securities", [{"symbol": f"CORR_{i}", "price": 50.0, "tech_score": 82.0, "sector": "Tech"} for i in range(5)], 50000, 50000, 0, []),
    (8, "Abundant qualifying with £50k cash", [{"symbol": f"OPP_{i}", "price": 50.0, "tech_score": 85.0, "sector": f"Sector_{i%5}"} for i in range(15)], 50000, 50000, 0, []),
    (9, "Almost no available cash (£2,800)", [{"symbol": "CAND_1", "price": 50.0, "tech_score": 85.0}], 50000, 2800, 47200, []),
    (10, "Capital released after exit", [{"symbol": "RECYCLE_1", "price": 50.0, "tech_score": 85.0}], 50000, 20000, 30000, []),
    (11, "Simultaneous exits & opportunities", [{"symbol": f"NEW_{i}", "price": 50.0, "tech_score": 85.0, "sector": f"Sec_{i}"} for i in range(3)], 50000, 25000, 25000, []),
    (12, "Daily loss corridor reached", [{"symbol": "OPP_1", "price": 50.0, "tech_score": 85.0}], 50000, 50000, 0, [], "BULL", 0.05),
    (13, "Profit corridor reached", [{"symbol": f"POST_PROFIT_{i}", "price": 50.0, "tech_score": 85.0, "sector": f"Sec_{i}"} for i in range(2)], 50000, 45000, 5000, []),
    (14, "Risk budget exhausted (95% deployed)", [{"symbol": "BUDGET_EXH", "price": 50.0, "tech_score": 85.0}], 50000, 2500, 47500, []),
    (15, "Maximum positions reached (15 held)", [{"symbol": "NEW_16", "price": 50.0, "tech_score": 85.0}], 50000, 20000, 30000, [{"ticker": f"POS_{i}", "symbol": f"POS_{i}", "quantity": 10, "currentPrice": 50, "market_value_gbp": 2000, "sector": f"Sec_{i%5}"} for i in range(15)])
]

print("=" * 115)
print(f"{'Scenario':<40} | {'Qual':<4} | {'Appr':<4} | {'Orders':<6} | {'Deployed':<10} | {'Cash':<10} | {'Util%':<5} | {'Binding Constraint':<30}")
print("=" * 115)

for s in scenarios:
    res = run_scenario(*s)
    scen_str = res['scenario'][:38]
    print(f"{scen_str:<40} | {res['qualified']:<4} | {res['approved']:<4} | {res['orders']:<6} | £{res['capital_deployed']:<9.2f} | £{res['cash']:<9.2f} | {res['utilisation_pct']:<5.1f} | {res['binding_constraint']:<30}")

print("=" * 115)
