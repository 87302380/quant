"""Closed-bar trend context and a causal breakout/retest candidate."""
import numpy as np
import pandas as pd
import talib

def aligned_trend(base,info,hours,name):
    c=info.close.to_numpy(dtype=float);ema20=talib.EMA(c,20);ema50=talib.EMA(c,50)
    slope=pd.Series(ema50).diff(6 if hours==1 else 3).to_numpy()
    up=(c>ema50)&(slope>0)
    if hours==1:up &= ema20>ema50
    a=pd.DataFrame({'available':pd.to_datetime(info.date,utc=True).astype('datetime64[ns, UTC]')+pd.Timedelta(hours=hours)-pd.Timedelta(minutes=5),name:up})
    left=pd.DataFrame({'date':pd.to_datetime(base.date,utc=True).astype('datetime64[ns, UTC]')})
    r=pd.merge_asof(left,a,left_on='date',right_on='available',tolerance=pd.Timedelta(hours=hours)-pd.Timedelta(minutes=5))
    return r[name].fillna(False).to_numpy(dtype=bool)

def retest_features(base,hour,four,btc):
    out=pd.DataFrame(index=base.index)
    out['op_h_up']=aligned_trend(base,hour,1,'h');out['op_4h_up']=aligned_trend(base,four,4,'f')
    dates=pd.to_datetime(base.date,utc=True).astype('datetime64[ns, UTC]')
    left=pd.DataFrame({'date':dates,'coin':base.close.to_numpy(dtype=float)})
    benchmark=pd.DataFrame({'date':pd.to_datetime(btc.date,utc=True).astype('datetime64[ns, UTC]'),'btc':btc.close.to_numpy(dtype=float)})
    joined=left.merge(benchmark,on='date',how='left',sort=False,validate='one_to_one')
    step=joined.date.diff().eq(pd.Timedelta(minutes=5))&joined.btc.notna()&joined.btc.shift().notna()
    valid=step.rolling(12,min_periods=12).sum().eq(12)
    rs=(np.log(joined.coin/joined.coin.shift(12))-np.log(joined.btc/joined.btc.shift(12))).where(valid)
    out['op_rs60']=rs.to_numpy()
    high=base.high.shift().rolling(12,min_periods=12).max()
    volume=base.volume.shift().rolling(20,min_periods=20).median()
    breakout=(base.close>high)&(base.close.shift()<=high.shift())&(base.volume>volume)
    level=high.where(breakout).ffill(limit=11).shift()
    stamp=dates.where(breakout).ffill(limit=11).shift()
    atr=talib.ATR(base.high.to_numpy(dtype=float),base.low.to_numpy(dtype=float),base.close.to_numpy(dtype=float),14)
    out['op_retest']=(out.op_h_up&out.op_4h_up&(out.op_rs60>0)&level.notna()&((dates-stamp)<=pd.Timedelta(hours=1))&
        (base.low<=level)&(base.close>=level)&(base.close<=level+.5*atr)&(base.close>base.open)&valid.to_numpy()).to_numpy()
    return out
