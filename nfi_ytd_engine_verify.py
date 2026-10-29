"""Read every separate YTD dataset with pinned Freqtrade without trading/network."""
from datetime import datetime, timezone
import importlib.metadata
import json

from freqtrade.data.history.datahandlers.jsondatahandler import JsonGzDataHandler
from freqtrade.enums import CandleType
import nfi_data as old
import nfi_ytd as ytd


def main():
    path=ytd.STUDY/'engine_verification.json'
    result={'started_at':datetime.now(timezone.utc).isoformat(),'status':'running'}
    old.write(path,result)
    try:
        version=importlib.metadata.version('freqtrade')
        if version!='2026.9':raise ValueError('Pinned Freqtrade2026.9 required')
        verified=old.read(ytd.STUDY/'verification.json')
        manifest_path=ytd.ARCHIVE/'manifest.json'
        if verified['status']!='success' or verified['data_manifest_sha256']!=old.sha(manifest_path.read_bytes()):
            raise ValueError('Require current successful native-data verification first')
        items=old.read(manifest_path)['files']
        handler=JsonGzDataHandler(ytd.LOCAL/'freqtrade')
        counts={'futures':0,'mark':0}
        for item in items:
            kind=CandleType.MARK if item['candle_type']=='mark' else CandleType.FUTURES
            frame=handler._ohlcv_load(item['pair'],item['timeframe'],None,kind)
            if frame.empty or len(frame)!=item['rows']:raise ValueError('Engine row count differs')
            if int(frame.iloc[0]['date'].timestamp()*1000)!=old.millis(item['start']):
                raise ValueError('Engine start differs')
            key='mark1h' if item['candle_type']=='mark' else item['timeframe']
            if int(frame.iloc[-1]['date'].timestamp()*1000)+ytd.BARS[key][1]!=old.millis(item['end_exclusive']):
                raise ValueError('Engine end differs')
            counts[item['candle_type']]+=1
        result.update(status='success',freqtrade=version,datasets=counts,
                      scope='Native data verified and engine-readable; no fullYTD strategy backtest claimed')
    except Exception as exc:
        result.update(status='failed',error=str(exc));raise
    finally:
        result['finished_at']=datetime.now(timezone.utc).isoformat()
        old.write(path,result)
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
