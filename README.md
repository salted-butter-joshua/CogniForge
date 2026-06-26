<div align="center">

# Loop Engineering

**生产级 AI 闭环工程方法论与参考实现**

[方法论](#loop-engineering-是什么) · [CogniForge 参考实现](./learn-loop/) · [技术栈白皮书](./loop-engineering.md)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./learn-loop/LICENSE)

</div>

---

## Loop Engineering 是什么

**Loop Engineering（闭环工程）** 是一套面向 AI Agent 的**迭代闭环系统设计方法**：把「生成 → 执行 → 评估 → 反馈 → 再生成」做成**可观测、可终止、可续跑**的生产级流水线，而不是手写 `while True` 或依赖模型自行喊停。

核心主张：

| 原则 | 含义 |
|------|------|
| **双重终止** | 业务达标条件 + 全局 `max_iter` 硬上限，禁止只靠模型判断退出 |
| **生成与评估分离** | Judge / 校验器与生成模型分离，避免自判偏差 |
| **状态可恢复** | LangGraph Checkpoint + Redis/PostgreSQL，宕机可断点续跑 |
| **收敛检测** | 连续多轮指标无提升则主动退出（`stagnated`），拒绝无效空转 |
| **分层超时** | 单步 / 单轮 / 全任务逐级熔断 |
| **异常隔离** | 单步失败记录并进入下一轮修复，不拖垮整条 Loop |

完整技术栈、架构选型与线上规范见 **[loop-engineering.md](./loop-engineering.md)**。

---

## 仓库结构

```
loop-engineering/
├── loop-engineering.md     # 方法论与技术栈白皮书
├── learn-loop/             # CogniForge 参考实现（建议重命名为 cogniforge/）
│   ├── README.md
│   ├── src/
│   ├── config/
│   └── docker-compose.yml
└── README.md
```

> **目录命名**：实现代号 **CogniForge**。若目录仍为 `learn-loop/`，可执行 `git mv learn-loop cogniforge` 完成重命名（需先关闭占用该目录的 IDE/进程）。

---

## CogniForge

**[CogniForge](./learn-loop/)** 是 Loop Engineering 在**知识学习与 mastery 验证**场景下的首个开源参考实现，包含自适应课程/难度、Observer 笔记分析与 Web Console：

```bash
cd learn-loop   # 或 cogniforge（重命名后）
cp .env.example .env
docker compose up --build
```

详见 **[learn-loop/README.md](./learn-loop/README.md)**（CogniForge 文档）。

---

## 许可证

参考实现采用 [MIT License](./learn-loop/LICENSE)。
