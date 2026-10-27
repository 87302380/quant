import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import cloud_data


class CloudDataTests(unittest.TestCase):
    def test_pack_restore_roundtrip(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);data=root/'data';archive=root/'datasets';data.mkdir()
            file=data/'BTC-USDT-SWAP_5m_fixture.csv'
            value=b'timestamp,open,high,low,close,volume\n2026-01-01T00:00:00Z,1,2,1,2,3\n'
            file.write_bytes(value)
            with patch.object(cloud_data,'DATA',data),patch.object(cloud_data,'ARCHIVE',archive):
                cloud_data.pack();file.unlink();cloud_data.restore()
                self.assertEqual(file.read_bytes(),value)
                file.write_bytes(b'changed')
                with self.assertRaises(ValueError):cloud_data.restore()


if __name__=='__main__':unittest.main()
