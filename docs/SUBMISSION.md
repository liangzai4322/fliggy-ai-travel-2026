## 参赛项目名称

行程有数 · 预算旅行助手

## 团队 / 作者与奖品领取人

- 团队名称：行程有数
- 主要提交人 GitHub ID（仅 1 位，必填）：liangzai4322
- 其他成员（可选，仅用于署名）：无

## 旅行场景与目标用户

面向预算固定、希望轻松出游的自由行用户。用户给出出发地、目的地、日期、人数和总预算，获得机酒候选、费用拆分和留有休息时间的行程。

## 我做了什么

作品把“先知道能花多少钱”和“每项价格从哪里来”放进同一条旅行规划流程：

1. 百炼理解需求并调用官方飞猪 Skill，查询去程、返程和酒店。
2. 每项结果记录查询条件、时间、命令与响应，保留官方产品链接。
3. 按成人数、晚数、房间数核算参考费用；餐饮、活动、市内交通和机动金单独标为估算。
4. 缺少价格时不把它记作零元；税费、酒店起价和多人同价库存未核验时，不声称预算已经满足。
5. 提供可离线浏览的 HTML 预算单，以及可重放历史证据的 Python 脚本。

本作品为查询和规划原型，不创建订单或代为支付。

## 百炼使用说明（必填）

- 百炼能力 / 模型：阿里云百炼 Managed Agent，Qwen3.8-Flash；Multi-Agent 关闭。
- 调用方式：百炼控制台的 Managed Agent 会话与内置工具；不是仅在文档中提及百炼。
- 使用环节与输入输出：运行时接收用户旅行需求，读取官方技能参数文档，通过 bash 调用飞猪 CLI，比较真实候选，输出预算解释与行程。凭据在创建会话时通过环境变量注入，不放进提示词或公开源码。
- Skill 名称：飞猪旅行 V1.0，官方来源 `alibaba-flyai/flyai-skill`；实测 CLI 为 `@fly-ai/flyai-cli@1.0.16`。
- 其他工具 / 技术栈：Python 3 标准库、Node.js、官方 FlyAI CLI、HTML/CSS。独立 Python 脚本负责确定性查询和预算报告，不单独提供大模型推理；完整 AI 体验按仓库的百炼步骤复现。

## 效果展示

2026-10-22 在百炼 Managed Agent 中完成正式验证：上海→三亚、三亚→上海及三晚酒店三项查询均 `exitCode=0`、`status=0`，每项返回 10 条。原始查询证据已随仓库公开，包含查询时间、命令、版本与完整响应。

方案 A：MU5377 去程、HO1130 返程、三亚湾摩卡时光公寓。机酒列表价按单人及每间每晚推算为 ¥3278；加上餐饮、市内交通、活动和机动金估算 ¥2700，参考合计 ¥5978。税费、价格单位、多人库存及酒店完整成交价仍待核验，未宣称最终预算满足。

![作品实际运行画面](https://raw.githubusercontent.com/liangzai4322/fliggy-ai-travel-2026/main/docs/assets/demo.png)

![预算核算实际截图](https://raw.githubusercontent.com/liangzai4322/fliggy-ai-travel-2026/main/docs/assets/budget.png)

![百炼真实调用截图](https://raw.githubusercontent.com/liangzai4322/fliggy-ai-travel-2026/main/docs/assets/bailian-run.png)

验证：6 项预算与异常边界测试通过；历史证据离线复读得到相同参考合计；Chrome 页面已实际打开核验。详见仓库 `docs/VERIFICATION.md`。

## 项目链接与复现方式

- GitHub 仓库：https://github.com/liangzai4322/fliggy-ai-travel-2026
- 在线演示快照：https://liangzai4322.github.io/fliggy-ai-travel-2026/
- 完整行程与候选比较：https://github.com/liangzai4322/fliggy-ai-travel-2026/blob/main/demo/demo-report.md

在线演示展示一次真实查询的快照，不提供在线实时聊天，也不接收用户 Key。

完整 AI 体验：在百炼新建智能体，使用仓库 `agent/` 的配置和提示词，添加官方飞猪技能，在会话环境中注入自己的 `FLYAI_API_KEY`，输入 `examples/sanya.json` 对应需求并运行。独立报告：安装官方 CLI 后运行 `python3 travel.py --request examples/sanya.json`，打开生成的 `output/report.html`。

需求示例：2名成人，2026-11-07上海到三亚，2026-11-10返程，3晚1间，总预算8000元；直飞优先，海边散步，行程轻松。未来复现请更新日期。

## 踩坑记录（可选）

- 免 Key 模式在百炼云端实际返回 `429 Trial limit reached`，需要正式凭据；没有把官网体验结果冒充为智能体运行成功。
- 不同会话的运行环境可能独立，CLI 安装需要检查。
- 酒店列表起价不是指定房型、人数及全部晚数的成交总价；航班列表价也不足以证明税费和行李口径。预算报告保留这些缺口。
- 为避免 SDK 报错携带认证字段，公开证据不保存原始 stderr。
- 真实响应使用 `ticketPrice`，与官方示例的 `adultPrice` 不同；已适配实际字段，并将单人及人民币口径列为待核验项。
