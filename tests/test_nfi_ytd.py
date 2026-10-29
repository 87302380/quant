"""YTD range planning must preserve checkpoints and expose every gap."""
import unittest
from nfi_ytd import missing_intervals, BARS
from nfi_data import millis, validate


class YearToDatePlanningTest(unittest.TestCase):
    def test_missing_ranges_group_and_resume_without_redownloading_present_rows(self):
        self.assertEqual(missing_intervals({0,10,15,30},0,40,5),[(5,10),(20,30),(35,40)])
        self.assertEqual(missing_intervals(set(range(0,40,5)),0,40,5),[])
        self.assertEqual(missing_intervals(set(),0,40,5),[(0,40)])

    def test_warmup_is_allowed_and_timeframes_are_native(self):
        self.assertEqual(set(BARS),{'5m','15m','1h','4h','1d','mark1h'})
        self.assertEqual(BARS['1d'][0],'1Dutc')
        for tf,(_,step,start) in BARS.items():
            self.assertGreaterEqual(millis(start),millis('2024-01-01'))
            self.assertLess(millis(start),millis('2026-01-01'))
            self.assertEqual(millis(start)%step,0)

    def test_native_gap_and_unclosed_rows_cannot_be_published(self):
        row=lambda ts,closed='1':[str(ts),'100','102','99','101','1','1','100',closed]
        validate([row(0),row(300000)],0,600000,300000)
        with self.assertRaises(ValueError):validate([row(0)],0,600000,300000)
        with self.assertRaises(ValueError):validate([row(0),row(300000,'0')],0,600000,300000)


if __name__=='__main__':unittest.main()
