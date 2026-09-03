# PRV CAPITAL | FULL REPOSITORY RED-TEAM AUDIT & SYSTEM REBUILD

## Executive Summary
This document records the baseline state, defect inventory, root cause analysis, architectural blueprint, and certification plan for PRV Capital. The objective is an autonomous, mathematically reconciled, and resilient practice trading system with positive net expectancy after all realistic friction costs.

---

## 1. Baseline Inventory (Phase 1)
- **Git Commit Hash**: `85aae61` (Snapshot tag: `pre_full_system_red_team`, Branch: `audit/pre_full_system_red_team`)
- **Python Runtime**: Python 3.14.7 (macOS)
- **Active Environment**: `TRADING_ENV=demo`
- **Account Mode**: `ACCOUNT_MODE=PRACTICE`
- **Configuration Version**: `CONFIG_V3.0_PRACTICE_30DAY_CHALLENGE_20260902`
- **Database Schema**: SQLite 56 tables (`user_version: 0`), Supabase RLS migrations 002 & 003
- **Audit Governance**: `PRACTICE_NEW_ENTRIES_ALLOWED = FALSE`, `REAL_MONEY_TRADING_ENABLED = FALSE`, Challenge status archived as `PRE_AUDIT_DIAGNOSTIC_PERIOD`.

---

## 2. Critical Defect Inventory & Root Causes (Phase 2 & Phase 3)

| Defect ID | Severity | File & Location | Description & Root Cause |
| :--- | :--- | :--- | :--- |
| **DEF-01** | CRITICAL | `src/core/engine.py:46` | `self.paper_mode` set via non-existent `DRY_RUN_PAPER_ONLY`, defaulting to `False` (Live mode) even when `ACCOUNT_MODE=PRACTICE`. Causes mode ambiguity across order router. |
| **DEF-02** | CRITICAL | `src/core/engine.py:448` | `settings.NORMAL_LIVE_ENTRIES_ALLOWED` attribute error: attribute does not exist on `TradingSettings`. Would crash on LIVE entry evaluation. |
| **DEF-03** | CRITICAL | `src/execution/order_router.py:199-204` | Order router bypasses `PRACTICE_NEW_ENTRIES_ALLOWED` check when `is_paper=True` and bypasses `REAL_MONEY_TRADING_ENABLED` check when `is_paper=False`. |
| **DEF-04** | CRITICAL | `src/portfolio/portfolio_snapshot.py:139-148` | Stale-data contamination: Empty position list (`[]`) from broker interpreted as network glitch, causing resurrecting of 11 old positions from `broker_positions_cache.json`. |
| **DEF-05** | CRITICAL | `src/portfolio/portfolio_snapshot.py:244` | Hardcoded fallback cash `22625.20` used if broker summary free cash key is missing, contaminating NAV. |
| **DEF-06** | HIGH | `src/portfolio/portfolio_snapshot.py:337-347` | P&L Bridge Tautology: `spread_and_slippage_drag` calculated as plug figure `total_incurred_friction - total_sdrt_paid - total_fx_paid` to force mathematical identity rather than ledger-reconciled. |
| **DEF-07** | HIGH | `src/analytics/live_evidence_tracker.py:345-350` | Hardcoded telemetry placeholder values (`avg_open_mfe_pct: 3.82`, `current_unrealized_pnl_gbp: 212.97`, `active_holdings: 7`, `signals_generated: 103`) masquerading as live calculation. |
| **DEF-08** | HIGH | `src/analytics/practice_challenge_engine.py:132-136, 188-195` | Hardcoded counterfactual savings (`costs_avoided_by_gate: 1845.60`, `gross_losses_avoided: 3420.50`) and funnel numbers presented as analysis. |
| **DEF-09** | HIGH | `src/brokers/trading212.py:212, 223, 234` | Swallowed exceptions returning empty or cached values silently without health/freshness flags or age timestamps. |
| **DEF-10** | MEDIUM | `src/data/market_hours.py` | Simple binary open/closed checks lacking explicit session states (`PRE_MARKET`, `REGULAR`, `AFTER_HOURS`, `OVERNIGHT`, `FULLY_CLOSED`, `HOLIDAY`). |
| **DEF-11** | MEDIUM | Repository-wide | Lack of strongly-typed `Money` class leading to raw float arithmetic and potential currency/unit confusion (GBX vs GBP vs USD). |
| **DEF-12** | MEDIUM | `src/execution/order_router.py` | Lacks formal order state machine with client order IDs, idempotency keys, and explicit atomic state transitions. |
| **DEF-13** | MEDIUM | `src/core/engine.py:452` | Numerical literals (`500.0`, `2500.0`) in cash checks rather than central settings. |
| **DEF-14** | MEDIUM | `src/core/engine.py:435-487` | Concurrency race: multiple candidates could evaluate against same cash allowance simultaneously without atomic reservations. |

