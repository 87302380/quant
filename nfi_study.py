"""Reproduce the frozen X8 controls with the real Freqtrade engine (never trade)."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('variants', nargs='+', choices=[
        'baseline100', 'official', 'official_1x', 'official_no_adjust',
        'official_12slots', 'official_cost10', 'official_filters', 'official_24h', 'baseline100_24h',
        'risk_stop3', 'risk_stop6', 'risk_stale12', 'risk_trendgate', 'risk_profitprotect', 'official_1x_24h', 'risk_overheat80'])
    args = parser.parse_args()
    for name in args.variants:
        risk_strategies = {'risk_stop3': 'NFIRiskStop3', 'risk_stop6': 'NFIRiskStop6',
                           'risk_stale12': 'NFIRiskStale12', 'risk_trendgate': 'NFIRiskTrendGate',
                           'risk_profitprotect': 'NFIRiskProfitProtect', 'risk_overheat80': 'NFIRiskOverheat80'}
        config_name = {'official_cost10': 'official', 'official_filters': 'official',
                       'official_24h': 'official', 'baseline100_24h': 'baseline100',
                       'official_1x_24h': 'official_1x'}.get(name, name)
        if name in risk_strategies:
            config_name = 'official'
        config = ROOT / 'research/nfi/study' / f'{config_name}.json'
        strategy = 'NFI24Hour' if name.endswith('_24h') else ('NFIHistoricalFilters' if name == 'official_filters' else 'NostalgiaForInfinityX8')
        strategy = risk_strategies.get(name, strategy)
        strategy_path = 'research/nfi/risk_study' if name in risk_strategies else ('research/nfi/study' if strategy != 'NostalgiaForInfinityX8' else 'research/nfi/upstream')
        out = ROOT / 'results/nfi/study' / name
        out.mkdir(parents=True, exist_ok=True)
        runtime = ROOT / 'data/nfi/study-runtime'
        runtime.mkdir(parents=True, exist_ok=True)
        userdir = tempfile.mkdtemp(prefix=f'{name}-', dir=runtime)
        command = [str(ROOT / '.venv/bin/freqtrade'), 'backtesting',
                   '--userdir', userdir,
                   '--config', str(config), '--strategy-path', str(ROOT / strategy_path),
                   '--strategy', strategy, '--datadir', str(ROOT / 'data/nfi/freqtrade'),
                   '--data-format-ohlcv', 'jsongz', '--timerange', '20260701-20261028',
                   '--fee', '0.001' if name == 'official_cost10' else '0.0005',
                   '--cache', 'none', '--export', 'trades', '--breakdown', 'month',
                   '--backtest-directory', str(out)]
        record = {'started_at': datetime.now(timezone.utc).isoformat(), 'command': command,
                  'config_sha256': hashlib.sha256(config.read_bytes()).hexdigest(), 'status': 'running'}
        record_path = out / 'execution.json'
        record_path.write_text(json.dumps(record, indent=2))
        print(f'START {name}', flush=True)
        with (out / 'run.log').open('w') as log:
            proc = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        record.update(finished_at=datetime.now(timezone.utc).isoformat(),
                      returncode=proc.returncode, status='success' if proc.returncode == 0 else 'failed')
        record_path.write_text(json.dumps(record, indent=2))
        print(f'END {name}: {record["status"]}', flush=True)
        if proc.returncode:
            sys.exit(proc.returncode)


if __name__ == '__main__':
    main()
