import unittest
from settlementlab.core.calendar import BusinessCalendar,FixedClock,iso_date
from settlementlab.core.validation import DomainError

class CalendarControls(unittest.TestCase):
    def test_weekends_closures_and_leap_year(self):
        self.assertEqual(BusinessCalendar().next_day('2026-11-06'),'2026-11-09')
        self.assertEqual(BusinessCalendar('demo-v1',('2026-11-09',)).next_day('2026-11-06'),'2026-11-10')
        self.assertEqual(BusinessCalendar().next_day('2028-02-28'),'2028-02-29')
        self.assertEqual(FixedClock('2026-11-09').describe()['mode'],'simulated')
    def test_policies_are_fingerprinted_and_validated(self):
        first=BusinessCalendar();changed=BusinessCalendar(closed_dates=('2026-11-09',))
        self.assertNotEqual(first.to_dict()['fingerprint'],changed.to_dict()['fingerprint'])
        bad=first.to_dict();bad['closed_dates']=['2026-11-09']
        with self.assertRaises(DomainError):BusinessCalendar.from_dict(bad)
        for value in ['20261109','2026-02-30',None]:
            with self.assertRaises(DomainError):iso_date(value)
        with self.assertRaises(DomainError):BusinessCalendar(closed_dates=['2026-11-09']*2)
        with self.assertRaises(DomainError):BusinessCalendar().next_day('9999-12-31')
