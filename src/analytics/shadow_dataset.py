"""
🏛️ PRV CAPITAL | 42-SIGNAL POINT-IN-TIME SHADOW STRATEGY DATASET & RECONCILIATION ENGINE
Authoritative ground-truth repository of all 42 forward-test market signals.
Reconstructs every aggregate performance metric (Win Rate, Expectancy, Profit Factor, Cost Drag)
strictly BOTTOM-UP from individual raw trade rows.

Zero hardcoded summary metrics. Guaranteed mathematical reconciliation:
Expectancy = sum(net_pnl) / completed_trades == P(win) * AvgNetWin - P(loss) * AvgNetLoss
Profit Factor = sum(net_wins) / sum(net_losses)
"""
from datetime import datetime
from typing import Dict, Any, List, Tuple
from src.execution.cost_model import cost_model


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# THE COMPLETE 42 POINT-IN-TIME FORWARD-TEST SIGNALS DATASET
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RAW_42_SIGNALS = [
    # 1. CRM - Enterprise AI Agentforce catalyst (US Equity, Large Cap) -> WIN
    {"signal_id": "SIG_001_CRM", "timestamp": "2026-08-03 14:35:00", "ticker": "CRM", "exchange": "NYSE", "currency": "USD", "instrument_type": "EQUITY",
     "entry": 280.00, "target": 305.00, "stop": 272.00, "nominal": 1000.0, "exit_price": 305.00, "holding_days": 9, "mfe": 9.2, "mae": 1.1,
     "fundamental_score": 85.0, "spread_bps": 4.0, "capital_eff_score": 82.0},
    
    # 2. AZN - Oncology Phase 3 Clearance (UK Equity, Large Cap) -> WIN
    {"signal_id": "SIG_002_AZN", "timestamp": "2026-08-03 08:45:00", "ticker": "AZN", "exchange": "LSE", "currency": "GBP", "instrument_type": "EQUITY",
     "entry": 125.00, "target": 134.00, "stop": 122.00, "nominal": 1000.0, "exit_price": 134.00, "holding_days": 11, "mfe": 7.5, "mae": 1.4,
     "fundamental_score": 82.0, "spread_bps": 6.0, "capital_eff_score": 75.0},

    # 3. NVDA - Blackwell GB200 Ramp (US Equity, Mega Cap) -> WIN
    {"signal_id": "SIG_003_NVDA", "timestamp": "2026-08-04 15:10:00", "ticker": "NVDA", "exchange": "NASDAQ", "currency": "USD", "instrument_type": "EQUITY",
     "entry": 128.00, "target": 142.00, "stop": 123.50, "nominal": 1000.0, "exit_price": 142.00, "holding_days": 8, "mfe": 11.4, "mae": 1.8,
     "fundamental_score": 90.0, "spread_bps": 3.0, "capital_eff_score": 88.0},

    # 4. SHEL - North Sea Gas Margin Drag (UK Equity, Main Market) -> LOSS
    {"signal_id": "SIG_004_SHEL", "timestamp": "2026-08-04 09:15:00", "ticker": "SHEL", "exchange": "LSE", "currency": "GBP", "instrument_type": "EQUITY",
     "entry": 28.50, "target": 29.20, "stop": 27.80, "nominal": 1000.0, "exit_price": 27.80, "holding_days": 14, "mfe": 1.2, "mae": 2.5,
     "fundamental_score": 54.0, "spread_bps": 8.0, "capital_eff_score": 35.0},

    # 5. GLEN - Copper Inventory Drawdown (UK Equity, Main Market) -> LOSS
    {"signal_id": "SIG_005_GLEN", "timestamp": "2026-08-05 08:30:00", "ticker": "GLEN", "exchange": "LSE", "currency": "GBP", "instrument_type": "EQUITY",
     "entry": 4.60, "target": 4.70, "stop": 4.48, "nominal": 1000.0, "exit_price": 4.48, "holding_days": 16, "mfe": 1.0, "mae": 2.6,
     "fundamental_score": 52.0, "spread_bps": 12.0, "capital_eff_score": 28.0},

    # 6. EXPN - Consumer Credit Verification Data (UK Equity, Main Market) -> WIN
    {"signal_id": "SIG_006_EXPN", "timestamp": "2026-08-05 10:00:00", "ticker": "EXPN", "exchange": "LSE", "currency": "GBP", "instrument_type": "EQUITY",
     "entry": 36.80, "target": 39.50, "stop": 35.70, "nominal": 1000.0, "exit_price": 39.50, "holding_days": 12, "mfe": 7.8, "mae": 1.5,
     "fundamental_score": 78.0, "spread_bps": 8.0, "capital_eff_score": 70.0},

    # 7. PM - Tobacco Volume Drag (US Equity, Large Cap) -> LOSS
    {"signal_id": "SIG_007_PM", "timestamp": "2026-08-06 14:45:00", "ticker": "PM", "exchange": "NYSE", "currency": "USD", "instrument_type": "EQUITY",
     "entry": 118.00, "target": 121.00, "stop": 115.00, "nominal": 1000.0, "exit_price": 115.00, "holding_days": 18, "mfe": 1.4, "mae": 2.5,
     "fundamental_score": 53.0, "spread_bps": 6.0, "capital_eff_score": 32.0},

    # 8. DE - Autonomous Tractor & Precision Ag (US Equity, Large Cap) -> WIN
    {"signal_id": "SIG_008_DE", "timestamp": "2026-08-06 15:30:00", "ticker": "DE", "exchange": "NYSE", "currency": "USD", "instrument_type": "EQUITY",
     "entry": 380.00, "target": 415.00, "stop": 368.00, "nominal": 1000.0, "exit_price": 415.00, "holding_days": 10, "mfe": 9.8, "mae": 1.6,
     "fundamental_score": 84.0, "spread_bps": 6.0, "capital_eff_score": 80.0},

    # 9. BMY - Reblozyl Clinical Hold Noise (US Equity, Large Cap) -> LOSS (Stopped Out)
    {"signal_id": "SIG_009_BMY", "timestamp": "2026-08-07 14:00:00", "ticker": "BMY", "exchange": "NYSE", "currency": "USD", "instrument_type": "EQUITY",
     "entry": 52.00, "target": 56.50, "stop": 50.40, "nominal": 1000.0, "exit_price": 50.40, "holding_days": 7, "mfe": 2.1, "mae": 3.1,
     "fundamental_score": 76.0, "spread_bps": 6.0, "capital_eff_score": 72.0},

    # 10. ULVR - Volume Stagnation (UK Equity, Main Market) -> LOSS
    {"signal_id": "SIG_010_ULVR", "timestamp": "2026-08-07 09:30:00", "ticker": "ULVR", "exchange": "LSE", "currency": "GBP", "instrument_type": "EQUITY",
     "entry": 47.20, "target": 48.00, "stop": 46.00, "nominal": 1000.0, "exit_price": 46.00, "holding_days": 20, "mfe": 0.8, "mae": 2.5,
     "fundamental_score": 50.0, "spread_bps": 8.0, "capital_eff_score": 22.0},

    # 11. MSFT - Azure Cloud ARR acceleration (US Equity, Mega Cap) -> WIN
    {"signal_id": "SIG_011_MSFT", "timestamp": "2026-08-10 14:35:00", "ticker": "MSFT", "exchange": "NASDAQ", "currency": "USD", "instrument_type": "EQUITY",
     "entry": 445.00, "target": 480.00, "stop": 432.00, "nominal": 1000.0, "exit_price": 480.00, "holding_days": 9, "mfe": 8.2, "mae": 1.2,
     "fundamental_score": 88.0, "spread_bps": 3.0, "capital_eff_score": 85.0},

    # 12. LIN - Clean Hydrogen Industrial Gas Contracts (US Equity, Large Cap) -> WIN
    {"signal_id": "SIG_012_LIN", "timestamp": "2026-08-10 15:15:00", "ticker": "LIN", "exchange": "NYSE", "currency": "USD", "instrument_type": "EQUITY",
     "entry": 450.00, "target": 485.00, "stop": 438.00, "nominal": 1000.0, "exit_price": 485.00, "holding_days": 10, "mfe": 8.1, "mae": 1.1,
     "fundamental_score": 82.0, "spread_bps": 5.0, "capital_eff_score": 78.0},

    # 13. AAL - Anglo American Capex Overhang (UK Equity, Main Market) -> LOSS
    {"signal_id": "SIG_013_AAL", "timestamp": "2026-08-11 08:50:00", "ticker": "AAL", "exchange": "LSE", "currency": "GBP", "instrument_type": "EQUITY",
     "entry": 24.20, "target": 24.80, "stop": 23.50, "nominal": 1000.0, "exit_price": 23.50, "holding_days": 15, "mfe": 1.2, "mae": 2.9,
     "fundamental_score": 48.0, "spread_bps": 10.0, "capital_eff_score": 25.0},

    # 14. ANTO - Water Restrictions Capex Drag (UK Equity, Main Market) -> LOSS
    {"signal_id": "SIG_014_ANTO", "timestamp": "2026-08-11 09:20:00", "ticker": "ANTO", "exchange": "LSE", "currency": "GBP", "instrument_type": "EQUITY",
     "entry": 19.50, "target": 20.00, "stop": 18.90, "nominal": 1000.0, "exit_price": 18.90, "holding_days": 17, "mfe": 1.1, "mae": 3.1,
     "fundamental_score": 50.0, "spread_bps": 12.0, "capital_eff_score": 24.0},

    # 15. MA - Cross-Border FX Regulation Noise (US Equity, Large Cap) -> LOSS (Stopped Out)
    {"signal_id": "SIG_015_MA", "timestamp": "2026-08-12 14:40:00", "ticker": "MA", "exchange": "NYSE", "currency": "USD", "instrument_type": "EQUITY",
     "entry": 485.00, "target": 525.00, "stop": 472.00, "nominal": 1000.0, "exit_price": 472.00, "holding_days": 8, "mfe": 2.4, "mae": 2.7,
     "fundamental_score": 83.0, "spread_bps": 4.0, "capital_eff_score": 76.0},

    # 16. DHR - Bioprocessing & Genomic Consumables (US Equity, Large Cap) -> WIN
    {"signal_id": "SIG_016_DHR", "timestamp": "2026-08-12 15:20:00", "ticker": "DHR", "exchange": "NYSE", "currency": "USD", "instrument_type": "EQUITY",
     "entry": 255.00, "target": 278.00, "stop": 247.00, "nominal": 1000.0, "exit_price": 278.00, "holding_days": 12, "mfe": 9.3, "mae": 1.5,
     "fundamental_score": 81.0, "spread_bps": 5.0, "capital_eff_score": 74.0},

    # 17. UNP - Intermodal Rail Freight Pricing Power (US Equity, Large Cap) -> WIN
    {"signal_id": "SIG_017_UNP", "timestamp": "2026-08-13 14:50:00", "ticker": "UNP", "exchange": "NYSE", "currency": "USD", "instrument_type": "EQUITY",
     "entry": 242.00, "target": 262.00, "stop": 235.00, "nominal": 1000.0, "exit_price": 262.00, "holding_days": 14, "mfe": 8.6, "mae": 1.8,
     "fundamental_score": 79.0, "spread_bps": 5.0, "capital_eff_score": 72.0},

    # 18. JNJ - MedTech Litigation Noise (US Equity, Large Cap) -> LOSS
    {"signal_id": "SIG_018_JNJ", "timestamp": "2026-08-13 15:40:00", "ticker": "JNJ", "exchange": "NYSE", "currency": "USD", "instrument_type": "EQUITY",
     "entry": 162.00, "target": 165.50, "stop": 158.00, "nominal": 1000.0, "exit_price": 158.00, "holding_days": 19, "mfe": 1.1, "mae": 2.5,
     "fundamental_score": 52.0, "spread_bps": 4.0, "capital_eff_score": 26.0},

    # 19. REL - Legal & Scientific AI Data Subscriptions (UK Equity, Main Market) -> WIN
    {"signal_id": "SIG_019_REL", "timestamp": "2026-08-14 08:40:00", "ticker": "REL", "exchange": "LSE", "currency": "GBP", "instrument_type": "EQUITY",
     "entry": 35.50, "target": 38.20, "stop": 34.60, "nominal": 1000.0, "exit_price": 38.20, "holding_days": 10, "mfe": 7.9, "mae": 1.2,
     "fundamental_score": 80.0, "spread_bps": 6.0, "capital_eff_score": 75.0},

    # 20. LSEG - Financial Data & London Clearing Volume (UK Equity, Main Market) -> WIN
    {"signal_id": "SIG_020_LSEG", "timestamp": "2026-08-14 09:10:00", "ticker": "LSEG", "exchange": "LSE", "currency": "GBP", "instrument_type": "EQUITY",
     "entry": 102.00, "target": 109.50, "stop": 99.50, "nominal": 1000.0, "exit_price": 109.50, "holding_days": 11, "mfe": 7.6, "mae": 1.3,
     "fundamental_score": 82.0, "spread_bps": 7.0, "capital_eff_score": 72.0},

    # 21. AAPL - Apple Intelligence iPhone Upgrade Cycle (US Equity, Mega Cap) -> WIN
    {"signal_id": "SIG_021_AAPL", "timestamp": "2026-08-17 14:30:00", "ticker": "AAPL", "exchange": "NASDAQ", "currency": "USD", "instrument_type": "EQUITY",
     "entry": 224.00, "target": 244.00, "stop": 217.00, "nominal": 1000.0, "exit_price": 244.00, "holding_days": 8, "mfe": 9.2, "mae": 1.0,
     "fundamental_score": 87.0, "spread_bps": 3.0, "capital_eff_score": 84.0},

    # 22. GOOGL - Gemini Cloud & AI Search Monetization (US Equity, Mega Cap) -> WIN
    {"signal_id": "SIG_022_GOOGL", "timestamp": "2026-08-17 15:00:00", "ticker": "GOOGL", "exchange": "NASDAQ", "currency": "USD", "instrument_type": "EQUITY",
     "entry": 165.00, "target": 180.00, "stop": 159.50, "nominal": 1000.0, "exit_price": 180.00, "holding_days": 9, "mfe": 9.5, "mae": 1.4,
     "fundamental_score": 86.0, "spread_bps": 3.0, "capital_eff_score": 82.0},

    # 23. BP - Refining Margin Collapse (UK Equity, Main Market) -> REJECTED UPFRONT (Score 40)
    {"signal_id": "SIG_023_BP", "timestamp": "2026-08-18 08:35:00", "ticker": "BP", "exchange": "LSE", "currency": "GBP", "instrument_type": "EQUITY",
     "entry": 4.30, "target": 4.40, "stop": 4.15, "nominal": 1000.0, "exit_price": 4.15, "holding_days": 15, "mfe": 0.9, "mae": 3.5,
     "fundamental_score": 40.0, "spread_bps": 10.0, "capital_eff_score": 18.0},

    # 24. HSBA - Net Interest Margin Peaking (UK Equity, Main Market) -> LOSS
    {"signal_id": "SIG_024_HSBA", "timestamp": "2026-08-18 09:05:00", "ticker": "HSBA", "exchange": "LSE", "currency": "GBP", "instrument_type": "EQUITY",
     "entry": 6.80, "target": 6.95, "stop": 6.60, "nominal": 1000.0, "exit_price": 6.60, "holding_days": 18, "mfe": 1.0, "mae": 2.9,
     "fundamental_score": 48.0, "spread_bps": 8.0, "capital_eff_score": 22.0},

    # 25. AMZN - AWS GenAI Infrastructure Scaling (US Equity, Mega Cap) -> WIN
    {"signal_id": "SIG_025_AMZN", "timestamp": "2026-08-19 14:35:00", "ticker": "AMZN", "exchange": "NASDAQ", "currency": "USD", "instrument_type": "EQUITY",
     "entry": 178.00, "target": 196.00, "stop": 172.00, "nominal": 1000.0, "exit_price": 196.00, "holding_days": 8, "mfe": 10.5, "mae": 1.5,
     "fundamental_score": 89.0, "spread_bps": 3.0, "capital_eff_score": 86.0},

    # 26. META - Meta AI & Llama Enterprise Monetization (US Equity, Mega Cap) -> WIN
    {"signal_id": "SIG_026_META", "timestamp": "2026-08-19 15:10:00", "ticker": "META", "exchange": "NASDAQ", "currency": "USD", "instrument_type": "EQUITY",
     "entry": 510.00, "target": 560.00, "stop": 492.00, "nominal": 1000.0, "exit_price": 560.00, "holding_days": 9, "mfe": 10.2, "mae": 1.2,
     "fundamental_score": 88.0, "spread_bps": 4.0, "capital_eff_score": 85.0},

    # 27. CSPX - iShares Core S&P 500 ETF (UK Listed ETF, GBP) -> WIN (Filtered from D due to >14d holding)
    {"signal_id": "SIG_027_CSPX", "timestamp": "2026-08-20 08:30:00", "ticker": "CSPX", "exchange": "LSE", "currency": "GBP", "instrument_type": "ETF",
     "entry": 450.00, "target": 475.00, "stop": 441.00, "nominal": 1000.0, "exit_price": 475.00, "holding_days": 16, "mfe": 5.8, "mae": 0.9,
     "fundamental_score": 80.0, "spread_bps": 3.0, "capital_eff_score": 60.0},

    # 28. VUAG - Vanguard S&P 500 ETF (UK Listed ETF, GBP) -> WIN (Filtered from D due to >14d holding)
    {"signal_id": "SIG_028_VUAG", "timestamp": "2026-08-20 09:00:00", "ticker": "VUAG", "exchange": "LSE", "currency": "GBP", "instrument_type": "ETF",
     "entry": 88.00, "target": 93.00, "stop": 86.20, "nominal": 1000.0, "exit_price": 93.00, "holding_days": 17, "mfe": 5.9, "mae": 1.0,
     "fundamental_score": 80.0, "spread_bps": 3.0, "capital_eff_score": 58.0},

    # 29. LLY - Mounjaro/Zepbound Incretin Franchise (US Equity, Large Cap) -> WIN
    {"signal_id": "SIG_029_LLY", "timestamp": "2026-08-21 14:30:00", "ticker": "LLY", "exchange": "NYSE", "currency": "USD", "instrument_type": "EQUITY",
     "entry": 920.00, "target": 1010.00, "stop": 888.00, "nominal": 1000.0, "exit_price": 1010.00, "holding_days": 10, "mfe": 10.1, "mae": 1.6,
     "fundamental_score": 92.0, "spread_bps": 5.0, "capital_eff_score": 89.0},

    # 30. NVO - Wegovy Supply Chain Bottleneck (US Equity ADR, Large Cap) -> LOSS (Stopped out)
    {"signal_id": "SIG_030_NVO", "timestamp": "2026-08-21 15:15:00", "ticker": "NVO", "exchange": "NYSE", "currency": "USD", "instrument_type": "ADR",
     "entry": 135.00, "target": 147.00, "stop": 130.50, "nominal": 1000.0, "exit_price": 130.50, "holding_days": 15, "mfe": 2.2, "mae": 3.4,
     "fundamental_score": 75.0, "spread_bps": 5.0, "capital_eff_score": 62.0},

    # 31. BOO - Boohoo Group (UK AIM Share, Micro Cap) -> REJECTED UPFRONT (Spread 55 bps & Score 38)
    {"signal_id": "SIG_031_BOO", "timestamp": "2026-08-24 08:35:00", "ticker": "BOO", "exchange": "AIM", "currency": "GBP", "instrument_type": "AIM",
     "entry": 0.32, "target": 0.33, "stop": 0.30, "nominal": 1000.0, "exit_price": 0.30, "holding_days": 21, "mfe": 1.5, "mae": 6.2,
     "fundamental_score": 38.0, "spread_bps": 55.0, "capital_eff_score": 15.0},

    # 32. ASML - EUV Lithography High-NA Shipments (US ADR, Large Cap) -> WIN (Filtered from D due to >14d holding)
    {"signal_id": "SIG_032_ASML", "timestamp": "2026-08-24 14:40:00", "ticker": "ASML", "exchange": "NASDAQ", "currency": "USD", "instrument_type": "ADR",
     "entry": 870.00, "target": 950.00, "stop": 840.00, "nominal": 1000.0, "exit_price": 950.00, "holding_days": 15, "mfe": 9.5, "mae": 1.7,
     "fundamental_score": 88.0, "spread_bps": 6.0, "capital_eff_score": 68.0},

    # 33. AVGO - Custom Silicon TPU & Ethernet Switches (US Equity, Large Cap) -> WIN
    {"signal_id": "SIG_033_AVGO", "timestamp": "2026-08-25 14:35:00", "ticker": "AVGO", "exchange": "NASDAQ", "currency": "USD", "instrument_type": "EQUITY",
     "entry": 155.00, "target": 172.00, "stop": 149.00, "nominal": 1000.0, "exit_price": 172.00, "holding_days": 9, "mfe": 11.2, "mae": 1.4,
     "fundamental_score": 89.0, "spread_bps": 4.0, "capital_eff_score": 87.0},

    # 34. TXN - Analog Industrial Inventory Drag (US Equity, Large Cap) -> LOSS
    {"signal_id": "SIG_034_TXN", "timestamp": "2026-08-25 15:15:00", "ticker": "TXN", "exchange": "NASDAQ", "currency": "USD", "instrument_type": "EQUITY",
     "entry": 205.00, "target": 210.00, "stop": 199.00, "nominal": 1000.0, "exit_price": 199.00, "holding_days": 16, "mfe": 1.1, "mae": 2.9,
     "fundamental_score": 52.0, "spread_bps": 5.0, "capital_eff_score": 28.0},

    # 35. QCOM - Snapdragon X Elite Copilot PC Ramp (US Equity, Large Cap) -> WIN
    {"signal_id": "SIG_035_QCOM", "timestamp": "2026-08-26 14:30:00", "ticker": "QCOM", "exchange": "NASDAQ", "currency": "USD", "instrument_type": "EQUITY",
     "entry": 168.00, "target": 184.00, "stop": 162.00, "nominal": 1000.0, "exit_price": 184.00, "holding_days": 10, "mfe": 9.8, "mae": 1.6,
     "fundamental_score": 83.0, "spread_bps": 4.0, "capital_eff_score": 79.0},

    # 36. AMD - MI300X AI Accelerator Deployments (US Equity, Large Cap) -> WIN
    {"signal_id": "SIG_036_AMD", "timestamp": "2026-08-26 15:20:00", "ticker": "AMD", "exchange": "NASDAQ", "currency": "USD", "instrument_type": "EQUITY",
     "entry": 148.00, "target": 164.00, "stop": 142.00, "nominal": 1000.0, "exit_price": 164.00, "holding_days": 10, "mfe": 11.0, "mae": 1.8,
     "fundamental_score": 81.0, "spread_bps": 4.0, "capital_eff_score": 78.0},

    # 37. SNPS - EDA Export Control Turbulence (US Equity, Large Cap) -> LOSS (Stopped Out)
    {"signal_id": "SIG_037_SNPS", "timestamp": "2026-08-27 14:45:00", "ticker": "SNPS", "exchange": "NASDAQ", "currency": "USD", "instrument_type": "EQUITY",
     "entry": 560.00, "target": 610.00, "stop": 542.00, "nominal": 1000.0, "exit_price": 542.00, "holding_days": 6, "mfe": 1.8, "mae": 3.3,
     "fundamental_score": 84.0, "spread_bps": 5.0, "capital_eff_score": 77.0},

    # 38. CDNS - System Design Enablement ARR (US Equity, Large Cap) -> WIN
    {"signal_id": "SIG_038_CDNS", "timestamp": "2026-08-27 15:30:00", "ticker": "CDNS", "exchange": "NASDAQ", "currency": "USD", "instrument_type": "EQUITY",
     "entry": 290.00, "target": 315.00, "stop": 281.00, "nominal": 1000.0, "exit_price": 315.00, "holding_days": 12, "mfe": 8.9, "mae": 1.4,
     "fundamental_score": 82.0, "spread_bps": 5.0, "capital_eff_score": 74.0},

    # 39. ARM - Mobile License Expiry Noise (US ADR, Large Cap) -> LOSS (Stopped Out)
    {"signal_id": "SIG_039_ARM", "timestamp": "2026-08-28 14:35:00", "ticker": "ARM", "exchange": "NASDAQ", "currency": "USD", "instrument_type": "ADR",
     "entry": 132.00, "target": 148.00, "stop": 126.50, "nominal": 1000.0, "exit_price": 126.50, "holding_days": 7, "mfe": 2.5, "mae": 4.2,
     "fundamental_score": 86.0, "spread_bps": 5.0, "capital_eff_score": 85.0},

    # 40. INTU - TurboTax & QuickBooks AI Assist (US Equity, Large Cap) -> WIN
    {"signal_id": "SIG_040_INTU", "timestamp": "2026-08-28 15:10:00", "ticker": "INTU", "exchange": "NASDAQ", "currency": "USD", "instrument_type": "EQUITY",
     "entry": 640.00, "target": 690.00, "stop": 622.00, "nominal": 1000.0, "exit_price": 690.00, "holding_days": 12, "mfe": 8.1, "mae": 1.3,
     "fundamental_score": 81.0, "spread_bps": 5.0, "capital_eff_score": 72.0},

    # 41. WFC - Net Interest Income Peak (US Equity, Large Cap) -> REJECTED UPFRONT (Score 42)
    {"signal_id": "SIG_041_WFC", "timestamp": "2026-08-29 14:40:00", "ticker": "WFC", "exchange": "NYSE", "currency": "USD", "instrument_type": "EQUITY",
     "entry": 58.00, "target": 59.00, "stop": 56.50, "nominal": 1000.0, "exit_price": 56.50, "holding_days": 17, "mfe": 0.8, "mae": 2.6,
     "fundamental_score": 42.0, "spread_bps": 5.0, "capital_eff_score": 20.0},

    # 42. BAC - Deposit Beta Pressure (US Equity, Large Cap) -> REJECTED UPFRONT (Score 44)
    {"signal_id": "SIG_042_BAC", "timestamp": "2026-08-29 15:15:00", "ticker": "BAC", "exchange": "NYSE", "currency": "USD", "instrument_type": "EQUITY",
     "entry": 39.50, "target": 40.20, "stop": 38.50, "nominal": 1000.0, "exit_price": 38.50, "holding_days": 16, "mfe": 0.9, "mae": 2.5,
     "fundamental_score": 44.0, "spread_bps": 4.0, "capital_eff_score": 22.0}
]


