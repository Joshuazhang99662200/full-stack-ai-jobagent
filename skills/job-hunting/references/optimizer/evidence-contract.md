# 优化器证据契约

每一条实质性 bullet 都要回带它的证据 ID、需求 ID、来源简历条目 ID、改写操作与置信度。起草完成后再抽取主张,并且只拿每条主张对照它自己引用的证据做校验。

合法的校验状态是 `SUPPORTED`、`PARTIALLY_SUPPORTED`、`UNSUPPORTED` 与 `CONTRADICTED`。处于部分支撑状态的内容必须先收窄表述并重新校验,才能被纳入。
