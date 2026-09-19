from pathlib import Path

root = Path.cwd()
test = root / "scripts/test_local_phone_llm_live_call.py"
test.write_text(r'''import unittest

from local_phone_llm_live_call import (
    ORANGE_SUPPORT_NUMBER,
    build_probe_start_args,
    normalize_allowlisted_target,
    parse_probe_report,
)


class LocalPhoneLlmLiveCallTest(unittest.TestCase):
    def test_orange_support_is_the_only_initial_allowlisted_target(self):
        self.assertEqual("510100100", ORANGE_SUPPORT_NUMBER)
        self.assertEqual("510100100", normalize_allowlisted_target("510 100 100"))
        with self.assertRaises(ValueError):
            normalize_allowlisted_target("501234567")
        with self.assertRaises(ValueError):
            normalize_allowlisted_target("112")

    def test_probe_args_are_fixed_to_local_phone_live_probe(self):
        args = build_probe_start_args("RFCT70L7E8J")
        joined = " ".join(args)
        self.assertIn("run_local_phone_llm_live_call_probe", joined)
        self.assertNotIn(ORANGE_SUPPORT_NUMBER, joined)

    def test_report_parser_requires_terminal_marker(self):
        self.assertIsNone(parse_probe_report("stt_text=test\n"))
        report = parse_probe_report(
            "stt_text=witaj\\napproved_text=dzień dobry\\n"
            "local_phone_llm_live_call_success=true\\nprobe_complete=true\\n"
        )
        self.assertIsNotNone(report)
        self.assertEqual("witaj", report["stt_text"])
        self.assertEqual("dzień dobry", report["approved_text"])
        self.assertEqual("true", report["local_phone_llm_live_call_success"])


if __name__ == "__main__":
    unittest.main()
''')
print("local_phone_live_red_tests_written=true")
