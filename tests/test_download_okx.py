import json
import tempfile
import unittest
from pathlib import Path
from download_okx import STEP, BARS, download, export, open_db, timestamp


class FakeClient:
    base = 'https://www.okx.com'
    def __init__(self, fail=False): self.calls=0; self.fail=fail
    def get(self,path,params):
        self.calls+=1
        if self.fail and self.calls==2: raise OSError('network interrupted')
        cursor=int(params['after'])
        step=BARS[params['bar']]
        return dict(code='0',data=[[str(t),'100','102','98','101','3','0.03','3.03','1']
                    for t in range(cursor-step,max(-1,cursor-3*step),-step)])


class DownloadTests(unittest.TestCase):
    def test_higher_timeframes(self):
        for bar in ('1m','5m','1H','4H'):
            with tempfile.TemporaryDirectory() as tmp:
                db=open_db(Path(tmp)/'db')
                end=4*BARS[bar]
                download(FakeClient(),db,'BTC-USDT-SWAP',0,end,0,bar=bar)
                self.assertEqual(export(db,'BTC-USDT-SWAP',0,end,Path(tmp)/'x.csv',bar=bar),4)
                db.close()

    def test_resume_and_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=open_db(Path(tmp)/'db')
            with self.assertRaises(OSError): download(FakeClient(True),db,'BTC-USDT-SWAP',0,4*STEP,0)
            self.assertEqual(db.execute('select count(*) from candles').fetchone()[0],2)
            download(FakeClient(),db,'BTC-USDT-SWAP',0,4*STEP,0)
            path=Path(tmp)/'candles.csv'
            self.assertEqual(export(db,'BTC-USDT-SWAP',0,4*STEP,path),4)
            self.assertEqual(len(path.read_text().splitlines()),5)
            db.close()

    def test_gap_blocks_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=open_db(Path(tmp)/'db')
            with self.assertRaises(RuntimeError): export(db,'BTC-USDT-SWAP',0,STEP,Path(tmp)/'x.csv')
            self.assertFalse((Path(tmp)/'x.csv').exists())
            db.close()

    def test_dates(self):
        self.assertEqual(timestamp('1970-01-01T08:00:00+08:00'),0)
        for x in ['2025-01-01','2025-01-01T00:01:00Z']:
            with self.assertRaises(ValueError): timestamp(x)


if __name__ == '__main__': unittest.main()
