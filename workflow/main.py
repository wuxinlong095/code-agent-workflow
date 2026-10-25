"""命令行入口。

  ./run.sh -m workflow.main demo
  ./run.sh -m workflow.main run --input samples/buggy_cart.py --max-iters 3
  ./run.sh -m workflow.main graph
  ./run.sh -m workflow.main resume --run-id 20261025-213000
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from . import flow, report
from .engine import CheckpointStore, State

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "runs"


def _execute(state: State, run_id: str, max_iters: int, use_llm: bool,
             start_at: str | None = None) -> int:
    store = CheckpointStore(RUNS)
    workflow, meta = flow.build_workflow(max_iters=max_iters, use_llm=use_llm)
    workflow.run_id = run_id
    try:
        workflow.run(state, store=store, start_at=start_at)
    except Exception as exc:  # 未配置 on_error 的致命错误
        print(f"[失败] 流程中断：{type(exc).__name__}: {exc}")
        print(f"       现场：{store.run_dir(run_id)}")
        return 1

    run_dir = store.run_dir(run_id)
    markdown = state.get("report_md") or report.render(state, meta["mermaid"], workflow.events)
    (run_dir / "report.md").write_text(markdown, encoding="utf-8")
    (run_dir / "final_code.py").write_text(state.get("code") or "", encoding="utf-8")
    (run_dir / "state.json").write_text(
        json.dumps(state.snapshot(), ensure_ascii=False, indent=2), encoding="utf-8")
    (run_dir / "events.jsonl").write_text(
        "\n".join(json.dumps(event, ensure_ascii=False) for event in workflow.events) + "\n",
        encoding="utf-8")

    review = state.get("review") or {}
    print(f"[完成] run_id = {run_id}")
    print(f"       迭代 {state.get('iteration') or 0} 轮，代码 v{state.get('version') or 1}，"
          f"判定 {review.get('verdict') or '未执行'}")
    print(f"       报告：{run_dir / 'report.md'}")
    print(f"       日志：{run_dir / 'events.jsonl'}")
    return 0


def _cmd_run(args) -> int:
    run_id = args.run_id or time.strftime("%Y%m%d-%H%M%S")
    state = State({"run_id": run_id, "task": args.task,
                   "input_path": args.input, "max_iters": args.max_iters})
    return _execute(state, run_id, args.max_iters, args.llm)


def _cmd_demo(args) -> int:
    sample = ROOT / "samples" / "buggy_cart.py"
    namespace = argparse.Namespace(
        task="审查并修复购物车模块中的典型缺陷（内置样例）",
        input=str(sample) if sample.exists() else None,
        max_iters=args.max_iters,
        llm=args.llm,
        run_id=None,
    )
    return _cmd_run(namespace)


def _cmd_resume(args) -> int:
    store = CheckpointStore(RUNS)
    snapshot = store.load(args.run_id)
    state = State.from_snapshot(snapshot["state"])
    nxt = snapshot.get("next")
    if not nxt or nxt == "__END__":
        print(f"运行 {args.run_id} 已结束，无需续跑")
        return 0
    print(f"[续跑] {args.run_id} 从节点 {nxt} 继续")
    return _execute(state, args.run_id, state.get("max_iters") or 3, False, start_at=nxt)


def _cmd_graph(args) -> int:
    workflow, meta = flow.build_workflow()
    print(meta["mermaid"])
    print("\n节点表：")
    for name, step in workflow.steps.items():
        reads = ",".join(step.reads) or "-"
        writes = ",".join(step.writes) or "-"
        print(f"  {name:<8} {step.kind:<7} 读:{reads:<20} 写:{writes:<26} 访问上限:{step.max_visits}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m workflow.main",
                                     description="多 Agent 代码审查工作流（MVP）")
    sub = parser.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run", help="执行一次工作流")
    run.add_argument("--task", default="审查并修复购物车模块中的典型缺陷")
    run.add_argument("--input", default=None, help="待审查的 .py 文件；省略则用模板或 LLM 生成")
    run.add_argument("--max-iters", type=int, default=3, help="修复-复检循环最大轮数")
    run.add_argument("--llm", action="store_true", help="编码节点改用 OpenAI 兼容接口")
    run.add_argument("--run-id", default=None)
    run.set_defaults(func=_cmd_run)

    demo = sub.add_parser("demo", help="用内置样例跑一遍完整流程")
    demo.add_argument("--max-iters", type=int, default=3)
    demo.add_argument("--llm", action="store_true")
    demo.set_defaults(func=_cmd_demo)

    graph = sub.add_parser("graph", help="打印工作流图和节点表")
    graph.set_defaults(func=_cmd_graph)

    resume = sub.add_parser("resume", help="从检查点续跑")
    resume.add_argument("--run-id", required=True)
    resume.set_defaults(func=_cmd_resume)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
