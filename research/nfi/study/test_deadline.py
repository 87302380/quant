"""Deadline contract independent of profit, direction, rebuys and exit vetoes."""
from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('deadline_control', Path(__file__).with_name('NFI24Hour.py'))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class DeadlineTest(unittest.TestCase):
    def test_deadline_overrides_losses_and_rebuys_and_parent_exit_veto(self):
        strategy = module.NFI24Hour.__new__(module.NFI24Hour)
        opened = datetime(2026, 7, 1, tzinfo=timezone.utc)
        trade = SimpleNamespace(open_date_utc=opened, last_entry_date_utc=opened+timedelta(hours=23))
        now = opened + timedelta(hours=24)
        with patch.object(module.NostalgiaForInfinityX8, 'custom_exit', return_value=None) as parent:
            self.assertIsNone(strategy.custom_exit('X',trade,now-timedelta(minutes=5),1,-.5))
            self.assertEqual(parent.call_count,1)
            for profit in (-.8, .2):
                self.assertEqual(strategy.custom_exit('X',trade,now,1,profit),strategy.deadline_reason)
            self.assertEqual(parent.call_count,1)
        with patch.object(module.NostalgiaForInfinityX8,'confirm_trade_exit',return_value=False):
            self.assertTrue(strategy.confirm_trade_exit('X',trade,'limit',1,1,'GTC',strategy.deadline_reason,now))
            self.assertFalse(strategy.confirm_trade_exit('X',trade,'limit',1,1,'GTC','other_exit',now))
        with patch.object(module.NostalgiaForInfinityX8,'adjust_trade_position',return_value=100) as parent:
            self.assertIsNone(strategy.adjust_trade_position(trade,now))
            parent.assert_not_called()
        self.assertTrue(strategy.check_entry_timeout('X',trade,None,now))


if __name__ == '__main__':
    unittest.main()
