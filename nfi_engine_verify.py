"""Check the pinned Freqtrade can import X8 and load all exported datasets offline."""
import importlib.metadata
import importlib.util
import json
import subprocess
import sys

import nfi_data as data
from nfi_verify import verify_sources


def main():
    from freqtrade.data.history.datahandlers.jsondatahandler import JsonGzDataHandler
    from freqtrade.enums import CandleType
    from freqtrade.strategy.interface import IStrategy
    if importlib.metadata.version('freqtrade')!='2026.9':
        raise ValueError('use the pinned freqtrade==2026.9 engine')
    verify_sources()
    path=data.STUDY/'upstream/NostalgiaForInfinityX8.py'
    spec=importlib.util.spec_from_file_location('nfi_pinned_x8',path)
    module=importlib.util.module_from_spec(spec)
    sys.modules[spec.name]=module;spec.loader.exec_module(module)
    cls=module.NostalgiaForInfinityX8
    if not issubclass(cls,IStrategy) or cls.timeframe!='5m' or cls.info_timeframes!=['15m','1h','4h','1d']:
        raise ValueError('unexpected strategy interface')
    handler=JsonGzDataHandler(data.LOCAL/'freqtrade')
    counts={'futures':0,'mark':0}
    for file in ('manifest.json','mark_manifest.json'):
        for item in data.read(data.ARCHIVE/file)['files']:
            kind=CandleType.MARK if file=='mark_manifest.json' else CandleType.FUTURES
            # Read without filling gaps, resampling or dropping last rows.
            frame=handler._ohlcv_load(item['pair'],item['timeframe'],None,kind)
            if len(frame)!=item['rows'] or frame.empty:
                raise ValueError('engine row count differs from native manifest')
            if int(frame.iloc[0]['date'].timestamp()*1000)!=data.millis(item['start']):
                raise ValueError('engine start time differs')
            step=3600000 if kind==CandleType.MARK else data.BARS[item['timeframe']][1]
            if int(frame.iloc[-1]['date'].timestamp()*1000)+step!=data.millis(item['end_exclusive']):
                raise ValueError('engine end time differs')
            counts[str(kind)]+=1
    result=dict(status='success',freqtrade=importlib.metadata.version('freqtrade'),
                strategy=cls.__name__,strategy_import='success',datasets=counts,
                scope='Engine import and data loading only; NOT a full strategy backtest')
    freeze=subprocess.check_output([sys.executable,'-m','pip','freeze'],text=True)
    (data.ROOT/'results/nfi/engine_requirements.txt').write_text(freeze,encoding='utf-8')
    data.write(data.ROOT/'results/nfi/engine_verification.json',result)
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    from datetime import datetime,timezone
    path=data.ROOT/'results/nfi/engine_verification.json'
    data.write(path,dict(status='running',started_at=datetime.now(timezone.utc).isoformat()))
    try:main()
    except Exception as exc:
        data.write(path,dict(status='failed',error=str(exc),finished_at=datetime.now(timezone.utc).isoformat()))
        raise
