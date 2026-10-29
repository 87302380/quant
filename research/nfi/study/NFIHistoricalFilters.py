"""Documented filter control, not a replacement for historical volume-universe data."""
import json
from pathlib import Path
import sys

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'upstream'))
from NostalgiaForInfinityX8 import NostalgiaForInfinityX8


def historical_eligibility(dates, daily, listed):
    history = daily[['date', 'high', 'low']].copy().sort_values('date')
    history['range'] = history.high.rolling(3, min_periods=3).max() / history.low.rolling(3, min_periods=3).min() - 1
    # A day's high/low becomes available at its close, never at its opening timestamp.
    history['available'] = (history.date + pd.Timedelta(days=1)).astype('datetime64[ns, UTC]')
    aligned = pd.merge_asof(pd.DataFrame({'date': dates.astype('datetime64[ns, UTC]')}).sort_values('date'),
                           history[['available', 'range']], left_on='date', right_on='available')
    return aligned['range'].between(.03, .95).to_numpy() & (pd.DatetimeIndex(dates) >= listed + pd.Timedelta(days=60))


class NFIHistoricalFilters(NostalgiaForInfinityX8):
    """Original signals/exits with causal 60-day age and closed 3-day range entry gates."""
    def populate_entry_trend(self, dataframe, metadata):
        dataframe = super().populate_entry_trend(dataframe, metadata)
        universe = json.loads((Path(__file__).resolve().parents[1] / 'universe.json').read_text())
        item = next(p for p in universe['pairs'] if p['pair'] == metadata['pair'])
        daily = self.dp.get_pair_dataframe(metadata['pair'], '1d')
        listed = pd.Timestamp(int(item['list_time']), unit='ms', tz='UTC')
        eligible = historical_eligibility(dataframe.date, daily, listed)
        dataframe.loc[~eligible, ['enter_long', 'enter_short']] = 0
        return dataframe
