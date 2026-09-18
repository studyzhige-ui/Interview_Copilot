# 竞品功能与外部接入核验

> 日期：2026-09-14。用途：支持产品功能补齐讨论；本文件记录研究事实与限制，不制定产品方案。
> 对照[原14家竞品记录](2026-09-job-journey-evidence.md)，重新访问原样本并重点读取与本轮六类补充相关的内容。公开页面或帮助文档不等于登录后功能实测；未上传个人材料、安装客户端或执行真实申请。

## 1. 原竞品的对照结果

| 产品与来源 | 本轮可用信息与具体形态 | 核验范围 |
|---|---|---|
| [OfferGoose鹅来面](https://offergoose.cn/) | 系统音频识别、实时思路建议、模拟、押题、复盘、多语言 | 本轮官网正文；通过率与响应速度是宣传数据，未实测 |
| [面灵AI](https://www.mianlingai.com/) | 官网演示将问题、核心要点、参考回答分开；提供回看、暂停、立即回答等操作介绍；另有模拟、复盘、双端、翻译与简历入口 | 本轮官网；演示不是用户实际会话 |
| [面试猫](https://offermore.cc/) | 原记录包含岗位模拟、追问、资料知识库、实时辅助和分析 | 本轮入口可访问但定向正文读取不稳定；详细功能以原核验为据，未新增实测结论 |
| [Offer IN](https://www.offerin.cn/) | 原记录包含面试笔试辅助、双端与客户端增强 | 本轮公开页读取有限，保留原证据；与Offerin.co分别记录 |
| [智面星](https://aiqtools.cn/) | 根据简历和岗位模拟，现场关键词与答案提示，面试报告 | 本轮官网；题库数量、命中率和效果不作为已验证结论 |
| [面试精灵](https://interview-genie.com/web/) | 简历与JD定制会话、说话人区分；双栏分别提供快速思路与深入结果；会话记录；页面介绍简历增强与联网 | 网页抓取超时，已用浏览器读取公开页；RAG和模型内部机制未验证 |
| [白瓜](https://m.baigua.com/) | 本轮页面可见笔试、实时面试、模拟与跨文化面试入口；原记录另含双端、个人资料库与总结 | 部分定向读取无结果，不将原记录细节声称为本轮实测 |
| [OfferWing](https://offerwing.cn/) | 招聘日历、JD简历、模拟、语速/逻辑/内容反馈、投递日程、面经广场、专家辅导及模拟职场介绍 | 已用浏览器读取；页面保留“更多功能即将上线”，不能据首页断言各服务均已完整上线 |
| [Offerin.co](https://offerin.co/) | JD诊断、选中文本逐句修改、预览/PDF、英文版本、历史版本与JD联动；模拟可观摩或人机交互，并包含谈薪；集中保存素材 | 已用浏览器读取；“简历补料教练”“工作复盘助手”仍标即将上线；生成参考JD不是市场实际岗位 |
| [Offer.cc](https://offer.cc/zh) | 原记录中的截图识题、算法/系统设计/行为题、追问上下文与简历个性化 | 本轮抓取失败，沿用9月10—11日证据，不声称完成本轮重新核验 |
| [Final Round AI](https://www.finalroundai.com/) | 每个Goal关联岗位、简历、资料与轮次；准备、练习、现场辅助及复盘沿用同一Goal；复盘衔接下一轮 | 本轮官网正文；已确认其公开组织方式，未验证底层共享实现 |
| [LockedIn AI](https://www.lockedinai.com/) | 现场助手、编程与双端/远程协助；Career Launchpad另提供简历、求职信、职业主页优化、跟踪与规划 | 结合本轮入口与9月13日官网FAQ；不能把主页优化等同于自建可发布个人站 |
| [Sensei](https://www.senseicopilot.com/) | 简历与个人故事编辑、岗位上下文、实时建议、Coding与Playground | 结合本轮入口与9月13日读取；不据此推断支持完整职业知识管理 |
| [InterviewGPT.in](https://www.interviewgpt.in/) | Windows现场助手、快捷键、屏幕分析、技术问题辅助及ATS检查入口 | 本轮官网FAQ；不合并其他同名域名 |

## 2. 补充对标

| 产品与来源 | 本轮观察到的方式 |
|---|---|
| [Teal](https://www.tealhq.com/) | 按岗位定制简历、模板、JD匹配、职位收藏与跟踪、求职信；浏览器扩展用于收集外部机会 |
| [Huntr](https://huntr.co/) | 基础与岗位定制简历、逐项修改建议及原因、批量采纳/拒绝、检查、求职信；岗位采集、网申填充、岗位/面试记录与私有笔记 |
| [Yoodli官方练习指南](https://support.yoodli.ai/en/articles/9550465-practice-with-yoodli) | 角色对话、演讲/展示、面试练习分别适配场景；输入公司岗位、选择对话风格、自选问题及动态追问；屏幕分享可用于展示材料，结束后查看分析并保存练习 |
| [Big Interview](https://www.biginterview.com/)与[官方题库说明](https://support.biginterview.com/en/article/the-question-library-1n0yh2y/) | 本轮官网可访问；行业、岗位、能力的题库组织沿用A阶段已读官方说明 |
| [牛客网申助手](https://www.nowcoder.com/my/resume-plugin-intro) | 本轮抓取正文有限；预填写、用户补改与网站适配沿用B阶段核验，不扩大为任意网站完全自动投递 |

## 3. 邮箱能否直接接入

**官方接口支持产品直接建立用户授权连接，不以另行安装市场插件为技术前提。**“内置”是我们产品的集成形态，仍需要接入邮箱提供方的认证与数据接口。

| 来源 | 已核验事实 |
|---|---|
| [Gmail权限说明](https://developers.google.com/workspace/gmail/api/auth/scopes) | OAuth可授权读取；gmail.readonly属于受限权限，metadata不包含正文。面向公众的相应应用需验证；在服务器存储或传输受限数据涉及安全评估。读取权限不等于发送权限 |
| [Gmail变更通知](https://developers.google.com/workspace/gmail/api/guides/push) | 可通过Cloud Pub/Sub通知后端邮箱变化，再读取变化；watch需要续期。文档对用户设备推荐同步轮询方式，不能将云端推送方案直接等同于纯本地运行 |
| [Microsoft Graph权限](https://learn.microsoft.com/en-us/graph/permissions-reference#mailread) | 委托Mail.Read读取登录用户邮箱，支持个人Microsoft账户及工作/学校账户；Mail.ReadBasic不含正文与附件。应用权限和用户委托权限不同 |
| [Outlook变更通知](https://learn.microsoft.com/en-us/graph/outlook-change-notifications-overview) | 邮件、日历等可订阅变更；需要维护订阅有效期与通知中断恢复；用户委托订阅有邮箱范围限制 |

用户授权是接入的一部分，不代替开发者应用注册、生产验证、连接有效性与持续同步处理。邮箱权限也不会自动给出“仅招聘邮件”的语义边界；产品仍需决定筛选与资料使用范围。以上未执行OAuth接入验证。

## 4. Canva接入与简历编辑

“canvas”暂按Canva研究。以下结论只适用于这些官方文档描述的产品与接口；没有验证其与中国大陆可画账户体系的互通。

| 来源 | 已核验事实 |
|---|---|
| [Canva Connect APIs](https://www.canva.dev/docs/connect/) | 支持资产、设计等的创建与同步，可将设计交给用户编辑后导出回本产品；公开集成需要审核。该接口与在Canva内部运行的Apps SDK不同 |
| [Get design](https://www.canva.dev/docs/connect/api-reference/designs/get-design/) | 可获取设计元数据及编辑/查看链接；存在编辑链接不等于获得可嵌入的完整编辑器或任意设计内容修改接口 |
| [Autofill指南](https://www.canva.dev/docs/connect/autofill-guide/) | 可将数据填入有标记字段的设计/模板；官方指南要求集成代表Canva Enterprise组织成员操作，开发者资格不自动覆盖所有终端用户；不是普通个人账号授权后即可假定通用 |
| [Design Editing API](https://www.canva.dev/docs/apps/design-editing/) | 属于Canva Apps SDK的设计交互能力，不能将SDK与Connect REST接口混作同一种外部编辑方式 |
| [Canva AI Connector](https://www.canva.com/ai-connector/) | 官方提供AI连接入口；本轮只确认入口存在，未验证我们的产品能否直接使用全部编辑能力、可用账户及商业条件 |

因此，“本产品自有简历编辑器”“接入Canva设计并返回成果”“未来市场中提供Canva扩展”是需要分别决策的集成形态。文档事实不足以承诺用户只授权一次，就能在我们的UI内获得完整Canva编辑体验。
