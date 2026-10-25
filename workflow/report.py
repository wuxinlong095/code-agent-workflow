"""把一次运行的状态渲染成 Markdown 报告。"""
from __future__ import annotations

import difflib


def render(state, mermaid_graph: str, events: list[dict]) -> str:
    history = state.get("review_history") or []
    review = state.get("review") or {}
    messages = state.get("messages") or []
    original = state.get("code_v1") or ""
    final = state.get("code") or ""
    version = state.get("version") or 1
    remaining = list(review.get("issues") or [])
    out: list[str] = []

    out.append("# 代码审查工作流 · 执行报告\n")
    out.append("## 1. 基本信息\n")
    out.append("| 项 | 值 |")
    out.append("| --- | --- |")
    out.append(f"| 运行 ID | `{state.get('run_id') or '-'}` |")
    out.append(f"| 任务 | {state.get('task') or '-'} |")
    out.append(f"| 输入 | `{state.get('input_path') or '无（模板/LLM 生成）'}` |")
    out.append(f"| 迭代轮次 | {len(history)} |")
    out.append(f"| 最终判定 | **{review.get('verdict') or '未执行'}** |")
    out.append(f"| 代码版本 | v{version} |")
    out.append(f"| 路由说明 | {state.get('route_reason') or '-'} |")

    error = state.get("last_error")
    if error:
        out.append("\n## 2. 执行异常\n")
        out.append(f"- 出错节点：`{error.get('step')}`")
        out.append(f"- 错误信息：{error.get('error')}")
        out.append("- 处理方式：按 on_error 路由到报告节点，流程未中断归档")

    out.append("\n## 3. 工作流图\n")
    out.append("```mermaid")
    out.append(mermaid_graph)
    out.append("```")

    out.append("\n## 4. 迭代过程\n")
    out.append("| 轮次 | 问题数 | 可自动修复 | 判定 | 上一轮修复动作 |")
    out.append("| --- | --- | --- | --- | --- |")
    for item in history:
        issues = item.get("issues") or []
        fixable = len([i for i in issues if i.get("fixable")])
        fixed = item.get("auto_fixed") or []
        joined = "；".join(fixed) if fixed else "—"
        out.append(f"| {item.get('iteration')} | {len(issues)} | {fixable} | "
                   f"{item.get('verdict')} | {joined} |")
    if not history:
        out.append("| - | - | - | - | - |")

    out.append("\n## 5. 最终问题清单\n")
    if remaining:
        out.append("| 编号 | 行 | 级别 | 说明 | 可自动修复 |")
        out.append("| --- | --- | --- | --- | --- |")
        for issue in remaining:
            auto = "是" if issue.get("fixable") else "否"
            out.append(f"| {issue['code']} | {issue['line']} | {issue['severity']} | "
                       f"{issue['message']} | {auto} |")
    else:
        out.append("无遗留问题。")

    applied = state.get("last_fixed") or []
    skipped = state.get("fix_skipped") or []
    out.append("\n## 6. 修复动作\n")
    if applied:
        out.append("**已应用**\n")
        for item in applied:
            out.append(f"- {item}")
    else:
        out.append("**已应用**：无")
    if skipped:
        out.append("\n**跳过（需人工确认）**\n")
        for item in skipped:
            out.append(f"- {item}")

    diff = list(difflib.unified_diff(original.splitlines(), final.splitlines(),
                                     fromfile="v1", tofile=f"v{version}", lineterm=""))
    out.append("\n## 7. 代码差异（v1 → 最终版）\n")
    out.append("```diff")
    out.extend(diff if diff else ["（无变化）"])
    out.append("```")

    out.append("\n## 8. 最终代码\n")
    out.append("```python")
    out.append(final.rstrip() or "# （无）")
    out.append("```")

    out.append("\n## 9. Agent 消息记录\n")
    if messages:
        out.append("| # | 发送方 | 接收方 | 类型 | 摘要 |")
        out.append("| --- | --- | --- | --- | --- |")
        for message in messages:
            out.append(f"| {message['seq']} | {message['from']} | {message['to']} | "
                       f"{message['type']} | {message['summary']} |")
    else:
        out.append("（无消息）")

    steps = [event for event in events if event.get("event") == "step_end"]
    out.append("\n## 10. 执行统计\n")
    out.append(f"- 节点执行次数：{len(steps)}")
    total_ms = 0.0
    for event in steps:
        total_ms += float(event.get("ms") or 0)
        out.append(f"  - `{event.get('step')}`：{event.get('ms')} ms → 下一节点 "
                   f"`{event.get('next')}`")
    out.append(f"- 总耗时：{round(total_ms, 1)} ms")
    errors = [event for event in events if event.get("event") == "step_error"]
    if errors:
        out.append(f"- 错误事件：{len(errors)} 次（明细见 events.jsonl）")

    return "\n".join(out) + "\n"
