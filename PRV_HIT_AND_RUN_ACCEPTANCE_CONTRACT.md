# PRV Capital Hit-and-Run Product Acceptance Contract

**Status:** FROZEN USER-AUTHORISED CONTRACT  
**Purpose:** Govern every future PRV Capital build, review, test, and deployment decision.  
**Rule:** No strategy, risk, execution, universe, allocation, or deployment behaviour may be added, removed, substituted, or reinterpreted without explicit user authorisation.

## 1. User Objective
PRV Capital is a pure hit-and-run trading system:
- Continuously analyse the Trading212-tradable universe while relevant markets are open.
- Find short-duration opportunities with positive expected net edge after costs.
- Deploy meaningful capital when justified.
- Enter, actively manage, exit, realise profit/loss, release capital, and rotate.
- Target **£100 realised net profit per day** as the base daily objective.
- Once £100 realised net profit is banked, continue hunting and bank additional realised net profit.
- Unrealised gains never count toward the £100 target.
- Never force a trade solely to reach the £100 target.

No guarantee of £100/day is claimed. The product objective is to maximise the chance of achieving it through valid trades.

## 2. Authorised Strategy Rules
Only these strategic constraints are authorised:
- Pure hit-and-run; no long-hold objective.
- No fixed multi-day rebalance cycle.
- Full Trading212-discoverable universe.
- No arbitrary geography, sector, market-cap, asset-class, or company-count restriction.
- AI may choose one position, several positions, or more.
- Prefer fewer/larger meaningful positions over many tiny purchases when evidence supports concentration.
- Total intended deployment must be **<= 80% of currently available trading capital**.
- Maximum planned loss on any individual holding = **5%**.
- Only realised net profit after all costs counts as banked.
- Base daily realised net target = **£100**.
- Continue trading after £100 if valid opportunities remain.
- No arbitrary fixed take-profit percentage, holding time, re-entry delay, or strategy threshold unless explicitly authorised later.
- Missing critical data remains UNKNOWN. It must never be replaced with a guessed default that can authorise a trade.

## 3. User Authorisation Rule
Explicit user authorisation is required before any proposed change to:
strategy logic, entry rules, exit rules, profit-taking logic, trailing logic, re-entry logic, number of holdings, allocation formula, capital ceiling, loss limit, daily target, universe restrictions, broker fallback behaviour, or deployment behaviour.

Technical bug fixes that do not change trading behaviour may proceed only if their behavioural impact is demonstrated to be neutral.

## 4. Product vs Strategy Failure
**PRODUCTION_FAILURE** = the product cannot correctly perform its job, including universe, market-data, metadata, allocation, lifecycle, or execution-path defects.

**STRATEGY_OUTCOME** = the product worked correctly and took trades as designed, but realised P&L was poor or negative.

**NO_VALID_EDGE** may be used only when the relevant open universe was successfully evaluated, execution capability resolved, required live data available, costs complete, candidates analysed, and no executable positive net opportunity remained.

Incomplete coverage must never be labelled NO_VALID_EDGE.

## 5. Universe and Market Coverage
Every proof must report:
- discovered count
- broker-tradable count
- open-session count
- market-data requested count
- market-data success count
- market-data failure count
- technically executable count
- opportunity-state count
- exact failure breakdown

A curated subset must be labelled **SUBSET TEST**, never full-universe proof.

## 6. Broker Execution Capability
Broker discovery, technical execution capability, and strategy authorisation are separate.

An order may be considered only when:
`TECHNICAL_EXECUTION_SUPPORTED == true`
AND
`STRATEGY_ORDER_AUTHORISED == true`

Unknown quantity precision, minimum quantity, tick size, spread, fee/tax, stop support, or session state must not be guessed.

## 7. Market Data
Every immediate-entry candidate must have:
session open, executable quote available now, authoritative bid/ask, quote market timestamp, quote fetch timestamp, data freshness state, known spread, and computable execution costs.

A recently fetched closed-market quote is not executable.
Unknown spread remains `None/UNKNOWN`, never `0`.

