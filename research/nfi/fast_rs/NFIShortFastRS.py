"""Closed five-minute BTC-relative strength: fixed horizons, no sizing changes."""
from pathlib import Path
import sys
import numpy as np
import pandas as pd
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'atr_short'))
from NFIShortATR import NFIShortATRGated


def strength_features(coin,btc):
    """Exact timestamp matching; no forward fill across missing benchmark bars.

    Inputs are open timestamps. Row t becomes usable at its five-minute close.
    Beta is fit on 7 days of five-minute returns ending before the 1h score window.
    """
    dates=pd.to_datetime(coin.date,utc=True).astype('datetime64[ns, UTC]')
    other=pd.DataFrame({'date':pd.to_datetime(btc.date,utc=True).astype('datetime64[ns, UTC]'),'btc':btc.close.to_numpy()})
    left=pd.DataFrame({'date':dates.to_numpy(),'coin':coin.close.to_numpy()})
    merged=left.merge(other,on='date',how='left',validate='one_to_one',sort=False)
    own=np.log(merged.coin);bench=np.log(merged.btc)
    contiguous=merged.date.diff().eq(pd.Timedelta(minutes=5))&merged.btc.notna()&merged.btc.shift().notna()
    output=pd.DataFrame(index=coin.index)
    for minutes in [15,60,240]:
        bars=minutes//5
        valid=contiguous.rolling(bars,min_periods=bars).sum().eq(bars)
        output[f'own_{minutes}']=(own-own.shift(bars)).where(valid).to_numpy()
        output[f'rs_{minutes}']=((own-own.shift(bars))-(bench-bench.shift(bars))).where(valid).to_numpy()
    x=bench.diff().where(contiguous);y=own.diff().where(contiguous)
    beta=(y.rolling(2016,min_periods=2016).cov(x)/x.rolling(2016,min_periods=2016).var()).shift(12)
    output['beta_estimate']=beta.to_numpy()
    output['beta_60']=(output.own_60.to_numpy()-beta.to_numpy()*(bench-bench.shift(12)).to_numpy())
    output['beta_60']=output.beta_60.where(np.isfinite(beta.to_numpy()))
    return output


class NFIShortFastBase(NFIShortATRGated):
    horizon=60
    filter_long=True
    filter_short=True
    confirm=False
    beta_adjust=False
    absolute_momentum=False

    def populate_indicators(self,df,metadata):
        df=super().populate_indicators(df,metadata)
        # BTC is in the fixed base whitelist. Cache only raw observed bars;
        # all transforms remain causal vector operations, never final-row scalars.
        if '_fast_btc' not in self.__dict__:
            self._fast_btc=self.dp.get_pair_dataframe('BTC/USDT:USDT','5m')
        features=strength_features(df,self._fast_btc)
        for name in features:df['fast_'+name]=features[name].to_numpy()
        return df

    def populate_entry_trend(self,df,metadata):
        df=super().populate_entry_trend(df,metadata)
        # The benchmark cannot be ranked against itself. Preserve its native
        # signals for every candidate, including controls.
        if metadata['pair']=='BTC/USDT:USDT':return df
        value=df['fast_beta_60'] if self.beta_adjust else df[f'fast_rs_{self.horizon}']
        long=value>1e-12;short=value< -1e-12
        if self.confirm:
            long &= df.fast_rs_240>1e-12;short &= df.fast_rs_240< -1e-12
        if self.absolute_momentum:
            long &= df.fast_own_60>0;short &= df.fast_own_60<0
        if self.filter_long:df.loc[~long,'enter_long']=0
        if self.filter_short:df.loc[~short,'enter_short']=0
        return df


class NFIShortFastControl(NFIShortFastBase):
    filter_long=False
    filter_short=False

class NFIShortFast15(NFIShortFastBase):
    horizon=15

class NFIShortFast60(NFIShortFastBase):
    pass

class NFIShortFast240(NFIShortFastBase):
    horizon=240

class NFIShortFastShort60(NFIShortFastBase):
    filter_long=False

class NFIShortFastLong60(NFIShortFastBase):
    filter_short=False

class NFIShortFastConfirm(NFIShortFastBase):
    confirm=True

class NFIShortFastBeta(NFIShortFastBase):
    beta_adjust=True

class NFIShortFastMomentum(NFIShortFastBase):
    absolute_momentum=True
