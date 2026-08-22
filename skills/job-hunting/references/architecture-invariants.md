# 架构不变式

```text
CandidateProfile != Resume
Evidence is the source of truth
JobSource != Job Intelligence
Job Match != Resume Compatibility
Resume Tailoring != Fact Generation
Preview != Approval
Approval != Send
Platform Connector != Domain Core
Search != Apply
Review != Auto Promote
CAPTCHA != Retry
```

不可逆操作各自是独立的能力。领域代码不得依赖 DOM 选择器、浏览器配置、平台 SDK 模型或连接器内部实现。
