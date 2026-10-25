"""单元测试：引擎控制流 + 审查/修复规则 + 端到端流程。

运行：./run.sh -m unittest discover -s tests -v
"""
import tempfile
import unittest
from pathlib import Path

from workflow import flow
from workflow.agents import apply_fixes, review_code
from workflow.engine import END, CheckpointStore, State, Step, Workflow

SAMPLE = Path(__file__).resolve().parents[1] / "samples" / "buggy_cart.py"


class EngineTests(unittest.TestCase):
    def test_sequence(self):
        wf = Workflow("seq", "a")
        wf.add(Step("a", lambda s: "b"))
        wf.add(Step("b", lambda s: END))
        wf.run(State())
        steps = [e["step"] for e in wf.events if e["event"] == "step_end"]
        self.assertEqual(steps, ["a", "b"])

    def test_branch(self):
        def router(state):
            return "yes" if state.get("flag") else "no"

        wf = Workflow("branch", "r")
        wf.add(Step("r", router, kind="router"))
        wf.add(Step("yes", lambda s: END))
        wf.add(Step("no", lambda s: END))
        wf.run(State({"flag": True}))
        steps = [e["step"] for e in wf.events if e["event"] == "step_end"]
        self.assertEqual(steps, ["r", "yes"])

    def test_loop_limit(self):
        def again(state):
            state.set("n", (state.get("n") or 0) + 1)
            return "again"

        wf = Workflow("loop", "again")
        wf.add(Step("again", again, max_visits=3))
        with self.assertRaises(RuntimeError):
            wf.run(State())

    def test_retry(self):
        counter = {"n": 0}

        def flaky(state):
            counter["n"] += 1
            if counter["n"] < 2:
                raise RuntimeError("boom")
            return "ok"

        wf = Workflow("retry", "flaky")
        wf.add(Step("flaky", flaky, retries=1))
        wf.add(Step("ok", lambda s: END))
        wf.run(State())
        self.assertEqual(counter["n"], 2)

    def test_checkpoint_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = CheckpointStore(tmp)
            wf = Workflow("cp", "a")
            wf.add(Step("a", lambda s: END))
            wf.run_id = "r1"
            wf.run(State({"x": 1}), store=store)
            snapshot = store.load("r1")
            self.assertEqual(snapshot["state"]["data"]["x"], 1)
            self.assertEqual(State.from_snapshot(snapshot["state"]).get("x"), 1)


class ReviewerTests(unittest.TestCase):
    def test_detects_sample_issues(self):
        code = SAMPLE.read_text(encoding="utf-8")
        result = review_code(code)
        codes = {item["code"] for item in result["issues"]}
        self.assertTrue({"E101", "E102", "E103", "E105"} <= codes)
        self.assertEqual(result["verdict"], "reject")

    def test_syntax_error_blocked(self):
        result = review_code("def f(:\n    pass\n")
        self.assertFalse(result["ok"])
        self.assertEqual(result["verdict"], "blocked")

    def test_fixer_removes_auto_fixable(self):
        code = SAMPLE.read_text(encoding="utf-8")
        issues = [i for i in review_code(code)["issues"] if i["fixable"]]
        fixed, applied, _ = apply_fixes(code, issues)
        self.assertGreaterEqual(len(applied), 3)
        left = [i for i in review_code(fixed)["issues"] if i["fixable"]]
        self.assertEqual(left, [])
        self.assertIn("is not None", fixed)
        self.assertIn("except Exception:", fixed)
        self.assertNotIn("import os", fixed)


class PipelineTests(unittest.TestCase):
    def test_end_to_end(self):
        wf, _ = flow.build_workflow(max_iters=3)
        state = State({"task": "审查购物车", "input_path": str(SAMPLE), "max_iters": 3})
        wf.run(state)
        self.assertTrue(state.get("finished"))
        self.assertEqual(state.get("version"), 2)
        self.assertEqual(state.get("iteration"), 2)
        markdown = state.get("report_md") or ""
        self.assertIn("执行报告", markdown)
        self.assertIn("flowchart", markdown)


if __name__ == "__main__":
    unittest.main()
