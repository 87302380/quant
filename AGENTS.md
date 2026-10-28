# Project instructions

This repository contains offline BTC and NFI X8 research, not a live trading service.

1. Read `RESEARCH_SCOPE.md` before changing the strategy. The original BTC studies remain BTC only. The user explicitly authorized a separate multi-coin OKX USDT perpetual NFI X8 study on 2026-10-28; read `research/nfi/README.md` and run `python nfi_verify.py` for it. No pre-2024 data. Earlier dates are warmup/comparison, not evidence of current effectiveness.
2. Restore the bundled datasets with `python cloud_data.py`. No exchange credentials or network are needed for existing-history tests and backtests.
3. Run `python cloud_verify.py --backtest` to restore data, execute tests, and replay the current bear study. Python 3.10+ and its standard library are sufficient.
4. Use closed higher-timeframe bars for regime and location decisions. Lower-timeframe data must not supply future information. Keep fees/slippage and report funding is disabled by user request.
5. All current 2024-2026 BTC history has been examined; do not label repeated historical optimization as independent out-of-sample proof or guaranteed returns.
6. Preserve existing experiments and disclose failed variants. All entry units of one campaign count as one net trade. No live exchange orders are authorized by this repository.
7. Generated raw CSVs, SQLite caches and large trade/equity outputs are ignored. Dataset gzip archives and SHA256 manifests are tracked. Preserve reproducibility without adding secrets or legacy robot configurations.
