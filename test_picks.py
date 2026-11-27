from datetime import date, timedelta
from unittest import TestCase

import numpy as np

from history import merge_picks, update_history
from international_model import adjust_qualification
from picks import assign_picks, home_exception


class PublicationTest(TestCase):
    def test_archives_displayed_threshold_and_exception_once(self):
        day = date(2026, 11, 16)
        matches = [
            dict(id=str(i), day=(day + timedelta(days=offset)).isoformat(),
                 home='Home', away='Away', league='league', kickoff=kickoff,
                 market=market, prob=prob, stale=stale, homeException=True,
                 breakdown=[prob-.2,.2,1-prob],table=([dict(team='Home')]+
                    [dict(team='Other '+str(n)) for n in range(8)]+[dict(team='Away')]) if i==1 else [])
            for i, (prob, market, offset, kickoff, stale) in enumerate([
                (.875, '1X', 0, '14:00', False),
                (.83, '1X', 0, '14:00', False),
                (.81, '1X', 0, '14:00', False),
                (.84, 'X2', 0, '14:00', False),
                (.95, 'X2', 4, '14:00', False),
                (.94, 'X2', 0, '00:00', False),
                (.94, 'X2', 0, '14:00', True),
            ])
        ]
        snapshot = dict(updated="2026-11-16T01:00:00+00:00",
                        leagues=[dict(code='league',name='League')], matches=matches)
        assign_picks(snapshot)
        self.assertEqual([m.get('pick') for m in matches],
                         ['standard','exception',None,None,None,None,None])
        history = update_history({'picks': []}, snapshot, {'0': [2, 2], '1': [0, 2]})
        rows = {m['id']: m for m in history['picks']}
        self.assertEqual(tuple(rows), ('1','0'))
        self.assertEqual((rows['0']['status'], rows['1']['status']), ('hit','miss'))
        self.assertTrue(rows['1']['exception'])
        matches[0]['prob'] = .97
        self.assertEqual(update_history(history, snapshot, {})['picks'][1]['prob'], .875)
        matches[0]['market'] = 'X2'
        alternate = update_history(history, snapshot, {'0': [2, 0]})
        self.assertEqual(next(pick['status'] for pick in alternate['picks'] if pick['id']=='0|X2'), 'miss')
        recovered = merge_picks(history['picks'], [dict(rows['0'],status='pending')])
        self.assertEqual({m['id']:m['status'] for m in recovered}, {'0':'hit','1':'miss'})

    def test_home_exception_checks_top_and_bottom_five(self):
        table = [dict(team=str(i)) for i in range(20)]
        self.assertTrue(home_exception(None,table,'4','15'))
        self.assertFalse(home_exception(None,table,'5','15'))
        self.assertFalse(home_exception(None,table,'4','14'))
        self.assertFalse(home_exception(None,table,'15','4'))


class QualificationTest(TestCase):
    def test_adjustment_keeps_probabilities_coherent(self):
        probs = np.array([.6,.25,.15])
        np.testing.assert_allclose(adjust_qualification(probs, ['qualified','open']), [.57,.265,.165])
        np.testing.assert_allclose(adjust_qualification(probs, ['qualified','qualified']), [.57,.2875,.1425])
        np.testing.assert_allclose(adjust_qualification(probs, ['open','open']), probs)


class CalibrationTest(TestCase):
    def test_competition_offsets_keep_coherent_outcomes_and_fallback(self):
        from model_benchmarks import ProbabilityCalibration

        forecasts = np.tile([.4,.3,.3], (200,1))
        codes = np.array(['home-heavy']*100+['away-heavy']*100)
        actual = np.array([0]*75+[1]*15+[2]*10+[0]*10+[1]*15+[2]*75)
        calibration = ProbabilityCalibration('competition').fit(forecasts,actual,codes)
        sample = np.tile([.4,.3,.3], (3,1))
        adjusted = calibration.predict(sample,np.array(['home-heavy','away-heavy','unseen']))
        np.testing.assert_allclose(adjusted.sum(axis=1), 1)
        self.assertGreater(adjusted[0,0], adjusted[2,0])
        self.assertGreater(adjusted[1,2], adjusted[2,2])
