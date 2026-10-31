"""Independent CP/short-target replays. Existing experiments remain immutable."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'results/nfi/target_review'
VARIANTS = {'cp': ('NFIShortStop_2_0_R2_0', 'ablation'),
            'r15': ('NFIShortStop_2_0_R1_5', 'ablation'),
            'r10': ('NFIShortStop_2_0_R1_0', 'ablation'),
            'canonical_r15': ('NFIShortTargetR15', 'ablation'),
            'canonical_r10': ('NFIShortTargetR10', 'ablation'),
            'canonical': ('NFIShortOPCompression', 'opportunities')}
VARIANTS.update({'abl_' + n.lower(): ('NFIAblation_' + n, 'ablation')
                 for n in ['base', 'S', 'C', 'P', 'SC', 'SP', 'CP', 'SCP']})


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(name, fee, suffix, start):
    folder = OUT / (name + suffix)
    folder.mkdir(parents=True, exist_ok=True)
    if list(folder.glob('*.zip')) or (folder / 'execution.json').exists():
        raise ValueError('Preserve existing attempt: ' + str(folder))
    runtime = ROOT / 'data/nfi_ytd2026/runtime'
    runtime.mkdir(parents=True, exist_ok=True)
    userdir = Path(tempfile.mkdtemp(prefix='target-' + name, dir=runtime))
    overlay = userdir / 'network.json'
    ca = os.environ.get('REQUESTS_CA_BUNDLE') or os.environ.get('SSL_CERT_FILE')
    proxy = os.environ.get('HTTPS_PROXY') or os.environ.get('https_proxy')
    exchange = {}
    if proxy:
        exchange['ccxt_config'] = {'httpsProxy': proxy}
        exchange['ccxt_async_config'] = {'httpsProxy': proxy}
    if ca:
        exchange.setdefault('ccxt_config', {})['validateServerSsl'] = ca
        exchange.setdefault('ccxt_async_config', {})['cafile'] = ca
    for key in ['ccxt_config', 'ccxt_async_config']:
        exchange.setdefault(key, {})['rateLimit'] = 500
    overlay.write_text(json.dumps({'exchange': exchange}, indent=2) + '\n')
    config = ROOT / 'research/nfi/ytd2026/config.backtest.json'
    universe = json.loads((config.parent / 'universe.json').read_text())
    from nfi_data import millis
    window = f"{millis(start or universe['evaluation_start'])//1000}-{millis(universe['end_exclusive'])//1000}"
    strategy, directory = VARIANTS[name]
    command = [str(ROOT / '.venv/bin/python'), str(ROOT / 'nfi_target_engine.py'),
               '--precision-fix', '--deadline-trace', str(folder / 'deadline_trace.jsonl'),
               'backtesting', '--userdir', str(userdir), '--config', str(config),
               '--config', str(overlay), '--strategy-path', str(ROOT / 'research/nfi' / directory),
               '--strategy', strategy, '--datadir', str(ROOT / 'data/nfi_ytd2026/freqtrade'),
               '--data-format-ohlcv', 'jsongz', '--timerange', window, '--fee', str(fee),
               '--cache', 'none', '--export', 'trades', '--breakdown', 'month',
               '--backtest-directory', str(folder)]
    sources = sorted((ROOT / 'research/nfi').rglob('*.py'))
    sources += [ROOT / p for p in ['nfi_target_review.py', 'nfi_target_engine.py', 'nfi_target_memory.py', 'nfi_short_engine.py', 'nfi_precision.py']]
    record = {'status': 'running', 'started_at': datetime.now(timezone.utc).isoformat(),
              'command': command, 'fee': fee, 'base_config_sha256': sha(config),
              'dataset_manifest_sha256': sha(ROOT / 'datasets/nfi_ytd2026/manifest.json'),
              'sources': {str(p.relative_to(ROOT)): sha(p) for p in sources},
              'network_overlay_sha256': sha(overlay), 'funding_excluded': True}
    path = folder / 'execution.json'
    path.write_text(json.dumps(record, indent=2) + '\n')
    print('START', name, suffix, flush=True)
    with (folder / 'run.log').open('w') as log:
        result = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
    record.update(status='success' if result.returncode == 0 else 'failed',
                  returncode=result.returncode, finished_at=datetime.now(timezone.utc).isoformat())
    path.write_text(json.dumps(record, indent=2) + '\n')
    print('END', name, suffix, record['status'], flush=True)
    return result.returncode


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('variants', nargs='+', choices=VARIANTS)
    parser.add_argument('--fee', type=float, default=.0005)
    parser.add_argument('--suffix', default='')
    parser.add_argument('--start')
    parser.add_argument('--workers', type=int, choices=[1, 2], default=1)
    args = parser.parse_args()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        codes = list(pool.map(lambda n: run(n, args.fee, args.suffix, args.start), args.variants))
    if any(codes):
        raise SystemExit(1)
