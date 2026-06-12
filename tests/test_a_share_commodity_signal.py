import sys
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from a_share_commodity_signal import commodity_signal_score, material_move, rank_commodity_moves


class CommoditySignalRankingTests(unittest.TestCase):
    def test_directional_return_beats_large_reversal_amplitude(self):
        trending_coal = {
            'name': '焦煤连续',
            'window_chg': -4.0,
            'window_amp': 4.2,
            'close_position': 0.08,
            'report_type': 'evening',
        }
        noisy_silver = {
            'name': '白银连续',
            'window_chg': 0.2,
            'window_amp': 7.0,
            'close_position': 0.52,
            'report_type': 'evening',
        }

        self.assertGreater(commodity_signal_score(trending_coal), commodity_signal_score(noisy_silver))

    def test_historical_percentile_boosts_self_significant_move(self):
        zinc = {
            'name': '沪锌连续',
            'window_chg': 1.2,
            'window_amp': 1.4,
            'abs_return_percentile': 0.96,
            'report_type': 'morning',
        }
        copper = {
            'name': '铜连续',
            'window_chg': 1.2,
            'window_amp': 1.4,
            'abs_return_percentile': 0.55,
            'report_type': 'morning',
        }

        self.assertGreater(commodity_signal_score(zinc), commodity_signal_score(copper))

    def test_material_move_uses_directional_return_not_amplitude_only(self):
        self.assertTrue(material_move({'name': '焦煤连续', 'window_chg': -0.8, 'window_amp': 0.9}))
        self.assertFalse(material_move({'name': '白银连续', 'window_chg': 0.1, 'window_amp': 2.5, 'close_position': 0.5}))

    def test_rank_keeps_core_first_but_uses_signal_score_inside_pool(self):
        moves = [
            {'name': '甲醇连续', 'window_chg': 1.0, 'window_amp': 1.1, 'abs_return_percentile': 0.75},
            {'name': '焦煤连续', 'window_chg': -4.0, 'window_amp': 4.2, 'abs_return_percentile': 0.97, 'close_position': 0.08},
            {'name': '白银连续', 'window_chg': 4.5, 'window_amp': 5.0, 'abs_return_percentile': 0.98, 'close_position': 0.95},
        ]

        ranked = rank_commodity_moves(moves, core_limit=2, expanded_limit=1)

        self.assertEqual([x['name'] for x in ranked], ['焦煤连续', '甲醇连续', '白银连续'])


if __name__ == '__main__':
    unittest.main()