## 8. Opportunity Analysis
The system may analyse momentum continuation, acceleration, breakout, pullback continuation, mean reversion, relative-strength divergence, catalyst-driven movement, and multi-factor setups.

No setup family may become a mandatory gate unless explicitly authorised.

Each candidate decision must expose thesis, supporting evidence, contrary evidence, expected gross move, estimated costs, expected net opportunity, downside estimate, data quality, session state, and execution capability.

## 9. Capital Allocation
AI decides whether to trade, which instruments, number of concurrent positions, capital per position, and total deployment.

Hard constraint:
`total_intended_deployment <= 0.80 * available_trading_capital`

No fallback allocation policy is authorised.

If AI allocation is unavailable:
`ALLOCATION_DECISION_UNAVAILABLE`
=> zero new allocations, zero new orders, fail closed.

## 10. Entry
Every real entry decision must record instrument, venue, timestamp, live bid/ask, intended quantity, intended capital, expected costs, expected net opportunity, thesis, downside, quantity rule, tick rule, protective-stop requirement, and allocation rationale.

No generic fixed confidence threshold is authorised.

## 11. Loss Protection
For a long holding:
`planned_loss_pct <= 0.05`
and
`stop_price >= authoritative_fill_price * 0.95`

Protective rounding may only make the planned loss smaller, never larger.
If a valid protective stop cannot be established or verified, no protected entry is authorised.

## 12. Position Lifecycle
Allowed lifecycle actions:
HOLD, TAKE_PROFIT, EDGE_DECAY_EXIT, MOMENTUM_REVERSAL_EXIT, ROTATE, STOP_LOSS_EXIT.

No fixed take-profit %, holding minutes, trailing %, re-entry cooldown, or multi-day hold rule is authorised.

## 13. Banking
On every exit record:
gross realised P&L, all costs, net realised P&L, cumulative banked net profit today, and remaining amount to £100 base target.

Only realised net profit counts.
At £100 banked net profit: continue hunting valid opportunities and continue banking additional realised net profit.

## 14. Account State
Every real-data proof must explicitly identify:
broker environment (DEMO or LIVE), account currency, cash, equity, and available-to-trade capital.

Synthetic balances must be labelled **SYNTHETIC** and separated from real broker proof.

## 15. Evidence Levels
**BUILT**: code exists.  
**TESTED**: specified tests passed.  
**READ_ONLY_REAL_DATA_PROVEN**: unmocked production path processed real current data without broker writes.  
**DEMO_EXECUTION_PROVEN**: authorised demo broker orders exercised the exact order/fill/stop/cancel/exit path.  
**PRODUCTION_PROVEN**: exact intended production path exercised successfully in the target environment.

Never call a lower evidence level production-ready.

## 16. Testing Rules
Mocks may support unit tests but cannot prove broker behaviour, live market coverage, execution capability, session state, real costs, or real order lifecycle.

Synthetic examples must be labelled SYNTHETIC.

## 17. Deployment Rules
Until explicitly authorised:
- do not deploy the hit-and-run branch
- do not modify the running six-instrument engine
- do not merge into the protected live path
- do not reset broker/account/ledger state

Deployment requires explicit user approval after evidence review.

## 18. Reporting Contract
Every future implementation report must state:
BASE_SHA, NEW_SHA, files changed, tests/results, broker writes, evidence level achieved, exact coverage counts, unresolved failures, unauthorised strategy rules introduced (must be 0), synthetic data used yes/no, mocks used yes/no, environment, and production failures found.

Claims such as PASS, READY, 0 failures, or working are invalid unless the evidence section proves them.

## 19. Current Build Priority
1. Finish execution-capability and market-data product correctness.
2. Prove broad open-market coverage.
3. Validate broker quantity/stop/tick behaviour in DEMO only with explicit authorisation.
4. Build and prove the real hit-and-run lifecycle.
5. Only then consider deployment.

## 20. Governing Principle
**USER AUTHORISATION BEFORE BEHAVIOUR CHANGE.**

No assistant, model, developer, or implementation agent may silently replace the user's trading objective with its own idea.
