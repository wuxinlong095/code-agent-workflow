"""极简多 Agent 工作流引擎（仅用标准库）。

提供的能力：
- 顺序执行：节点处理函数返回"下一个节点名"；
- 条件分支：router 节点根据共享状态返回不同节点；
- 循环：节点声明 max_visits，处理函数返回自身形成回路，超限直接报错；
- 共享状态：State 黑板，记录每次写入的来源；
- 事件日志：step_start / step_end / step_error，落盘为 JSONL；
- 检查点：每个节点结束写 runs/<run_id>/checkpoint.json，可断点续跑；
- 重试与错误路由：retries + on_error。
"""
from __future__ import annotations

import json
import time
import traceback
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

END = "__END__"


class State:
    """共享黑板：各 Agent 通过它读写数据，所有写入都留痕。"""

    def __init__(self, data: dict[str, Any] | None = None,
                 history: list[dict] | None = None) -> None:
        self.data: dict[str, Any] = dict(data or {})
        self.history: list[dict] = list(history or [])

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def set(self, key: str, value: Any, source: str = "unknown") -> None:
        self.data[key] = value
        self.history.append({"source": source, "key": key, "ts": round(time.time(), 3)})

    def update(self, mapping: dict[str, Any], source: str = "unknown") -> None:
        for key, value in mapping.items():
            self.set(key, value, source)

    def snapshot(self) -> dict[str, Any]:
        return {"data": self.data, "history": self.history}

    @classmethod
    def from_snapshot(cls, snap: dict[str, Any]) -> "State":
        return cls(snap.get("data"), snap.get("history"))


@dataclass
class Step:
    """工作流节点。kind: agent | tool | router。"""

    name: str
    handler: Callable[[State], str | None]
    kind: str = "agent"
    reads: tuple[str, ...] = ()
    writes: tuple[str, ...] = ()
    max_visits: int = 1
    retries: int = 0
    on_error: str | None = None


class CheckpointStore:
    """把每次节点结束后的状态写到 runs/<run_id>/，用于断点续跑与事后排查。"""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def run_dir(self, run_id: str) -> Path:
        path = self.root / run_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def save(self, run_id: str, index: int, next_step: str | None,
             state: State, events: list[dict]) -> None:
        path = self.run_dir(run_id)
        payload = {"index": index, "next": next_step, "state": state.snapshot()}
        (path / "checkpoint.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        with (path / "events.jsonl").open("w", encoding="utf-8") as handle:
            for event in events:
                handle.write(json.dumps(event, ensure_ascii=False) + "\n")

    def load(self, run_id: str) -> dict[str, Any]:
        path = self.run_dir(run_id) / "checkpoint.json"
        if not path.exists():
            raise FileNotFoundError(f"没有找到检查点：{path}")
        return json.loads(path.read_text(encoding="utf-8"))


class Workflow:
    """按"节点 + 返回下一个节点名"组织的最小工作流。"""

    def __init__(self, name: str, start: str) -> None:
        self.name = name
        self.start = start
        self.steps: dict[str, Step] = {}
        self.events: list[dict] = []
        self.run_id = ""

    def add(self, step: Step) -> "Workflow":
        if step.name in self.steps:
            raise ValueError(f"重复的节点名：{step.name}")
        self.steps[step.name] = step
        return self

    def _emit(self, event: str, **fields: Any) -> None:
        self.events.append({"ts": round(time.time(), 3), "event": event, **fields})

    def run(self, state: State, max_steps: int = 60,
            store: CheckpointStore | None = None,
            start_at: str | None = None) -> State:
        visits: Counter[str] = Counter()
        current = start_at or self.start
        executed = 0
        self._emit("workflow_start", workflow=self.name, run_id=self.run_id, start=current)

        while current and current != END:
            if current not in self.steps:
                raise KeyError(f"未知节点：{current}")
            if executed >= max_steps:
                raise RuntimeError(f"超过最大步数 {max_steps}，疑似死循环")
            step = self.steps[current]
            visits[current] += 1
            if visits[current] > step.max_visits:
                raise RuntimeError(
                    f"节点 {current} 访问 {visits[current]} 次，超过上限 {step.max_visits}")

            self._emit("step_start", step=current, kind=step.kind,
                       visit=visits[current], reads=list(step.reads))
            started = time.time()
            attempt = 0
            nxt: str | None = None
            while True:
                try:
                    nxt = step.handler(state)
                    break
                except Exception as exc:  # noqa: BLE001 - 节点级错误统一处理
                    attempt += 1
                    self._emit("step_error", step=current, attempt=attempt,
                               error=f"{type(exc).__name__}: {exc}",
                               traceback=traceback.format_exc())
                    state.set("last_error", {"step": current, "error": str(exc)}, source="engine")
                    if attempt > step.retries:
                        if step.on_error:
                            nxt = step.on_error
                            break
                        raise

            ms = round((time.time() - started) * 1000, 1)
            self._emit("step_end", step=current, next=nxt or END,
                       ms=ms, writes=list(step.writes))
            executed += 1
            if store is not None:
                store.save(self.run_id, executed, nxt, state, self.events)
            current = nxt

        self._emit("workflow_end", workflow=self.name, steps=executed)
        return state
