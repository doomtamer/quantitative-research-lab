# BTCUSDT DATA DOWNLOAD REPORT

Generated (UTC): 2026-11-17T20:09:05.355380+00:00
Requested: 2021-01-01 to 2026-11-16
Market: 2021-01-01 to 2026-11-16
Features rows / cols: 2145 / 92

## Source row counts
- ohlcv_daily: 2146
- funding_daily: 2146
- metrics_daily: 2146
- etf_trading_days: 731
- macro_days: 0

## Macro columns with actual values
- No macro columns downloaded

## Most missing columns (%)
- etf_flow_msbt_usd_m: 92.82%
- etf_flow_btc_usd_m: 73.19%
- etf_flow_btco_usd_m: 66.76%
- etf_flow_ezbc_usd_m: 66.76%
- etf_flow_ibit_usd_m: 66.71%
- etf_flow_fbtc_usd_m: 66.71%
- etf_flow_bitb_usd_m: 66.71%
- etf_flow_arkb_usd_m: 66.71%
- etf_flow_brrr_usd_m: 66.71%
- etf_flow_hodl_usd_m: 66.71%
- etf_flow_btcw_usd_m: 66.71%
- etf_flow_gbtc_usd_m: 66.71%
- etf_flow_total_usd_m: 65.97%
- etf_total_flow_30d: 53.47%
- etf_total_flow_z_30d: 53.47%
- etf_total_flow_14d: 52.45%
- etf_total_flow_7d: 51.93%
- etf_total_flow_3d: 51.75%
- toptrader_long_short_ratio_z_30d: 19.02%
- toptrader_long_short_count: 14.97%
- toptrader_long_short_ratio: 14.97%
- toptrader_long_short_ratio_log: 14.97%
- dist_ma_200d: 9.28%
- taker_long_short_volume_ratio_z_30d: 8.9%
- taker_long_short_volume_ratio: 6.11%

## Warnings
- Funding archive 2026-11 unavailable (may not be published yet)

## Research cautions
- Market features day t assumed available only after UTC day t closes.
- Futures positioning metrics shifted by one full day: Binance changed metrics timestamp conventions in 2026.
- ETF Farside observed day t shifted by one full day, a conservative proxy for publication availability.
- ETF trailing 3/7/14/30d features count REPORTING sessions, not calendar days; last available value carried forward up to 4 days.
- FRED daily market data lagged one calendar day; M2/Fedfunds lagged 45 calendar days.
- Macro vintages/revisions not corrected: use ALFRED and release-time data for rigorous PIT research.
- Targets t+1 exist only for rows with a next-day candle; last daily candle is removed.
