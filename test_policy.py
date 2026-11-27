from datetime import date
import unittest
from window import history_start
from picks import assign_picks,home_exception
from ranking_data import coefficient_features

class PolicyTests(unittest.TestCase):
    def test_exact_two_year_cutoff(self):
        self.assertEqual(history_start(date(2026,11,27)),date(2024,11,27))
        self.assertEqual(history_start(date(2024,2,29)),date(2022,2,28))

    def test_threshold_and_every_top_five_host(self):
        table=[dict(team=f'Team {i}') for i in range(20)]
        def fixture(identity,prob,home,away):
            return dict(id=identity,day='2026-11-28',home=home,away=away,league='test',
                        table=table,market='X2',prob=prob,breakdown=[1-prob,.2,prob-.2])
        regular=fixture('regular',.875,'Team 8','Team 9')
        low=fixture('low',.874999,'Team 8','Team 9')
        risk=fixture('risk',.7,'Team 4','Team 15')
        risk2=fixture('risk2',.9,'Team 0','Team 19')
        snapshot=dict(updated='2026-11-27T12:00:00+00:00',matches=[regular,low,risk,risk2],leagues=[])
        assign_picks(snapshot)
        self.assertEqual(regular['pick'],'standard')
        self.assertNotIn('pick',low)
        self.assertEqual(risk['pick'],'exception')
        self.assertEqual(risk2['pick'],'exception')
        self.assertEqual(risk['market'],'1X')
        self.assertAlmostEqual(risk['prob'],.5)
        self.assertFalse(home_exception(None,table,'Team 15','Team 4'))

    def test_coefficients_are_unavailable_before_publication(self):
        clubs={'home':dict(rank=1,points=50),'away':dict(rank=20,points=5)}
        archive={'2026':dict(available='2026-07-03',clubs=clubs,source='UEFA')}
        self.assertIsNone(coefficient_features('Home','Away','2026-07-03',archive))
        self.assertIsNotNone(coefficient_features('Home','Away','2026-07-04',archive))
