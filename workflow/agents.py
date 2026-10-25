"""三个 Agent 节点：编码、审查、修复。

设计约定：
- Agent 只通过共享 State 交换数据，彼此不 import，方便单独替换/新增；
- 每次交接调用 say() 往 state["messages"] 写一条消息，形成可追踪的通信记录；
- 审查与修复为确定性规则实现，离线可复现、可单元测试；
  编码节点在配置 OPENAI_API_KEY 后可切换为真实 LLM。
"""
from __future__ import annotations

import ast
import re

from .llm import LLMClient, extract_code

LONG_LINE = 100

TEMPLATE = '''"""购物车工具（离线模板生成，故意保留典型问题，供审查流程演示）。"""
import os


def total_price(items, discount=0.0):
    """计算总价：单价 * 数量求和后按折扣减免。"""
    s = 0
    for it in items:
        s = s + it["price"] * it["qty"]
    if discount != None:
        s = s * (1 - discount)
    return s


def load_cart(path):
    data = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = f.read().splitlines()
    except:
        data = []
    return data
'''


class Agent:
    name = "agent"
    reads: tuple[str, ...] = ()
    writes: tuple[str, ...] = ()

    def run(self, state) -> str | None:
        raise NotImplementedError

    def say(self, state, to: str, kind: str, summary: str, **payload) -> None:
        messages = list(state.get("messages") or [])
        messages.append({
            "seq": len(messages) + 1,
            "from": self.name,
            "to": to,
            "type": kind,
            "summary": summary,
            "payload": payload,
        })
        state.set("messages", messages, source=self.name)


def unused_imports(tree: ast.AST):
    """产出 (import 节点, 未使用的本地名列表)。"""
    used = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    found = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if isinstance(node, ast.ImportFrom) and node.module == "__future__":
                continue
            locals_ = [alias.asname or alias.name.split(".")[0] for alias in node.names]
            bad = [name for name in locals_ if name not in used]
            if bad:
                found.append((node, bad))
    return found


def review_code(code: str) -> dict:
    """静态审查：返回 {ok, syntax_error, issues, verdict}。"""
    issues: list[dict] = []

    def add(rule: str, line: int, message: str, severity: str, fixable: bool) -> None:
        issues.append({"code": rule, "line": line, "message": message,
                       "severity": severity, "fixable": fixable})

    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return {"ok": False,
                "syntax_error": {"line": exc.lineno, "message": exc.msg},
                "issues": [], "verdict": "blocked"}

    missing_doc: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler) and node.type is None:
            add("E103", node.lineno, "裸 except 会吞掉所有异常（包括 Ctrl+C）", "error", True)
        elif isinstance(node, ast.Compare):
            for operator, comparator in zip(node.ops, node.comparators):
                if (isinstance(comparator, ast.Constant) and comparator.value is None
                        and isinstance(operator, (ast.Eq, ast.NotEq))):
                    add("E101", node.lineno, "与 None 比较应使用 is / is not", "error", True)
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in {"eval", "exec"}:
                add("E107", node.lineno, f"使用 {func.id}()，存在代码注入风险，需人工改造",
                    "error", False)
            if isinstance(func, ast.Name) and func.id == "print":
                add("W203", node.lineno, "残留 print，请确认是否为调试输出", "warning", False)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for default in node.args.defaults:
                if isinstance(default, (ast.List, ast.Dict, ast.Set)):
                    add("E102", node.lineno,
                        f"函数 {node.name} 使用可变默认参数，会在多次调用间共享", "error", False)
            if ast.get_docstring(node) is None:
                missing_doc.append((node.lineno, node.name))

    for line, name in missing_doc[:3]:
        add("W202", line, f"函数 {name} 缺少文档字符串", "info", False)

    for node, bad in unused_imports(tree):
        add("E105", node.lineno, f"未使用的导入：{', '.join(bad)}", "warning", True)

    long_lines = [(index, len(text)) for index, text in enumerate(code.splitlines(), 1)
                  if len(text) > LONG_LINE]
    for line, length in long_lines[:3]:
        add("W201", line, f"代码行长度 {length} 超过 {LONG_LINE} 字符", "warning", False)

    issues.sort(key=lambda item: (item["line"], item["code"]))
    errors = [item for item in issues if item["severity"] == "error"]
    verdict = "reject" if errors else ("revise" if issues else "pass")
    return {"ok": True, "syntax_error": None, "issues": issues, "verdict": verdict}


