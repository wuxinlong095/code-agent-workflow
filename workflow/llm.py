"""可选的大模型接入（OpenAI 兼容 /chat/completions）。

没有配置 OPENAI_API_KEY 时 available=False，编码节点会自动降级到离线模板，
保证评审环境零配置可跑。
"""
from __future__ import annotations

import json
import os
import urllib.request

DEFAULT_BASE = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o-mini"


class LLMClient:
    def __init__(self, model: str | None = None, base_url: str | None = None,
                 api_key: str | None = None, timeout: int = 30) -> None:
        self.model = model or os.getenv("LLM_MODEL", DEFAULT_MODEL)
        self.base_url = (base_url or os.getenv("LLM_BASE_URL", DEFAULT_BASE)).rstrip("/")
        self.api_key = api_key or os.getenv("OPENAI_API_KEY", "")
        self.timeout = timeout
        self.calls = 0

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def complete(self, prompt: str,
                 system: str = "你是资深 Python 工程师，代码简洁、可直接运行。",
                 max_tokens: int = 1500) -> str:
        if not self.available:
            raise RuntimeError("未配置 OPENAI_API_KEY")
        body = json.dumps({
            "model": self.model,
            "temperature": 0.2,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        }).encode("utf-8")
        request = urllib.request.Request(
            self.base_url + "/chat/completions",
            data=body,
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.api_key}"},
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        self.calls += 1
        return payload["choices"][0]["message"]["content"]


def extract_code(text: str) -> str:
    """从 Markdown 回复中抽取第一个代码块。"""
    if "```" not in text:
        return text.strip() + "\n"
    parts = text.split("```")
    for index in range(1, len(parts), 2):
        block = parts[index]
        lines = block.splitlines()
        if lines and lines[0].strip().lower() in {"python", "py", "python3"}:
            block = "\n".join(lines[1:])
        return block.strip("\n") + "\n"
    return text.strip() + "\n"
