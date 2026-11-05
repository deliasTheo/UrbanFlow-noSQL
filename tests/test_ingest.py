"""Contrôles du document MongoDB et des cas horaires."""
import unittest
import pandas as pd
from urbanflow.timeutil import trip_durations


class DurationTest(unittest.TestCase):
    def test_transition_and_unresolvable(self):
        pickup = pd.Series(pd.to_datetime(['2024-03-10 01:30', '2024-03-10 02:30', None]))
        dropoff = pd.Series(pd.to_datetime(['2024-03-10 03:30', '2024-03-10 03:30', None]))
        flags = trip_durations(pickup, dropoff)
        exported = flags.duration_s.mask(flags.dst_unresolved)
        self.assertEqual(exported[0], 3600)
        self.assertTrue(flags.dst_corrected[0])
        self.assertTrue(pd.isna(exported[1]))
        self.assertTrue(pd.isna(exported[2]))


class DocumentsTest(unittest.TestCase):
    def test_uncertain_duration_is_not_exported(self):
        from urbanflow.ingest import documents
        from urbanflow.quality import ANOMALY_CODES
        trips = pd.DataFrame({'tpep_pickup_datetime': pd.to_datetime(['2024-03-10 02:30'])})
        flags = pd.DataFrame({code: [False] for code in ANOMALY_CODES})
        flags['DST_UNRESOLVED'] = True
        flags['duration_s'] = 3600.0
        doc = next(documents(trips, flags, 'file', 0, 1))
        self.assertIsNone(doc['duration_s'])
        self.assertEqual(doc['data']['tpep_pickup_datetime'], '2024-03-10T02:30:00')
        self.assertEqual(doc['quality_flags'], ['DST_UNRESOLVED'])
        self.assertEqual(set(doc), {'_id', 'source', 'data', 'duration_s', 'quality_flags'})


if __name__ == '__main__':
    unittest.main()
