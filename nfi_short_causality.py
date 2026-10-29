"""Sample newly enabled short tags with isolated replay caches and ULP matching."""
import json,sys,tempfile
from pathlib import Path
from freqtrade.optimize.analysis.lookahead import LookaheadAnalysis
from freqtrade.optimize.backtesting import Backtesting,LOW_IDX,HIGH_IDX
from freqtrade.main import main
from nfi_precision import candle_contains

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'results/nfi/short_search'
original_prepare=LookaheadAnalysis.prepare_data
original_full=LookaheadAnalysis.fill_full_varholder
original_row=LookaheadAnalysis.analyze_row
records=[]


def isolated(self,holder,pairs):
    runtime=ROOT/'data/nfi_ytd2026/causality';runtime.mkdir(parents=True,exist_ok=True)
    previous=self.local_config['user_data_dir']
    self.local_config['user_data_dir']=Path(tempfile.mkdtemp(dir=runtime))
    try:return original_prepare(self,holder,pairs)
    finally:self.local_config['user_data_dir']=previous


def select_new(self):
    original_full(self)
    frame=self.full_varHolder.result['results']
    tags={'505','506','543','544','545','546','548','561','563'}
    mask=frame.is_short&frame.enter_tag.fillna('').map(lambda tag:bool(set(tag.split())&tags))
    self.full_varHolder.result['results']=frame.loc[mask].reset_index(drop=True)
    chosen=self.full_varHolder.result['results'][['pair','enter_tag','open_date','close_date']].head(self.targeted_trade_amount)
    (OUT/'causality_selection.json').write_text(chosen.to_json(orient='records',date_format='iso',indent=2)+'\n')


def capture(self,idx,row):
    original_row(self,idx,row)
    records.append({'pair':row['pair'],'tag':row['enter_tag'],'open':str(row['open_date']),'close':str(row['close_date']),
                    'false_entries':self.current_analysis.false_entry_signals,'false_exits':self.current_analysis.false_exit_signals,
                    'biased_indicators':list(self.current_analysis.false_indicators)})
    (OUT/'causality_detail.json').write_text(json.dumps(records,indent=2)+'\n')


if __name__=='__main__':
    LookaheadAnalysis.prepare_data=isolated
    LookaheadAnalysis.fill_full_varholder=select_new
    LookaheadAnalysis.analyze_row=capture
    Backtesting._get_order_filled=lambda self,rate,row:candle_contains(rate,row[LOW_IDX],row[HIGH_IDX])
    sys.exit(main(sys.argv[1:]))
