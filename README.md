# 多 Agent 代码审查工作流（HW2 · Simple Workflow MVP）

三个 Agent（编码 coder → 审查 reviewer → 修复 fixer）通过共享状态协作，完成
"读入代码 → 静态审查 → 自动修复 → 复检 → 出报告"的端到端流程。

**方向选择**：代码审查流程（编码 + 审查 + 修复）。选它是因为可以复用 HW1 代码助手中
"发现问题 → 定位 → 修复"的经验，而且审查结果能用确定性规则实现，**离线可复现、可写单元测试**，
评审时不需要任何 Key。

## 1. 环境

| 项 | 说明 |
| --- | --- |
| 系统 | Windows 11 + MSYS2 UCRT64（Git Bash 也可） |
| Python | 3.12（未加入 PATH，仓库自带 `run.sh` 自动探测） |
| 依赖 | 无第三方包，纯标准库 |

## 2. 快速开始

```bash
cd ~/Desktop/code-agent-workflow

./run.sh -m workflow.main demo               # 用内置样例跑完整流程
./run.sh -m workflow.main graph              # 只打印工作流图 + 节点表
./run.sh -m unittest discover -s tests -v    # 单元测试
