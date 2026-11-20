"""Decision information boundaries and missing counterfactuals in the #21 replay."""

import unittest

from scripts.backtest_dispatch import backtest, read


def codec_campaigns():
    return [
        c
        for c in read("dispatch-backtest-inputs-001.json")["campaigns"]
        if c["family"] == "codec"
    ]


class DispatchReplayTests(unittest.TestCase):
    def test_test_outcomes_affect_scores_only(self):
        campaigns = codec_campaigns()
        before = backtest(campaigns, "rana")["decisions"]
        for campaign in campaigns:
            for trial in campaign["trials"]:
                if trial["stage"] == "test" and campaign["arm"] == "rana":
                    trial.update(seconds=1000, accepted=False)
        after = backtest(campaigns, "rana")["decisions"]
        self.assertEqual([r["chosen"] for r in before], [r["chosen"] for r in after])
        (old,) = [
            r for r in before if r["resident"] == "coder" and r["scenario"] == "free"
        ]
        (new,) = [
            r for r in after if r["resident"] == "coder" and r["scenario"] == "free"
        ]
        self.assertEqual((new["chosen_full"], new["baseline_full"]), (0, 4))
        self.assertLess(new["paired_saving_s"], old["paired_saving_s"])

    def test_missing_finalist_is_unscored(self):
        rows = backtest(codec_campaigns(), "rana")["decisions"]
        for row in rows:
            if row["resident"] in {"layout", "flint"}:
                self.assertEqual(row["score"], "missing paired outcomes")
                self.assertNotIn("paired_saving_s", row)
