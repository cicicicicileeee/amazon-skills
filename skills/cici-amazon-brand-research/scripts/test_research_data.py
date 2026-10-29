"""Synthetic fixtures only; no network or installed-skill changes."""
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

import research_data as rd


def monthly(**values):
    row = dict.fromkeys(rd.SCHEMAS['asin_monthly'].split(','), '')
    row.update(marketplace='amazon.es', month='2026-09', asin='SYNTH00001',
               entity_level='child', brand='Synthetic Brand', brand_verified='true',
               sales_scope='child', count_key='SYNTH00001', units='10', revenue='200',
               currency='EUR', data_kind='estimate', measurement_source='Synthetic Provider v1', availability='unknown', source_id='s1')
    row.update(values)
    return row


def complaint(**values):
    row = dict.fromkeys(rd.SCHEMAS['complaints'].split(','), '')
    row.update(evidence_id='e1', source_id='s1', platform='Example Forum',
               evidence_set='social', url='https://example.org/topic',
               published_at='2026-09-01', collected_at='2026-10-22',
               brand='Synthetic Brand', model='Model A', country='ES',
               country_basis='Explicit country in original', market_relevance='target',
               firsthand='true', promotional='false', complaint='true',
               issue_code='durability', severity='core_function', excerpt='Synthetic test quote')
    row.update(values)
    return row


class ResearchTests(unittest.TestCase):
    def test_date_windows(self):
        self.assertEqual(rd.window('2026-10-22'), ('2025-10-01', '2026-09-30'))
        self.assertEqual(rd.window('2025-01-01'), ('2024-01-01', '2024-12-31'))
        self.assertEqual(rd.window('2024-03-10', 1), ('2024-02-01', '2024-02-29'))

    def test_market(self):
        self.assertEqual(rd.market('https://www.amazon.es/s?k=brand'), ('amazon.es', 'ES', 'EUR'))
        self.assertEqual(rd.market('US')[0], 'amazon.com')
        with self.assertRaises(ValueError):
            rd.market('amazon.es.evil.example')

    def test_init_and_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'run'
            rd.init_run('Synthetic Brand', 'ES', '2026-10-22', root)
            self.assertFalse(rd.validate(root)['errors'])
            self.assertTrue(rd.validate(root)['warnings'])
            with self.assertRaises(FileExistsError):
                rd.init_run('Synthetic Brand', 'ES', '2026-10-22', root)
            rd.write_csv(root / 'data/asin_monthly.csv', [monthly(month='2020-01')], rd.SCHEMAS['asin_monthly'].split(','))
            result = rd.validate(root)
            self.assertTrue(any('outside' in e for e in result['errors']))
            self.assertTrue(any('source_id' in e for e in result['errors']))

    def test_parent_measurement_dedup(self):
        a = monthly(parent_asin='PARENT', sales_scope='parent', count_key='PARENT')
        b = dict(a, asin='SYNTH00002')
        result = rd.aggregate([a, b])[0]
        self.assertEqual(result['known_units'], Decimal(10))
        self.assertEqual(result['observed_child_asins'], 2)
        self.assertIsNone(result['child_asins_with_sales'])
        self.assertIsNone(result['active_child_asins'])
        with self.assertRaises(ValueError):
            rd.aggregate([a, dict(b, units='11')])

    def test_mixed_scopes_rejected(self):
        with self.assertRaises(ValueError):
            rd.aggregate([monthly(parent_asin='PARENT'), monthly(asin='PARENT', parent_asin='', entity_level='parent', sales_scope='parent', count_key='PARENT')])

    def test_partial_revenue_asp(self):
        result = rd.aggregate([monthly(), monthly(asin='SYNTH00002', count_key='SYNTH00002', revenue='')])[0]
        self.assertEqual(result['known_units'], 20)
        self.assertEqual(result['matched_asp'], 20)
        self.assertEqual(result['revenue_coverage'], Decimal('0.5'))

    def test_currency_and_actual_separation(self):
        # Same primary key in two currencies is invalid, so use distinct ASINs.
        result = rd.aggregate([monthly(), monthly(asin='SYNTH00002', count_key='SYNTH00002', currency='USD'), monthly(data_kind='actual')])
        self.assertEqual(len(result), 3)

    def test_missing_zero_unknown_brand(self):
        self.assertEqual(rd.aggregate([monthly(brand_verified='false')]), [])
        self.assertIsNone(rd.aggregate([monthly(units='', revenue='')])[0]['known_units'])
        self.assertEqual(rd.aggregate([monthly(units='0', revenue='0')])[0]['known_units'], 0)
        self.assertIsNone(rd.aggregate([monthly(sales_scope='unknown')])[0]['known_units'])
        for invalid in ('-1', 'NaN', 'Infinity', 'text'):
            with self.assertRaises(ValueError):
                rd.aggregate([monthly(units=invalid)])

    def test_duplicate_primary_key(self):
        with self.assertRaises(ValueError):
            rd.aggregate([monthly(), monthly()])

    def test_estimation_sources_separate(self):
        result = rd.aggregate([monthly(), monthly(measurement_source='Synthetic Provider v2')])
        self.assertEqual(len(result), 2)
        self.assertEqual([r['known_units'] for r in result], [10, 10])

    def test_complaint_dedup_and_multitheme(self):
        rows, themes, meta = rd.complaint_analysis([
            complaint(experience_id='event-1'),
            complaint(evidence_id='e2', experience_id='event-1', issue_code='service'),
            complaint(evidence_id='e3', experience_id='event-1'),
            complaint(evidence_id='e4', experience_id='event-2'),
        ])
        self.assertEqual(meta['eligible_independent_experiences'], 2)
        durability = next(r for r in themes if r['issue_code'] == 'durability')
        self.assertEqual(durability['independent_experiences'], 2)
        self.assertEqual(durability['sample_experiences'], 2)

    def test_bare_video_not_dedup(self):
        _, _, meta = rd.complaint_analysis([complaint(url='https://www.youtube.com/watch?v=demo', evidence_id='e1'), complaint(url='https://www.youtube.com/watch?v=demo', evidence_id='e2')])
        self.assertEqual(meta['eligible_independent_experiences'], 2)
        _, _, meta = rd.complaint_analysis([complaint(url='https://www.youtube.com/watch?v=demo&lc=comment-1&utm_source=x'), complaint(url='https://www.youtube.com/watch?lc=comment-1&v=demo')])
        self.assertEqual(meta['eligible_independent_experiences'], 1)

    def test_unknown_country_and_background(self):
        _, themes, meta = rd.complaint_analysis([complaint(country_basis=''), complaint(evidence_id='e2', firsthand='unknown'), complaint(evidence_id='e3', promotional='true')])
        self.assertEqual(themes[0]['market_relevance'], 'unknown')
        self.assertEqual(meta['excluded_rows'], 2)

    def test_crosspost_groups_not_combined(self):
        _, themes, meta = rd.complaint_analysis([complaint(content_hash='synthetic-full-text-hash'), complaint(content_hash='synthetic-full-text-hash', evidence_set='amazon_review')])
        self.assertEqual(meta['eligible_independent_experiences'], 1)
        self.assertEqual(len(themes), 2)
        self.assertIn('Do not sum', meta['note'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
