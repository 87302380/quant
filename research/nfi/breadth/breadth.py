"""Causal equal-weight market breadth on exact synchronous closed five-minute bars."""
import numpy as np
import pandas as pd

def market_features(frames):
    series={}
    for pair,frame in sorted(frames.items()):
        if frame.empty:continue
        idx=pd.DatetimeIndex(pd.to_datetime(frame.date,utc=True).astype('datetime64[ns, UTC]'))
        if idx.has_duplicates:raise ValueError('Duplicate market bar')
        series[pair]=pd.Series(frame.close.to_numpy(dtype=float),index=idx)
    if not series:raise ValueError('No market observations')
    close=pd.concat(series,axis=1,sort=True).sort_index();logs=np.log(close.where(close>0))
    step=pd.Series(close.index,index=close.index).diff().eq(pd.Timedelta(minutes=5))
    ret=logs.diff().where(step,axis=0)
    # Prior-day volatility ends before the current fifteen-minute measurement.
    sigma=ret.rolling(288,min_periods=288).std().shift(3)*np.sqrt(3)
    r15=logs-logs.shift(3)
    contiguous=ret.notna().rolling(3,min_periods=3).sum().eq(3)
    r15=r15.where(contiguous)
    valid=r15.notna()&sigma.gt(0)&np.isfinite(sigma)
    z=(r15/sigma).where(valid)
    mature=pd.DataFrame(False,index=close.index,columns=close.columns)
    for pair in close:
        first=close[pair].first_valid_index()
        if first is not None:mature[pair]=close.index>=first+pd.Timedelta(minutes=1455)
    count=valid.sum(axis=1);expected=mature.sum(axis=1)
    coverage=count/expected.replace(0,np.nan)
    known=(count>=20)&(coverage>=.8)
    fraction=((r15<0)&valid).sum(axis=1)/count.replace(0,np.nan)
    median=z.median(axis=1)
    raw=known&(fraction>=.8)&(median<=-1.5)
    recent=raw.rolling(12,min_periods=1).max().astype(bool)
    return pd.DataFrame({'date':close.index,'bre_valid_count':count.to_numpy(),'bre_mature_count':expected.to_numpy(),
        'bre_coverage':coverage.to_numpy(),'bre_down_fraction':fraction.to_numpy(),'bre_median_z':median.to_numpy(),
        'bre_known':known.to_numpy(),'bre_raw':raw.to_numpy(),'bre_recent':recent.to_numpy()})
