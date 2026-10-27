"""Slice A: tools/eval-report.py scores only the graders that count, in each
arm, and treats a case whose graders are all with-only as a signal."""

import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from helpers import ROOT

spec = importlib.util.spec_from_file_location("eval_report", ROOT / "tools" / "eval-report.py")
report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(report)


def grader(name, passed, flagged=False):
    return {"name": name, "passed": passed, "weight": 1, "withOnly": flagged, "scored": True}


def case(name, graders_cfg, with_runs, without_runs):
    return {"name": name, "graders": graders_cfg,
            "arms": {"with": [{"score": 1, "graders": g} for g in with_runs],
                     "without": [{"score": 0, "graders": g} for g in without_runs]}}


DISPATCH = {"name": "used-implementer", "config": {"arm": "with-only"}}
OUTCOME = {"name": "tests-pass", "config": {}}


class EvalReportTests(unittest.TestCase):
    def test_with_only_graders_never_count(self):
        c = case("impl", [DISPATCH, OUTCOME],
                 [[grader("used-implementer", True), grader("tests-pass", False)]],
                 [[grader("used-implementer", False), grader("tests-pass", True)]])
        # The CLI's own scores (1 and 0) would credit the dispatch check.
        self.assertEqual((report.arm_score(c, "with"), report.arm_score(c, "without")), (0.0, 1.0))

    def test_a_case_of_only_signals_has_no_score(self):
        c = case("rm", [DISPATCH], [[grader("used-implementer", True)]], [[grader("used-implementer", False)]])
        self.assertIsNone(report.arm_score(c, "with"))
        path = Path(tempfile.mkdtemp()) / "run.json"
        path.write_text(json.dumps({"costUsd": 0.1, "cases": [c]}))
        out = io.StringIO()
        with redirect_stdout(out):
            report.ablation([str(path)])
        self.assertIn("signal only", out.getvalue())
        self.assertIn("used-implementer *", out.getvalue())

    def report_of(self, *runs_files):
        folder = Path(tempfile.mkdtemp())
        paths = []
        for i, data in enumerate(runs_files):
            (folder / f"{i}.json").write_text(json.dumps(data))
            paths.append(str(folder / f"{i}.json"))
        out = io.StringIO()
        with redirect_stdout(out):
            report.ablation(paths)
        return out.getvalue()

    def test_errored_and_cost_capped_runs_are_left_out_and_named(self):
        c = case("impl", [OUTCOME], [[grader("tests-pass", True)], []], [[grader("tests-pass", False)]])
        c["arms"]["with"][1].update(error="timeout")
        c["arms"]["without"].append({"score": 0, "skippedPaidGraders": True, "graders": [grader("tests-pass", False)]})
        self.assertEqual((report.arm_score(c, "with"), report.arm_score(c, "without")), (1.0, 0.0))
        text = self.report_of({"costUsd": 1, "partial": True, "cases": [c]})
        self.assertIn("is partial", text)
        self.assertIn("impl (with): 1 run(s) left out: error", text)
        self.assertIn("impl (without): 1 run(s) left out: cost cap", text)

    def test_the_mean_pairs_cases_that_have_both_arms(self):
        both = case("both", [OUTCOME], [[grader("tests-pass", False)]], [[grader("tests-pass", False)]])
        only_with = case("only-with", [OUTCOME], [[grader("tests-pass", True)]], [])
        text = self.report_of({"cases": [both, only_with]})
        self.assertIn("mean, 1 cases with both", text)
        self.assertIn("+0.00", text.split("mean, 1 cases with both")[1].splitlines()[0])

    def test_a_flag_in_the_results_also_marks_a_grader(self):
        c = case("x", [OUTCOME], [[grader("tests-pass", True, flagged=True)]], [[grader("tests-pass", False)]])
        self.assertEqual(report.with_only(c), {"tests-pass"})


if __name__ == "__main__":
    unittest.main()
