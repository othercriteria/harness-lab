"""Check potential residency savings against a hand-calculated job timeline."""

import sys
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from analyze_worker_residency import opportunity, price

START = datetime(2026, 1, 1, tzinfo=UTC)


def row(job_id, submitted, completed, load):
    dispatch = completed - submitted
    return {
        "id": job_id,
        "session": "one-session",
        "server_key": "same-server",
        "submitted": (START + timedelta(seconds=submitted)).isoformat(),
        "completed": (START + timedelta(seconds=completed)).isoformat(),
        "dispatch": dispatch,
        "load": load,
        "cleanup_verified": True,
        "other_model_displaced": False,
        "seconds": {"load_to_ready": load, "other_dispatch": dispatch - load},
    }


def abc():
    return [row("A", 0, 12, 4), row("B", 14, 17, 1), row("C", 20, 29, 2)]


def link_ids(links):
    return [(a["id"], b["id"], gap) for a, b, gap in links]


class OpportunityTest(unittest.TestCase):
    def test_two_adjacent_links(self):
        self.assertEqual(
            link_ids(opportunity(abc(), [], 10)), [("A", "B", 2), ("B", "C", 3)]
        )

    def test_link_gaps_are_absolute_epoch_differences(self):
        a, b, _ = abc()
        b["submitted"] = "2026-01-01T02:00:14+02:00"
        self.assertEqual(link_ids(opportunity([a, b], [], 10)), [("A", "B", 2)])

    def test_gap_exactly_at_limit_and_one_second_over(self):
        # A to B hits the two-second limit exactly. B to C takes three seconds.
        self.assertEqual(link_ids(opportunity(abc(), [], 2)), [("A", "B", 2)])

    def test_ineligible_middle_job_still_separates_neighbors(self):
        # A to C would fit the limit (8 s). None of these changes permits skipping B.
        for field, value in (
            ("session", "other"),
            ("server_key", "other"),
            ("cleanup_verified", False),
        ):
            with self.subTest(field=field):
                rows = abc()
                rows[1][field] = value
                self.assertEqual(opportunity(rows, [], 10), [])

        rows = abc()
        del rows[1]["seconds"]
        self.assertEqual(opportunity(rows, [], 10), [])

    def test_other_campaign_start_breaks_only_the_occupied_gap(self):
        # The A-to-B gap spans seconds 12 through 14, including both endpoints.
        for second in (12, 13, 14):
            with self.subTest(second=second):
                links = opportunity(abc(), [START.timestamp() + second], 10)
                self.assertEqual(link_ids(links), [("B", "C", 3)])

    def test_other_campaign_start_outside_gaps_keeps_both_links(self):
        links = opportunity(abc(), [START.timestamp() + 16], 10)
        self.assertEqual(link_ids(links), [("A", "B", 2), ("B", "C", 3)])

    def test_overlapping_job_drops_only_the_negative_gap_link(self):
        a, _, c = abc()
        links = opportunity([a, row("B", 11, 17, 1), c], [], 10)
        self.assertEqual(link_ids(links), [("B", "C", 3)])


class PriceTest(unittest.TestCase):
    def test_price_of_two_links(self):
        # Dispatch: A + B + C = 12 + 3 + 9. Potential avoided loads: B + C = 1 + 2.
        self.assertEqual(
            price(opportunity(abc(), [], 10)),
            {
                "links": 2,
                "sessions": 1,
                "batches": 1,
                "jobs_in_batches": 3,
                "dispatch_seconds_in_batches": 24,
                "later_load_seconds": 3,
                "inter_job_gap_seconds": 5,
                "links_with_displacement_on_either_job": 0,
            },
        )

    def test_price_of_two_separate_batches_in_one_session(self):
        # Both runs of adjacent jobs qualify. The long gap between B and C does not.
        a, b, _ = abc()
        c = row("C", 30, 39, 2)
        d = row("D", 40, 44, 3)
        links = opportunity([a, b, c, d], [], 10)
        self.assertEqual(link_ids(links), [("A", "B", 2), ("C", "D", 1)])
        result = price(links)
        self.assertEqual((result["sessions"], result["batches"]), (1, 2))
        self.assertEqual(result["later_load_seconds"], 4)

    def test_price_of_single_link(self):
        a, b, _ = abc()
        result = price([(a, b, 2)])
        self.assertEqual(result["jobs_in_batches"], 2)
        self.assertEqual(result["dispatch_seconds_in_batches"], 15)
        self.assertEqual(result["later_load_seconds"], 1)

    def test_price_counts_displacement_on_either_job(self):
        a, b, c = abc()
        b["other_model_displaced"] = True
        self.assertEqual(
            price([(a, b, 2), (b, c, 3)])["links_with_displacement_on_either_job"], 2
        )

    def test_price_of_empty_links(self):
        self.assertEqual(
            price([]),
            {
                "links": 0,
                "sessions": 0,
                "batches": 0,
                "jobs_in_batches": 0,
                "dispatch_seconds_in_batches": 0,
                "later_load_seconds": 0,
                "inter_job_gap_seconds": 0,
                "links_with_displacement_on_either_job": 0,
            },
        )


if __name__ == "__main__":
    unittest.main()
