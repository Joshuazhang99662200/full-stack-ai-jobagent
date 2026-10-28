# 跟踪政策替换审计

当前施工基线main a895f59。此次只替换活动的无回复废止政策，不改发送审批、租约和审计。新唯一时钟为48小时；观察次数仅为审计计数，不作为废止条件。

待替换位置：jobs/sent_tracking.py 的 CHECK_DAYS、start_tracking、advance；schemas/sent_tracking.py 的检查次数上限；对应跟踪/迟登记测试；sent-tracking参考、宿主接线和能力目录中的旧节律。新pipeline的已读/实质活动时间来自证据，不从徽标推断。

基线扫描命令：rg -n "CHECK_DAYS|no_response_14d|resume_no_invite_14d|1/3/7/14|check_count.*4|timedelta\(days=14\)" src tests skills hosts docs。

历史设计中的通用指标观察窗口、上游许可证说明和不可变审计原文不属于无回复废止政策，不据此误删其他功能。最终交付记录活动路径扫描与回归结果，历史文件如仍保留旧描述须明确标为被新政策取代，不能再作为宿主执行入口。

无精确发送时间或未验证发送证明时，只保存历史声明；不构造超时时钟。登录/风控导致暂停时，恢复后先读取真实对话再判断废止，不能把无法加载当无回复。终态停止到期检查；重新联系创建独立联系轮次并重新取得批准。