---

## 3. Architecture Blueprint for System Rebuild

### 3.1 Strong Type Model: `Money` and `Currency` (Phase 4)
- Value objects `Money`, `Currency`, `Price` with immutable currency, unit (`MAJOR`/`MINOR`), source, and UTC timestamp.
- Strict arithmetic: CurrencyMismatchError on incompatible operations.
- Explicit normalization: LSE penny quotes (GBX) normalized exactly once at broker boundary.

### 3.2 Authoritative Snapshot Engine (Phase 5)
- `hydrate_once()` pattern creating frozen `BrokerSnapshot`.
- Every downstream report, gate, and agent uses the exact same snapshot object.
- Invariant: `cash + invested_market_value == broker_NAV` down to the penny.

### 3.3 Complete Ledger-Driven P&L Accounting Engine (Phase 6)
- Independent Ledgers: `BROKER_PRACTICE_NAV` and `PRV_REALISTIC_NET_NAV`.
- Cost taxonomy:
  1. `EMBEDDED_IN_FILL`: Spreads and slippage embedded into executed buy/sell price.
  2. `BROKER_DEBITED`: SDRT (0.50%), Trading212 FX fee (0.15%), SEC/FINRA fees, PTM levy.
  3. `MODELLED_ONLY`: Shadow transaction tracking.
- `PNL_BRIDGE_VARIANCE = £0.00` calculated strictly from transaction table and cash flow ledger.

### 3.4 Market Session Engine (Phase 7)
- Authoritative state machine: `PRE_MARKET`, `REGULAR`, `AFTER_HOURS`, `OVERNIGHT`, `FULLY_CLOSED`, `HOLIDAY`.
- Timezone handling: London (`Europe/London`), New York (`America/New_York`), UTC.
- Enforce: `NEW ENTRY EXECUTION = REGULAR SESSION ONLY` across both practice and live.
- Signals generated outside regular session transition to `PENDING_REVALIDATION`.

### 3.5 Order State Machine & Atomic Cash Reservation (Phases 8 & 13)
- Explicit states: `SIGNAL_CREATED -> SIGNAL_APPROVED -> ORDER_READY -> ORDER_SUBMITTED -> FILLED -> CLOSED`.
- Idempotency key and client order ID for every order attempt.
- Atomic reservation lock for cash, sector budget, and ticker count before dispatching order.

### 3.6 Stop/Target Integrity & Dual Protection (Phase 10)
- Immutable entry terms: `initial_stop`, `initial_target`, `target_method`, `trailing_rules`.
- Resolve stop/target convention: Default entry Stop = -2.5% (with ATR floor/ceiling), Target = +7.5% (3.0:1 gross R:R, >= 2.0:1 net R:R).
- Practice API broker-native stop testing + secondary daemon watchdog heartbeat.

---

## 4. Execution Roadmap
1. **Core Types & Units**: Implement `Money`, `Currency` model.
2. **Snapshot Engine**: Standardize `BrokerSnapshot` with zero-cache-leakage guarantee.
3. **Accounting Engine**: Implement dual ledgers and zero-variance P&L bridge.
4. **Market Session State Machine**: Build timezone and holiday calendar engine.
5. **Order State Machine & Reservation**: Implement atomic lifecycle router.
6. **Stop/Target Engine**: Standardize immutable terms and watchdog heartbeat.
7. **Clean Stale & Fake Telemetry**: Purge all hardcoded mock/fake values from evidence modules.
8. **Test Philosophy Upgrade**: Property tests, contract tests, fault injection, accounting invariants.
9. **Quantitative Replay & Profitability Validation**: Full-universe walk-forward and stress testing.
10. **Practice Reset & Certification**: Canary execution, fresh £50k account verification, and certification report.
