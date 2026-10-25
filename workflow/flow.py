"""把 Agent 组装成工作流：load -> 编码 -> 审查 -> 路由 -> 修复(回路) -> 报告。"""
from __future__ import annotations

from pathlib import Path

from . import report
from .agents import CoderAgent, FixerAgent, ReviewerAgent
from .engine import State, Step, Workflow
from .llm import LLMClient

EDGES = [
    ("load", "code", "初稿/任务"),
    ("code", "review", "代码 v1"),
    ("review", "route", "审查报告"),
    ("route", "fix", "有可自动修复问题且未超轮数"),
    ("route", "report", "通过 / 仅剩人工项 / 语法错误"),
    ("fix", "review", "修复后复检"),
]


def to_mermaid() -> str:
    lines = ["flowchart TD"]
    for src, dst, label in EDGES:
        lines.append(f"    {src} -->|{label}| {dst}")
    lines.append("    report --> done([结束])")
    return "\n".join(lines)


def route(state: State) -> str:
    """路由节点：决定继续修复还是收尾出报告。"""
    review = state.get("review") or {}
    iteration = state.get("iteration") or 0
    max_iters = state.get("max_iters") or 3

    if not review.get("ok", False):
        state.set("route_reason", "语法检查未通过，跳过修复直接出报告（需人工介入）", source="route")
        return "report"

    fixable = [item for item in review.get("issues", []) if item.get("fixable")]
    if fixable and iteration < max_iters:
        state.set("route_reason",
                  f"第 {iteration} 轮仍有 {len(fixable)} 个可自动修复问题，进入修复节点",
                  source="route")
        return "fix"

    state.set("route_reason", "没有可自动修复的问题（或已达迭代上限），输出报告", source="route")
    return "report"


def build_workflow(max_iters: int = 3, use_llm: bool = False) -> tuple[Workflow, dict]:
    coder = CoderAgent(LLMClient() if use_llm else None)
    reviewer = ReviewerAgent()
    fixer = FixerAgent()

    def load(state: State) -> str:
        path = state.get("input_path")
        if path:
            file = Path(path)
            if not file.exists():
                raise FileNotFoundError(f"输入文件不存在：{path}")
            state.update({"source_code": file.read_text(encoding="utf-8"),
                          "input_name": file.name}, source="load")
        else:
            state.set("source_code", None, source="load")
        return "code"

    def finish(state: State) -> None:
        state.update({"report_md": report.render(state, to_mermaid(), workflow.events),
                      "finished": True}, source="report")
        return None

    workflow = Workflow("code-review", start="load")
    workflow.add(Step("load", load, kind="tool", writes=("source_code",), on_error="report"))
    workflow.add(Step("code", coder.run, kind="agent", reads=coder.reads,
                      writes=coder.writes, retries=1, on_error="report"))
    workflow.add(Step("review", reviewer.run, kind="agent", reads=reviewer.reads,
                      writes=reviewer.writes, max_visits=max_iters + 1,
                      retries=1, on_error="report"))
    workflow.add(Step("route", route, kind="router", max_visits=max_iters + 1))
    workflow.add(Step("fix", fixer.run, kind="agent", reads=fixer.reads,
                      writes=fixer.writes, max_visits=max_iters,
                      retries=1, on_error="report"))
    workflow.add(Step("report", finish, kind="tool"))
    return workflow, {"mermaid": to_mermaid(), "max_iters": max_iters}