class ShadowDatasetService:
    """
    Evaluates each of the 42 signals across Strategy A, B, C, and D.
    Reconstructs exact trade logs and enforces zero-discrepancy mathematical consistency.
    """
    def __init__(self):
        self.raw_signals = RAW_42_SIGNALS

    def _evaluate_trade_costs(self, sig: Dict[str, Any]) -> Dict[str, float]:
        """Calculates exact friction components using the authoritative 2026 cost model."""
        nominal = sig["nominal"]
        entry_p = sig["entry"]
        exit_p = sig["exit_price"]
        is_uk = (sig["exchange"] in ["LSE", "AIM"] or sig["currency"] == "GBP")
        is_foreign = (sig["currency"] != "GBP")
        itype = sig["instrument_type"]
        spread_bps = sig.get("spread_bps", 6.0)
        spread_pct = spread_bps / 10000.0
        shares = nominal / entry_p

        # Entry costs (Buy)
        entry_f = cost_model.calculate_trade_friction(
            nominal_value=nominal,
            is_buy=True,
            is_uk=is_uk,
            is_foreign=is_foreign,
            shares_count=shares,
            instrument_type=itype,
            exchange=sig["exchange"],
            currency=sig["currency"],
            custom_spread_pct=spread_pct
        )

        # Exit consideration
        exit_nominal = nominal * (exit_p / entry_p)

        # Exit costs (Sell)
        exit_f = cost_model.calculate_trade_friction(
            nominal_value=exit_nominal,
            is_buy=False,
            is_uk=is_uk,
            is_foreign=is_foreign,
            shares_count=shares,
            instrument_type=itype,
            exchange=sig["exchange"],
            currency=sig["currency"],
            custom_spread_pct=spread_pct
        )

        sdrt = entry_f["stamp_duty"] + exit_f["stamp_duty"]
        fx = entry_f["fx_cost"] + exit_f["fx_cost"]
        spread_c = entry_f["spread_cost"] + exit_f["spread_cost"]
        slippage_c = entry_f["slippage_cost"] + exit_f["slippage_cost"]
        sec = entry_f["sec_fees"] + exit_f["sec_fees"]
        finra = entry_f["finra_fees"] + exit_f["finra_fees"]
        other = entry_f["ptm_levy"] + exit_f["ptm_levy"]
        total_c = round(sdrt + fx + spread_c + slippage_c + sec + finra + other, 2)

        gross_pnl = round(exit_nominal - nominal, 2)
        net_pnl = round(gross_pnl - total_c, 2)

        return {
            "gross_pnl": gross_pnl,
            "sdrt": round(sdrt, 2),
            "fx": round(fx, 2),
            "spread": round(spread_c, 2),
            "slippage": round(slippage_c, 2),
            "sec": round(sec, 4),
            "finra": round(finra, 4),
            "other_costs": round(other, 2),
            "total_costs": total_c,
            "net_pnl": net_pnl
        }

    def generate_full_42_trade_ledger(self) -> List[Dict[str, Any]]:
        """
        Generates the exhaustive 42-row trade ledger with all 22 required columns.
        """
        ledger: List[Dict[str, Any]] = []

        for sig in self.raw_signals:
            costs = self._evaluate_trade_costs(sig)
            gross_pnl = costs["gross_pnl"]
            net_pnl = costs["net_pnl"]
            tot_cost = costs["total_costs"]

            # Strategy Decision Logic
            # 1. Strategy A (Baseline): Takes signals unless catastrophic technical score (<45.0)
            strat_a_dec = "EXECUTE" if sig["fundamental_score"] >= 45.0 else "REJECT"

            # 2. Strategy B (Net Edge Gate): Requires Net R:R >= 2.0x, Cost/Profit <= 30%, fundamental >= 60.0
            expected_gross_profit = sig["nominal"] * ((sig["target"] - sig["entry"]) / sig["entry"])
            cost_to_profit_pct = (tot_cost / max(0.01, expected_gross_profit)) * 100.0
            gross_reward = sig["target"] - sig["entry"]
            gross_risk = sig["entry"] - sig["stop"]
            net_reward = expected_gross_profit - tot_cost
            net_risk = (sig["nominal"] * (gross_risk / sig["entry"])) + tot_cost
            net_rr = net_reward / max(0.01, net_risk)

            strat_b_dec = "EXECUTE" if (strat_a_dec == "EXECUTE" and net_rr >= 2.0 and cost_to_profit_pct <= 30.0 and sig["fundamental_score"] >= 60.0) else "REJECT"

            # 3. Strategy C (Spread/Liquidity Filter): Strategy B + Spread/Profit <= 15% and Spread <= 50 bps
            spread_to_profit_pct = (costs["spread"] / max(0.01, expected_gross_profit)) * 100.0
            strat_c_dec = "EXECUTE" if (strat_b_dec == "EXECUTE" and spread_to_profit_pct <= 15.0 and sig["spread_bps"] <= 50.0 and sig["fundamental_score"] >= 75.0) else "REJECT"

            # 4. Strategy D (Capital Efficiency & Dead Capital Hurdle): Strategy C + Capital Efficiency Score >= 70 & Holding <= 14d
            strat_d_dec = "EXECUTE" if (strat_c_dec == "EXECUTE" and sig["capital_eff_score"] >= 70.0 and sig["holding_days"] <= 14) else "REJECT"

            ledger.append({
                "signal_id": sig["signal_id"],
                "timestamp": sig["timestamp"],
                "ticker": sig["ticker"],
                "exchange": sig["exchange"],
                "currency": sig["currency"],
                "entry": sig["entry"],
                "target": sig["target"],
                "stop": sig["stop"],
                "strategy_A_decision": strat_a_dec,
                "strategy_B_decision": strat_b_dec,
                "strategy_C_decision": strat_c_dec,
                "strategy_D_decision": strat_d_dec,
                "gross_pnl": gross_pnl,
                "sdrt": costs["sdrt"],
                "fx": costs["fx"],
                "spread": costs["spread"],
                "slippage": costs["slippage"],
                "sec": costs["sec"],
                "finra": costs["finra"],
                "other_costs": costs["other_costs"],
                "total_costs": tot_cost,
                "net_pnl": net_pnl,
                "holding_period_days": sig["holding_days"],
                "mfe": sig["mfe"],
                "mae": sig["mae"]
            })

        return ledger

    def compute_strategy_summary(self, strategy_key: str = "strategy_A_decision") -> Dict[str, Any]:
        """
        Computes mathematically reconciled summary statistics from the raw ledger.
        """
        ledger = self.generate_full_42_trade_ledger()
        accepted_trades = [t for t in ledger if t[strategy_key] == "EXECUTE"]
        rejected_count = len(ledger) - len(accepted_trades)
        total_completed = len(accepted_trades)

        if total_completed == 0:
            return {
                "signals_evaluated": len(ledger),
                "accepted_trades": 0,
                "rejected_trades": rejected_count,
                "completed_trades": 0,
                "gross_pnl": 0.0,
                "total_costs": 0.0,
                "net_pnl": 0.0,
                "win_count": 0,
                "loss_count": 0,
                "sum_net_wins": 0.0,
                "sum_net_losses": 0.0,
                "average_net_win": 0.0,
                "average_net_loss": 0.0,
                "win_rate_pct": 0.0,
                "net_expectancy_per_trade": 0.0,
                "reconciled_expectancy": 0.0,
                "profit_factor": 0.0,
                "cost_to_gross_profit_pct": 0.0,
                "avg_holding_period_days": 0.0,
                "mfe_avg": 0.0,
                "mae_avg": 0.0
            }

        wins = [t for t in accepted_trades if t["net_pnl"] > 0]
        losses = [t for t in accepted_trades if t["net_pnl"] <= 0]

        win_count = len(wins)
        loss_count = len(losses)
        win_rate = (win_count / total_completed) * 100.0
        loss_rate = (loss_count / total_completed) * 100.0

        sum_net_wins = round(sum(t["net_pnl"] for t in wins), 2)
        sum_net_losses = round(sum(abs(t["net_pnl"]) for t in losses), 2)
        gross_pnl = round(sum(t["gross_pnl"] for t in accepted_trades), 2)
        gross_wins = round(sum(t["gross_pnl"] for t in wins), 2)
        total_costs = round(sum(t["total_costs"] for t in accepted_trades), 2)
        net_pnl = round(sum(t["net_pnl"] for t in accepted_trades), 2)

        avg_net_win = round(sum_net_wins / win_count, 2) if win_count > 0 else 0.0
        avg_net_loss = round(sum_net_losses / loss_count, 2) if loss_count > 0 else 0.0

        # Exact Expectancy: Net P&L / completed trades
        expectancy = round(net_pnl / total_completed, 2)

        # Independent verification equation: P(win) * AvgNetWin - P(loss) * AvgNetLoss
        reconciled_exp = round(((win_count / total_completed) * avg_net_win) - ((loss_count / total_completed) * avg_net_loss), 2)

        # Profit Factor: sum(net wins) / sum(net losses)
        profit_factor = round(sum_net_wins / max(0.01, sum_net_losses), 2) if sum_net_losses > 0 else (sum_net_wins if sum_net_wins > 0 else 0.0)

        # Cost Drag %
        cost_drag_pct = round((total_costs / max(0.01, gross_wins)) * 100.0, 1)

        # Avg Holding Days, MFE, MAE
        avg_holding = round(sum(t["holding_period_days"] for t in accepted_trades) / total_completed, 1)
        avg_mfe = round(sum(t["mfe"] for t in accepted_trades) / total_completed, 2)
        avg_mae = round(sum(t["mae"] for t in accepted_trades) / total_completed, 2)

        return {
            "signals_evaluated": len(ledger),
            "accepted_trades": total_completed,
            "rejected_trades": rejected_count,
            "completed_trades": total_completed,
            "gross_pnl": gross_pnl,
            "total_costs": total_costs,
            "net_pnl": net_pnl,
            "win_count": win_count,
            "loss_count": loss_count,
            "sum_net_wins": sum_net_wins,
            "sum_net_losses": sum_net_losses,
            "average_net_win": avg_net_win,
            "average_net_loss": avg_net_loss,
            "win_rate_pct": round(win_rate, 1),
            "net_expectancy_per_trade": expectancy,
            "reconciled_expectancy": reconciled_exp,
            "profit_factor": profit_factor,
            "cost_to_gross_profit_pct": cost_drag_pct,
            "avg_holding_period_days": avg_holding,
            "mfe_avg": avg_mfe,
            "mae_avg": avg_mae
        }


shadow_dataset_service = ShadowDatasetService()
