import gzip
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from decimal import Decimal

import nfi_data as data
from nfi_mark import validate_mark, mark_start
from nfi_expand import eligible
from nfi_verify import aggregate


class NfiDataTests(unittest.TestCase):
    def row(self,ts=0):
        return [str(ts),'10','12','9','11','100','25','250','1']

    def test_rejects_gaps_duplicates_unclosed_and_bad_ohlc(self):
        data.validate([self.row(),self.row(300000)],0,600000,300000)
        for rows in ([self.row()], [self.row(),self.row()], [self.row(),self.row(600000)]):
            with self.assertRaises(ValueError):data.validate(rows,0,600000,300000)
        for index,value in [(8,'0'),(2,'10'),(5,'-1'),(4,'NaN')]:
            row=self.row();row[index]=value
            with self.assertRaises(ValueError):data.validate([row],0,300000,300000)

    def test_mark_format_and_confirm(self):
        validate_mark([['0','10','12','9','11','1']],0,3600000)
        with self.assertRaises(ValueError):validate_mark([['0','10','12','9','11','0']],0,3600000)

    def test_new_contract_mark_history_starts_after_listing(self):
        launch=data.millis('2026-08-01T00:15:00Z')
        self.assertEqual(mark_start(launch),data.millis('2026-08-01T01:00:00Z'))
        self.assertEqual(mark_start(data.millis('2024-01-01')),data.millis('2026-06-24'))

    def test_universe_excludes_noncrypto_and_new_or_blacklisted_contracts(self):
        now=data.millis('2026-10-29')
        inst=dict(instId='BTC-USDT-SWAP',ctType='linear',settleCcy='USDT',state='live',instCategory='1',listTime=str(now-100*86400000))
        self.assertIsNone(eligible(inst,now,[]))
        self.assertEqual(eligible({**inst,'instCategory':'3'},now,[]),'not_crypto_category_1')
        self.assertEqual(eligible({**inst,'listTime':str(now-59*86400000)},now,[]),'younger_than_60_days')
        self.assertEqual(eligible(inst,now,['BTC/.*']),'upstream_blacklist')

    def test_deterministic_compression(self):
        with tempfile.TemporaryDirectory() as folder:
            a,b=Path(folder)/'a.gz',Path(folder)/'b.gz'
            data.compressed(a,b'hello');data.compressed(b,b'hello')
            self.assertEqual(a.read_bytes(),b.read_bytes())

    def test_metadata_hash_bytes_are_platform_independent(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'universe.json'
            data.write(path,{'pairs':['BTC/USDT:USDT']})
            self.assertNotIn(b'\r',path.read_bytes())
            self.assertEqual(data.read(path),{'pairs':['BTC/USDT:USDT']})

    def test_native_zero_trade_bars_do_not_create_false_higher_extremes(self):
        rows=[(0,list(map(Decimal,['12','12','12','12','0','0','0']))),
              (300000,list(map(Decimal,['10','11','9','10','5','1','10']))),
              (600000,list(map(Decimal,['10','10','10','10','0','0','0'])))]
        self.assertEqual(aggregate(rows),list(map(Decimal,['10','11','9','10','5','1','10'])))
        self.assertEqual(aggregate([rows[0]])[:4],[Decimal('12')]*4)

    def test_restore_base_volume_from_bundle_and_preserve_modified(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);archive=root/'archive';study=root/'study';out=root/'export'
            archive.mkdir();study.mkdir()
            universe=dict(pairs=[dict(instrument='BTC-USDT-SWAP')])
            data.write(study/'universe.json',universe)
            payload=json.dumps([self.row()]).encode();blob=gzip.compress(payload,mtime=0)
            name='BTC-USDT-SWAP_5m_0_300000.json.gz'
            with zipfile.ZipFile(archive/'BTC-USDT-SWAP.zip','w') as z:z.writestr(name,blob)
            item=dict(instrument='BTC-USDT-SWAP',pair='BTC/USDT:USDT',timeframe='5m',archive=name,
                      archive_sha256=data.sha(blob),raw_sha256=data.sha(payload),raw_bytes=len(payload),
                      start=data.iso(0),end_exclusive=data.iso(300000))
            data.write(archive/'manifest.json',dict(universe_sha256=data.sha((study/'universe.json').read_bytes()),files=[item]))
            with patch.object(data,'ARCHIVE',archive),patch.object(data,'STUDY',study),patch.object(data,'BARS',{'5m':('5m',300000,'1970-01-01')}):
                data.restore(out)
                dest=out/'futures/BTC_USDT_USDT-5m-futures.json.gz'
                self.assertEqual(json.loads(gzip.decompress(dest.read_bytes()))[0][-1],25.)
                data.compressed(dest,b'[]')
                with self.assertRaisesRegex(ValueError,'preserving modified'):data.restore(out)

    def test_archive_path_traversal(self):
        for name in ('../outside.gz','a/b.gz','a\\b.gz'):
            with self.assertRaises(ValueError):data.archive_bytes(name)


if __name__=='__main__':unittest.main()
