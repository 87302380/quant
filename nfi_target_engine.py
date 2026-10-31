"""Fetch identical leverage metadata for the declared research universe only."""
from pathlib import Path
import logging
import runpy

from freqtrade.exchange import Exchange

original = Exchange.load_leverage_tiers


def scoped_leverage_tiers(self):
    markets = self._markets
    pairs = self._config['exchange']['pair_whitelist']
    if not pairs or any('*' in p or '[' in p for p in pairs):
        raise ValueError('Require explicit frozen pair whitelist')
    missing = set(pairs) - set(markets)
    if missing:
        raise ValueError('Missing actual market specifications: ' + str(sorted(missing)))
    try:
        self._markets = {p: markets[p] for p in pairs}
        result = original(self)
    finally:
        self._markets = markets
    if any(not result.get(p) for p in pairs):
        raise ValueError('Incomplete current leverage metadata for frozen universe')
    logging.getLogger(__name__).info('TARGET_METADATA_VERIFIED %s markets; full market registry preserved', len(pairs))
    return result


if __name__ == '__main__':
    from nfi_target_memory import install
    install()
    Exchange.load_leverage_tiers = scoped_leverage_tiers
    runpy.run_path(str(Path(__file__).with_name('nfi_short_engine.py')), run_name='__main__')
