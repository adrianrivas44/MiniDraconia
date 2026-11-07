"""D2 additions to the engine: an old peek timer never cuts a clip that started meanwhile."""
import random
import unittest
from unittest.mock import patch


class PeekEndNeverCutsAnotherClip(unittest.TestCase):
    def ticker(self, ctx):
        from DyberPet.mia_director import MiaMicroTicker
        self.played, self.now = [], [100.0]
        return MiaMicroTicker(get_context=lambda: dict(ctx), play_action=self.played.append,
                              apply_cursor_flip=lambda mirror: None, on_edge=lambda side: None,
                              now_fn=lambda: self.now[0], rng=random.Random(1),
                              climb_cfg={'enabled': False})

    def start_peek(self, ticker, ctx):
        with patch('DyberPet.mia_director.decide_edge_action', return_value='peek'):
            ctx.update(at_edge='right', state='default')
            ticker.tick()
        self.assertTrue(self.played and self.played[-1].startswith('peek'), self.played)
        return self.played[-1]

    def test_still_peeking_she_goes_back_to_her_stand(self):
        ctx = {'state': 'default', 'available_poses': {'peek', 'default'}}
        ticker = self.ticker(ctx)
        pose = self.start_peek(ticker, ctx)
        ctx.update(at_edge='right', state='animat', act_name=pose)
        self.now[0] += 30
        ticker.tick()
        self.assertEqual(self.played[-1], 'default')

    def test_a_walk_started_during_the_peek_is_not_cut(self):
        ctx = {'state': 'default', 'available_poses': {'peek', 'default', 'left_walk'}}
        ticker = self.ticker(ctx)
        self.start_peek(ticker, ctx)
        before = list(self.played)
        ctx.update(at_edge=None, state='animat', act_name='left_walk')
        self.now[0] += 30
        ticker.tick()
        self.assertEqual(self.played, before, 'the old peek timer played over the walk')


if __name__ == '__main__':
    unittest.main()
