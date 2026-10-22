import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from streamreceipt.benchmark import benchmark, cases
from streamreceipt.core import MAX_BYTES, audit


class ReceiptTests(unittest.TestCase):
    def test_authored_protocol_corpus(self):
        result = benchmark()
        self.assertEqual(result["cases"], 13)
        self.assertEqual(result["streamreceipt_correct"], 13)
        self.assertLess(result["parse_only_correct"], result["streamreceipt_correct"])

    def test_safe_receipts_omit_tool_contents(self):
        for name, provider, transcript, expected in cases()[:2]:
            self.assertEqual(expected, "dispatch_allowed", name)
            output = json.dumps(audit(transcript, provider, require_usage=True))
            for sensitive in ("lookup", "call-1", "tool-1", '"item"', '"A"'):
                self.assertNotIn(sensitive, output)

    def test_missing_usage_policy_is_explicit(self):
        name, provider, transcript, _ = next(c for c in cases() if c[0] == "openai-no-usage")
        self.assertEqual(audit(transcript, provider)["verdict"], "dispatch_allowed", name)
        strict = audit(transcript, provider, require_usage=True)
        self.assertEqual(strict["verdict"], "inconclusive")
        self.assertIn("USAGE_UNOBSERVED", strict["findings"])

    def test_duplicate_tool_json_key_is_blocked(self):
        _, provider, transcript, _ = cases()[0]
        transcript = transcript.replace('\\"A\\"}', '\\"A\\",\\"item\\":\\"B\\"}')
        report = audit(transcript, provider)
        self.assertEqual(report["verdict"], "blocked")
        self.assertIn("DUPLICATE_JSON_KEY", report["findings"])

    def test_duplicate_terminal_is_blocked(self):
        _, provider, transcript, _ = cases()[0]
        report = audit(transcript + "data: [DONE]\n\n", provider)
        self.assertEqual(report["verdict"], "blocked")
        self.assertIn("EVENT_AFTER_DONE", report["findings"])

    def test_non_integer_anthropic_block_index_is_blocked(self):
        _, provider, transcript, _ = cases()[1]
        transcript = transcript.replace('"index":0,"delta"', '"index":[],"delta"', 1)
        report = audit(transcript, provider)
        self.assertEqual(report["verdict"], "blocked")
        self.assertIn("DELTA_OUTSIDE_BLOCK", report["findings"])

    def test_provider_error_is_blocked(self):
        _, provider, transcript, _ = cases()[1]
        transcript = transcript.replace(
            "event: message_stop\n", 'event: error\ndata: {"type":"error"}\n\n'
        )
        report = audit(transcript, provider)
        self.assertEqual(report["verdict"], "blocked")
        self.assertIn("PROVIDER_ERROR", report["findings"])

    def test_anthropic_cumulative_usage_deltas(self):
        _, provider, transcript, _ = cases()[1]
        interim = (
            "event: message_delta\n"
            'data: {"type":"message_delta","delta":{},"usage":{"output_tokens":2}}\n\n'
        )
        transcript = transcript.replace(
            "event: message_delta\n", interim + "event: message_delta\n"
        )
        report = audit(transcript, provider, require_usage=True)
        self.assertEqual(report["verdict"], "dispatch_allowed")
        self.assertTrue(report["usage_observed"])

    def test_invalid_sse_and_limit(self):
        self.assertEqual(audit("", "openai-chat")["findings"], ["EMPTY_STREAM"])
        oversized = audit("x" * (MAX_BYTES + 1), "openai-chat")
        self.assertEqual(oversized["verdict"], "blocked")
        self.assertEqual(oversized["findings"], ["TRANSCRIPT_LIMIT"])

    def test_cli_refuses_input_overwrite(self):
        _, provider, transcript, _ = cases()[0]
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "trace.sse"
            path.write_text(transcript, encoding="utf-8")
            run = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "streamreceipt",
                    "audit",
                    str(path),
                    "--provider",
                    provider,
                    "--json",
                    str(path),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(run.returncode, 0)
            self.assertEqual(path.read_text(encoding="utf-8"), transcript)


if __name__ == "__main__":
    unittest.main()
