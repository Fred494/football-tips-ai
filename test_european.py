"""Regression checks for European fixture identity and pre-match context."""
import unittest
from collections import defaultdict
from european_data import parse_schedule, club_key
from build import european_context, features


class EuropeanTests(unittest.TestCase):
    def test_schedule_parser_deduplicates_and_keeps_scores_separate(self):
        html = '<h3>Matchday 5</h3><p><b>Tuesday 24 November 2026</b><br/>'
        for index in range(100):
            html += f'<a href="https://www.uefa.com/uefachampionsleague/match/{index+1000}--a-b/">Home {index} vs Away {index}</a> (18:45)<br/>'
        html += '</p>'
        rows = parse_schedule(html + html, 'uefa.cl')
        self.assertEqual(len(rows),100)
        self.assertTrue(all(row['score'] is None for row in rows))
        self.assertEqual(rows[0]['kickoffCET'],'18:45')
        with self.assertRaises(ValueError):
            parse_schedule('<p>No matches</p>','uefa.cl')

    def test_names_match_domestic_identity(self):
        self.assertEqual(club_key('Inter'),club_key('FC Internazionale Milano'))
        self.assertEqual(club_key('Porto'),club_key('FC Porto'))
        self.assertNotEqual(club_key('Manchester City'),club_key('Manchester United'))

    def test_domestic_context_contributes_without_future_results(self):
        domestic=dict(id='d',day='2026-11-20',home='FC Porto',away='Arsenal FC',score=[1,0],league='pt.1',season='2026-27')
        cup=dict(id='e',day='2026-11-24',home='Porto',away='Arsenal',score=None,league='uefa.cl',season='2026-27')
        leagues=[dict(code='pt.1',seasons={'2026-27':[domestic]}),
                 dict(code='uefa.cl',seasons={'2026-27':[cup]})]
        context=european_context(leagues)
        self.assertEqual(cup['home'],'FC Porto')
        self.assertEqual(cup['away'],'Arsenal FC')
        self.assertEqual(len(context['2026-27']),1)
        recent=defaultdict(list,{'FC Porto':[domestic],'Arsenal FC':[domestic]})
        current=defaultdict(list)
        elo=defaultdict(lambda:1500.)
        opponents=defaultdict(list,{'FC Porto':[1500.],'Arsenal FC':[1500.]})
        x,stats=features(cup,recent,current,elo,[],opponents,all_venues=True)
        self.assertEqual(stats[2]['ppg'],3.)
        self.assertEqual(stats[3]['ppg'],0.)
        self.assertEqual(stats[0]['n'],0)