def apply_fixes(code: str, issues: list[dict]) -> tuple[str, list[str], list[str]]:
    """只处理 fixable 的问题；改完校验语法与修复效果，失败则整体回退。"""
    rules = {item["code"] for item in issues}
    applied: list[str] = []
    skipped: list[str] = []
    text = code

    if "E105" in rules:
        try:
            tree = ast.parse(text)
        except SyntaxError:
            tree = None
        if tree is not None:
            lines = text.splitlines()
            drop: set[int] = set()
            for node, bad in unused_imports(tree):
                if len(bad) == len(node.names):
                    for line_no in range(node.lineno, (node.end_lineno or node.lineno) + 1):
                        drop.add(line_no)
                    applied.append(f"E105 第 {node.lineno} 行：删除未使用导入 {', '.join(bad)}")
                else:
                    skipped.append(f"E105 第 {node.lineno} 行：导入语句内混用，需人工确认")
            if drop:
                text = "\n".join(line for index, line in enumerate(lines, 1)
                                 if index not in drop) + "\n"

    if "E101" in rules:
        new_text = re.sub(r"==\s*None\b", "is None", text)
        new_text = re.sub(r"!=\s*None\b", "is not None", new_text)
        if new_text != text:
            applied.append("E101 将 == None / != None 改写为 is / is not")
            text = new_text

    if "E103" in rules:
        new_text = re.sub(r"(?m)^(\s*)except\s*:", r"\1except Exception:", text)
        if new_text != text:
            applied.append("E103 裸 except 改写为 except Exception")
            text = new_text

    try:
        ast.parse(text)
    except SyntaxError as exc:
        return code, [], skipped + [f"修复后语法错误（第 {exc.lineno} 行），已回退原代码"]

    left = {item["code"] for item in review_code(text)["issues"] if item["fixable"]}
    still = sorted(rules & left)
    if still:
        skipped.append(f"以下问题未被消除：{', '.join(still)}")
    return text, applied, skipped


class CoderAgent(Agent):
    """编码 Agent：拿到任务/初稿，产出版本 v1 代码。"""

    name = "coder"
    reads = ("task", "source_code")
    writes = ("code", "code_v1", "version")

    def __init__(self, llm: LLMClient | None = None) -> None:
        self.llm = llm

    def run(self, state):
        source = state.get("source_code")
        if source:
            code = source
            how = f"采用 {state.get('input_name')} 作为初稿"
        elif self.llm is not None and self.llm.available:
            prompt = (f"任务：{state.get('task')}\n"
                      "请输出一份完整、可直接运行的 Python 模块，只返回代码块。")
            try:
                code = extract_code(self.llm.complete(prompt))
                how = f"由 LLM({self.llm.model}) 生成"
            except Exception as exc:  # 网络或额度问题不应中断流程
                code = TEMPLATE
                how = f"LLM 调用失败（{type(exc).__name__}），回退离线模板"
        else:
            code = TEMPLATE
            how = "离线模板生成（设置 OPENAI_API_KEY 可启用 LLM）"

        state.update({"code": code, "code_v1": code, "version": 1}, source=self.name)
        self.say(state, "reviewer", "code_ready", how,
                 version=1, lines=len(code.splitlines()))
        return "review"


class ReviewerAgent(Agent):
    """审查 Agent：静态检查，产出结构化问题清单与判定。"""

    name = "reviewer"
    reads = ("code",)
    writes = ("review", "review_history", "iteration")

    def run(self, state):
        code = state.get("code") or ""
        result = review_code(code)
        iteration = (state.get("iteration") or 0) + 1
        history = list(state.get("review_history") or [])
        history.append({
            "iteration": iteration,
            "verdict": result["verdict"],
            "issues": result["issues"],
            "auto_fixed": state.get("last_fixed") or [],
        })
        state.update({"review": result, "review_history": history,
                      "iteration": iteration}, source=self.name)
        self.say(state, "router", "review_done",
                 f"第 {iteration} 轮审查：{len(result['issues'])} 个问题，判定 {result['verdict']}",
                 codes=[item["code"] for item in result["issues"]])
        return "route"


class FixerAgent(Agent):
    """修复 Agent：按审查结果做安全的机械化改写，产出新版本代码。"""

    name = "fixer"
    reads = ("code", "review")
    writes = ("code", "version", "last_fixed", "fix_skipped")

    def run(self, state):
        code = state.get("code") or ""
        review = state.get("review") or {}
        fixable = [item for item in review.get("issues", []) if item.get("fixable")]
        new_code, applied, skipped = apply_fixes(code, fixable)
        version = (state.get("version") or 1) + 1
        state.update({"code": new_code, "version": version,
                      "last_fixed": applied, "fix_skipped": skipped}, source=self.name)
        self.say(state, "reviewer", "code_fixed",
                 f"应用 {len(applied)} 条修复，跳过 {len(skipped)} 条，产出 v{version}",
                 applied=applied, skipped=skipped, version=version)
        return "review"
