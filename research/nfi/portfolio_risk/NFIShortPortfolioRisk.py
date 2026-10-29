"""Portfolio risk hypotheses on the fixed ATR-short framework; no exposure boosts."""
from pathlib import Path
import sys,logging,json
from datetime import timedelta
import numpy as np
import pandas as pd
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'atr_short'))
from NFIShortATR import NFIShortATRGated,NFI24Hour
from NFIShortResearch import align_hourly,Trade,stoploss_from_absolute


def btc_risk_features(btc,hourly):
    close=btc.close.astype(float)
    ret=np.log(close).diff()
    consecutive=btc.date.diff().eq(pd.Timedelta(minutes=5))
    ret=ret.where(consecutive)
    vol=ret.rolling(12,min_periods=12).std()
    reference=vol.shift(12).rolling(2016,min_periods=2016).median()
    atr=align_hourly(btc,hourly).short_atr
    r15=np.log(close/close.shift(3)).where(consecutive.rolling(3,min_periods=3).sum().eq(3))
    shock=(r15.to_numpy()< -1.5*atr.to_numpy()/close.to_numpy())
    frame=pd.DataFrame({'date':pd.to_datetime(btc.date,utc=True).astype('datetime64[ns, UTC]'),
                        'pm_shock':pd.Series(shock).rolling(12,min_periods=1).max().to_numpy().astype(bool),
                        'pm_vol_ratio':(vol/reference).to_numpy(),
                        'pm_btc_hour_return':np.log(close/close.shift(12)).where(consecutive.rolling(12,min_periods=12).sum().eq(12)).to_numpy()})
    return frame


def loss_per_coin(rate,distance,short,fee):
    stop=rate+distance if short else max(rate-distance,rate*.001)
    return abs(stop-rate)+fee*(rate+stop)


def recent_long_stop_guard(trades,pair,now):
    stopped=[]
    for trade in trades:
        close=getattr(trade,'close_date_utc',None)
        if trade.is_short or close is None or not (now-timedelta(hours=1)<close<=now):continue
        reason=getattr(trade,'exit_reason','') or ''
        if reason in ['stop_loss','trailing_stop_loss','research_pm_long_stop_gap']:stopped.append(trade)
    return len(stopped)>=2 or any(t.pair==pair for t in stopped)


