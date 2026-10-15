# 方块交互验证：Mythos 热更新脚本原型

这是两条原生 Mythos JSON 动作序列。无需修改/重新构建/替换模组 JAR。此前实验性的 Java 功能不依赖、不安装。

- `方块验证_准星_单次.json`：双手空手、游戏内无界面时，走已有 `click` 动作触发一次正常世界右键。请对准可触及方块；若对准实体，原生右键会尝试与实体交互。当前 JSON API 没有直接导出准星射线结果的动作，因此不会伪造已取得准星方块坐标。
- `方块验证_脚下_单次.json`：站稳、双手空手，冻结脚下坐标，用已有 `rightclickblock` 动作右键一次，保留视角，交互前客户端缓存由观察器保存。脚下 Y 使用 `floor(player_y - 0.01)`，兼容负坐标/半砖高度。
- `方块交互验证_导入.json`：适用于菜单导入的合集。已添加到现有唯一配置档 `Default/custom_paths.json`；当前 MCP 未连接，下一次加载配置时可见。以后修改脚本后运行 `hot_reload.cmd`，通过原有 `mythos_paths put/get` 校验、热载入并读回，不会执行脚本。不要拿 MCP 格式的单条 JSON 直接当磁盘合集导入，两种步骤字段分别为 `pos` / `goto`。

## 使用

1. 进服后双击 `hot_reload.cmd`，看到两条“已热载入”。无需关闭游戏。
2. 双击 `observe.cmd`，等控制台显示“观察器已就绪”。它自动定位唯一在世界中的客户端；多个客户端时运行 `python observe.py --player 角色名` 或 `--pid PID`。
3. 游戏菜单的路径/脚本列表里，找到分类“方块交互验证”，手动运行其中一条。准星模式请对准方块。测试时不要同时手动右键或运行别的自动交互。
4. 观察器最长等待 90 秒寻找一次出站方块右键，然后等目标坐标的更新最多 5 秒；结果写入 `results/review-*.json`。以后可以单独给这两条序列绑定热键。

## 验证含义

JSON 动作序列执行完成只表示尝试交互，不表示服务端确认。现有脚本 API 的 `capture_block_at` 读的是客户端世界缓存，不能据此宣布真实方块。

`observe.py` 是配套的只读 MCP 观察脚本，调用现有 `mythos_status`、`mythos_snapshot`、`mythos_packets capture_start/list/capture_stop`，不发送游戏动作或原始数据包，不清空捕获证据。原本已经开启捕获时保持开启；自己开启时结束后关闭。热载入模式只调用脚本验证/保存/读回接口，不运行序列。

观察器从已捕获的 `CPacketPlayerTryUseItemOnBlock` 获取实际目标位置，按 **1.12.2 的 X26/Y12/Z26** 解码位置，匹配后续 `SPacketBlockChange` 或 `SPacketMultiBlockChange` 中相同坐标。输出服务器下发的 stateId 和原包，以及独立的交互前后客户端快照。stateId 不擅自转换成某个矿物名称，客户端快照也不冒充服务器隐藏世界真值。

`server_block_update` 表示观察到对应位置的下发包。协议没有请求 ID，因此是会话、时间和坐标关联，不是严格因果确认。`timeout_unverified` 为超时未验证；多次交互、会话/维度变化、捕获预算耗尽会停止并标记未确认。服务器仍可能下发混淆值，不能保证还原隐藏地形。当前版本暂不提供完全纯 JSON 的坐标级回包解析；这部分由上述可热改的只读观察器完成。

## 验证与开发

运行 `python test_observe.py` 检查负坐标、空气回包、批量更新坐标、手别、截断包与每条序列仅一次交互。两条 JSON 另外使用模组现有 `PathConfigValidator` 离线校验。实际交互效果待游戏在线后验收。

源码参考：`PathSequenceManager` 的 `click/rightclickblock`，`ModUtils.simulateMouseClick/rightClickOnBlock`，`PathSequenceEventListener.captureBlockAt/captureHotbar`，`McpGameService.packets`。该原型不需要新增任何 Java 接口。成熟后可将“目标选择→交互→观察→结果存档”状态机迁移到独立模组。
