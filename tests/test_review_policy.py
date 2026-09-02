from __future__ import annotations

import json
import unittest

from lib.review import AXES, _decide_verdict, parse_omni_output


class ReviewPolicyTests(unittest.TestCase):
    def _payload(self) -> dict:
        return {
            **{axis: 9 for axis in AXES},
            "blocking_issues": [],
            "critique": "",
            "verdict": "ACCEPT",
        }

    def test_parser_requires_blocking_issues_field(self) -> None:
        payload = self._payload()
        payload.pop("blocking_issues")
        self.assertIsNone(parse_omni_output(json.dumps(payload)))

    def test_blocking_issue_forces_reject_above_threshold(self) -> None:
        payload = self._payload()
        payload["blocking_issues"] = [{
            "type": "malformed_text",
            "timestamp": "0:02",
            "detail": "Generated caption is nonsensical.",
        }]
        parsed = parse_omni_output(json.dumps(payload))
        self.assertIsNotNone(parsed)
        verdict, vetoed, score = _decide_verdict(
            parsed["breakdown"],
            parsed["blocking_issues"],
            threshold_value=7.0,
            veto_floor=5.0,
        )
        self.assertEqual(score, 9.0)
        self.assertEqual(vetoed, [])
        self.assertEqual(verdict, "REJECT")

    def test_clean_high_scores_accept(self) -> None:
        parsed = parse_omni_output(json.dumps(self._payload()))
        verdict, vetoed, score = _decide_verdict(
            parsed["breakdown"],
            parsed["blocking_issues"],
            threshold_value=7.0,
            veto_floor=5.0,
        )
        self.assertEqual((verdict, vetoed, score), ("ACCEPT", [], 9.0))


if __name__ == "__main__":
    unittest.main()
