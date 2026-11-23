"""Verify that scoreboard ingestion preserves published fixture identities."""
import unittest
from scoreboard_data import normalize_events

class ScoreboardTests(unittest.TestCase):
    def payload(self,completed,state):
        return dict(events=[dict(id='123',date='2026-11-22T20:00Z',competitions=[dict(
            status=dict(type=dict(completed=completed,state=state)),
            competitors=[
                dict(homeAway='home',score='2',team=dict(displayName='Internazionale')),
                dict(homeAway='away',score='1',team=dict(displayName='AS Roma'))])])])

    def known(self):
        return [dict(id='it.1|2026-27|2026-11-22|FC Internazionale Milano|AS Roma',
                     day='2026-11-22',home='FC Internazionale Milano',away='AS Roma')]

    def test_completed_score_keeps_archive_identity(self):
        rows=normalize_events(self.payload(True,'post'),'it.1','2026-27',self.known())
        self.assertEqual(rows[0]['id'],self.known()[0]['id'])
        self.assertEqual(rows[0]['score'],[2,1])

    def test_live_and_unconfirmed_scores_are_not_final(self):
        for completed,state in [(False,'in'),(False,'post'),(False,'pre')]:
            rows=normalize_events(self.payload(completed,state),'it.1','2026-27',self.known())
            self.assertIsNone(rows[0]['score'])

    def test_conflicting_known_opponents_are_rejected(self):
        known=self.known()+[dict(day='2026-11-22',home='AC Milan',away='Juventus FC')]
        payload=self.payload(True,'post')
        payload['events'][0]['competitions'][0]['competitors'][1]['team']['displayName']='Juventus'
        self.assertEqual(normalize_events(payload,'it.1','2026-27',known),[])

    def test_rescheduled_archive_uses_final_fixture_and_original_probability(self):
        from history import update_history
        original='en.1|2026-27|2026-11-21|Home|Away'
        actual='en.1|2026-27|2026-11-22|Home|Away'
        pick=dict(id=original,day='2026-11-21',home='Home',away='Away',
                  league='en.1',market='1X',prob=.88,publishedAt='2026-11-20T12:00:00+00:00',status='pending',score=None)
        snapshot=dict(updated='2026-11-23T12:00:00+00:00',leagues=[],matches=[])
        row=update_history({'picks':[pick]},snapshot,{actual:[2,0]})['picks'][0]
        self.assertEqual(row['status'],'hit')
        self.assertEqual(row['prob'],.88)
        self.assertEqual(row['day'],'2026-11-22')
        self.assertEqual(row['originalDay'],'2026-11-21')
        self.assertEqual(row['fixtureId'],actual)

    def test_extra_time_score_does_not_settle_a_90_minute_market(self):
        payload=self.payload(True,'post')
        payload['events'][0]['competitions'][0]['status']['period']=4
        rows=normalize_events(payload,'it.1','2026-27',self.known())
        self.assertIsNone(rows[0]['score'])

    def test_a_different_known_opponent_is_not_inferred_as_an_alias(self):
        known=self.known()+[dict(day='2026-11-15',home='AC Milan',away='Juventus FC')]
        payload=self.payload(True,'post')
        payload['events'][0]['competitions'][0]['competitors'][1]['team']['displayName']='Juventus'
        self.assertEqual(normalize_events(payload,'it.1','2026-27',known),[])