class NFIShortPMBase(NFIShortATRGated):
    long_stop=False
    long_budget=False
    portfolio_limit=None
    half_long=False
    shock_gate=False
    volatility_target=False
    correlation_cap=False
    side_cap=False
    stop_cooldown=False
    stop_reason='research_pm_long_stop_gap'

    def populate_indicators(self,df,metadata):
        df=super().populate_indicators(df,metadata)
        btc=self.dp.get_pair_dataframe('BTC/USDT:USDT','5m')
        stamp=btc.date.iloc[-1] if not btc.empty else None
        if self.__dict__.get('_pm_btc_stamp')!=stamp or '_pm_btc_features' not in self.__dict__:
            self._pm_btc_features=btc_risk_features(btc,self.dp.get_pair_dataframe('BTC/USDT:USDT','1h'));self._pm_btc_stamp=stamp
        if self.correlation_cap:self.hourly_returns(metadata['pair'],refresh=True)
        left=pd.DataFrame({'date':pd.to_datetime(df.date,utc=True).astype('datetime64[ns, UTC]')})
        aligned=left.merge(self._pm_btc_features,on='date',how='left',validate='one_to_one',sort=False)
        for column in ['pm_shock','pm_vol_ratio','pm_btc_hour_return']:df[column]=aligned[column].to_numpy()
        return df

    def populate_entry_trend(self,df,metadata):
        df=super().populate_entry_trend(df,metadata)
        if self.shock_gate:df.loc[df.pm_shock.eq(True),'enter_long']=0
        return df

    def long_level(self,trade):
        cache=self.__dict__.setdefault('_pm_long_cache',{})
        if trade.id not in cache:cache[trade.id]=trade.get_custom_data(key='pm_long_stop',default=None)
        return cache[trade.id]

    def pending_distance(self,pair,rate,short):
        if short:return self.__dict__.get('_short_pending',{}).get(pair)
        frame,_=self.dp.get_analyzed_dataframe(pair,self.timeframe)
        if frame.empty:return None
        atr=frame.iloc[-1].research_short_atr
        return min(max(2*atr,rate*.01),rate*.99) if np.isfinite(atr) and atr>0 else None

    def occupied_risk(self,equity):
        risk=0.;fee=self.config.get('fee',.0005)
        for trade in Trade.get_trades_proxy(is_open=True):
            if trade.nr_of_successful_entries==0:
                pending=self.__dict__.get('_pm_pending',{}).get(trade.pair)
                if pending is None:return equity*self.portfolio_limit
                # Existing unfilled trade is a real reservation. Failed requests
                # without an open Trade do not reserve anything.
                risk+=pending['risk_reserved'];continue
            stop=self.short_levels(trade)[0] if trade.is_short else self.long_level(trade)
            if stop is None:return equity*self.portfolio_limit
            risk+=trade.amount*(abs(stop-trade.open_rate)+fee*(stop+trade.open_rate))
        return risk

    def remaining_risk(self,equity):
        return float('inf') if self.portfolio_limit is None else max(0.,equity*self.portfolio_limit-self.occupied_risk(equity))

    def custom_stake_amount(self,pair,current_time,current_rate,proposed_stake,min_stake,max_stake,leverage,entry_tag,side,**kwargs):
        stake=super().custom_stake_amount(pair,current_time,current_rate,proposed_stake,min_stake,max_stake,leverage,entry_tag,side,**kwargs)
        short=side=='short';fee=self.config.get('fee',.0005)
        need_plan=(not short and (self.long_stop or self.long_budget)) or self.portfolio_limit is not None
        if need_plan:
            distance=self.pending_distance(pair,current_rate,short)
            if distance is None:return 0.
            equity=self.wallets.get_total_stake_amount()
            budget=min(equity*.01 if short or self.long_budget else float('inf'),self.remaining_risk(equity))
            per_coin=loss_per_coin(current_rate,distance,short,fee)
            stake=min(stake,budget*current_rate/(leverage*per_coin),max_stake)
            self.__dict__.setdefault('_pm_pending',{})[pair]={'distance':distance,'risk_reserved':stake*leverage/current_rate*per_coin}
        if not short:
            if self.half_long:stake*=.5
            if self.volatility_target:
                frame,_=self.dp.get_analyzed_dataframe(pair,self.timeframe)
                if not frame.empty and frame.iloc[-1].pm_vol_ratio>2 and frame.iloc[-1].pm_btc_hour_return<0:stake*=.5
        return stake if min_stake is None or stake>=min_stake else 0.

    def hourly_returns(self,pair,refresh=False):
        cache=self.__dict__.setdefault('_pm_hour_returns',{})
        if refresh or pair not in cache:
            frame=self.dp.get_pair_dataframe(pair,'1h')
            dates=pd.to_datetime(frame.date,utc=True).astype('datetime64[ns, UTC]')
            r=np.log(frame.close.astype(float)).diff().where(dates.diff().eq(pd.Timedelta(hours=1)))
            cache[pair]=pd.Series(r.to_numpy(),index=dates+pd.Timedelta(hours=1))
        return cache[pair]

    def pair_correlation(self,a,b,now):
        at=pd.Timestamp(now).floor('h');key=(tuple(sorted([a,b])),at)
        cache=self.__dict__.setdefault('_pm_corr_cache',{})
        if key not in cache:
            data=pd.concat([self.hourly_returns(a).loc[at-pd.Timedelta(days=7):at],self.hourly_returns(b).loc[at-pd.Timedelta(days=7):at]],axis=1).dropna().tail(168)
            value=data.iloc[:,0].corr(data.iloc[:,1]) if len(data)>=120 else float('nan')
            cache[key]=float(value) if np.isfinite(value) else 1.
        return cache[key]

    def confirm_trade_entry(self,pair,order_type,amount,rate,time_in_force,current_time,entry_tag,side,**kwargs):
        short=side=='short'
        if self.side_cap or self.correlation_cap:
            same=[t for t in Trade.get_trades_proxy(is_open=True) if t.is_short==short]
            if self.side_cap and len(same)>=2:return False
            if self.correlation_cap and sum(self.pair_correlation(pair,t.pair,current_time)>=.75 for t in same)>=2:return False
        if self.stop_cooldown and not short and recent_long_stop_guard(Trade.get_trades_proxy(is_open=False),pair,current_time):return False
        if self.portfolio_limit is not None or (self.long_budget and not short):
            pending=self.__dict__.get('_pm_pending',{}).get(pair)
            if pending is None:return False
            equity=self.wallets.get_total_stake_amount();allowed=min(equity*.01,self.remaining_risk(equity))
            risk=amount*loss_per_coin(rate,pending['distance'],short,self.config.get('fee',.0005))
            if risk>allowed+1e-6:return False
        return super().confirm_trade_entry(pair,order_type,amount,rate,time_in_force,current_time,entry_tag,side,**kwargs)

    def order_filled(self,pair,trade,order,current_time,**kwargs):
        super().order_filled(pair,trade,order,current_time,**kwargs)
        if not trade.is_short and self.long_stop and order.ft_order_side==trade.entry_side and trade.nr_of_successful_entries==1:
            distance=self._pm_pending[pair]['distance'];first=trade.select_filled_orders(trade.entry_side)[0].safe_price
            stop=max(first-distance,first*.001)
            trade.set_custom_data(key='pm_long_stop',value=stop);self.__dict__.setdefault('_pm_long_cache',{})[trade.id]=stop
        if self.portfolio_limit is not None and order.ft_order_side==trade.entry_side:
            equity=self.wallets.get_total_stake_amount()
            logging.getLogger(__name__).info('PM_RISK_AUDIT '+json.dumps({'time':current_time.isoformat(),'pair':pair,'trade_id':trade.id,'equity_basis':equity,'occupied_planned_loss':self.occupied_risk(equity),'limit_fraction':self.portfolio_limit}))

    def custom_stoploss(self,pair,trade,current_time,current_rate,current_profit,after_fill=False,**kwargs):
        if not trade.is_short and self.long_stop:
            stop=self.long_level(trade)
            return None if stop is None else stoploss_from_absolute(stop,current_rate,is_short=False,leverage=trade.leverage)
        return super().custom_stoploss(pair,trade,current_time,current_rate,current_profit,after_fill=after_fill,**kwargs)

    def custom_exit(self,pair,trade,current_time,current_rate,current_profit,**kwargs):
        if self.expired(trade,current_time):return self.deadline_reason
        if not trade.is_short and self.long_stop:
            stop=self.long_level(trade)
            if stop is not None and current_rate<=stop:return self.stop_reason
        return super().custom_exit(pair,trade,current_time,current_rate,current_profit,**kwargs)

    def confirm_trade_exit(self,pair,trade,order_type,amount,rate,time_in_force,exit_reason,current_time,**kwargs):
        if not trade.is_short and self.long_stop and exit_reason in [self.stop_reason,'stop_loss','trailing_stop_loss']:return True
        return super().confirm_trade_exit(pair,trade,order_type,amount,rate,time_in_force,exit_reason,current_time,**kwargs)


class NFIShortPMControl(NFIShortPMBase):
    pass

class NFIShortPMHalf(NFIShortPMBase):
    half_long=True

class NFIShortPMLongBudget(NFIShortPMBase):
    long_budget=True

class NFIShortPMLongStop(NFIShortPMBase):
    long_stop=True

class NFIShortPMLongATR(NFIShortPMBase):
    long_stop=True
    long_budget=True

class NFIShortPMPortfolio(NFIShortPMLongATR):
    portfolio_limit=.03

class NFIShortPMCooldown(NFIShortPMPortfolio):
    stop_cooldown=True

class NFIShortPMShock(NFIShortPMBase):
    shock_gate=True

class NFIShortPMVolatility(NFIShortPMBase):
    volatility_target=True

class NFIShortPMCorrelation(NFIShortPMBase):
    correlation_cap=True

class NFIShortPMSideCap(NFIShortPMBase):
    side_cap=True
