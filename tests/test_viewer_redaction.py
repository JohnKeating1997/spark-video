from __future__ import annotations

import unittest

from scripts.build_viewer import (
    _extract_sent_prompt,
    _is_video_render_record,
    _sanitize_for_viewer,
)


class ViewerRedactionTests(unittest.TestCase):
    def test_signed_url_query_is_removed_from_nested_log_data(self) -> None:
        value = {
            "stdout_excerpt": (
                "saved https://example.com/result.wav?Expires=1&Signature=secret"
            ),
            "response": {
                "url": "https://example.com/video.mp4?x-oss-process=watermark"
            },
        }
        clean = _sanitize_for_viewer(value)
        self.assertNotIn("Signature=", str(clean))
        self.assertNotIn("x-oss-process", str(clean))
        self.assertIn("https://example.com/result.wav?<redacted>", str(clean))

    def test_sensitive_fields_are_redacted_without_hiding_prompt(self) -> None:
        value = {
            "accessKeyId": "key-value",
            "authorization": "Bearer secret",
            "request": {"prompt": "keep this exact prompt"},
        }
        clean = _sanitize_for_viewer(value)
        self.assertEqual(clean["accessKeyId"], "<redacted>")
        self.assertEqual(clean["authorization"], "<redacted>")
        self.assertEqual(clean["request"]["prompt"], "keep this exact prompt")

    def test_wan_provider_nested_command_exposes_sent_prompt(self) -> None:
        record = {
            "kind": "video_generate",
            "request": {
                "kind": "r2v",
                "cmd": [
                    "wan",
                    "omni2video",
                    "--model",
                    "wan3.0",
                    "--prompt",
                    "literal compiled prompt",
                ],
            },
        }
        self.assertTrue(_is_video_render_record(record))
        self.assertEqual(_extract_sent_prompt(record), "literal compiled prompt")


if __name__ == "__main__":
    unittest.main()
