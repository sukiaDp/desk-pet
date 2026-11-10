# desk-pet

羊角修女桌宠（Tauri v2）。透明置顶、透明处点穿、可拖动，空闲时视线跟着鼠标，头顶气泡显示 Claude Code 的状态。

- 启动：`./desk-pet.sh`；退出：托盘图标 →「退出」（也可以在那里显示 / 隐藏）
- 构建：`./build.sh`（Rust 工具链、编译产物都在 `/mnt/data2/desk-pet-build`）
- 放大：`DESK_PET_SCALE=2 ./desk-pet.sh`（整数倍）
- 素材：`assets/` 是 1–6 号完整状态包解压后的原样内容，运行时直接读，不用重新编译。提裙礼、被夸后藏脸、无聊等待三个附加包整理成 `assets/states/<id>/` 并列在 `assets/extra-states.json`。原始 zip 在 `source-zips/`（不进 git）。

## 和 CC 联动

`cc-mod/` 是一个 CC mod（已装在用户级：`desk-pet@local-mods`）。每个会话把状态写到
`~/.cache/desk-pet/sessions/<会话id>.json`，每 60 秒写一次心跳。桌宠每秒汇总一次，优先级：等你回复 > 出错 > 工作中 > 完成 > 空闲。
3 分钟没有心跳的会话不计入；完成、出错超过 2 分钟算空闲。

| 情况 | 动画 |
| --- | --- |
| 工作中 | running（专注工作） |
| 查看中（读文件、搜索） | review（低头检查） |
| 等你回复（权限、提问） | 先 startled-avert（吓一跳），再 waiting；超过 1 分钟没人理 → bored-wait（无聊等待） |
| 完成 | 先 jumping（跳一下），再 waving（招手） |
| 出错 | failed |
| 空闲 | idle；鼠标动时视线跟随；偶尔随机 prayer-peek / sneeze / brave-gaze |
| 空闲且鼠标 2 分钟没动 | sit-swing（坐下晃脚），5 分钟 sleepy-nod（打瞌睡） |
| 拖动 | running-left / running-right |
| 桌宠启动、新开 CC 会话 | modest-curtsy（提裙礼） |
| 你发给 CC 的消息里有夸奖（谢谢、辛苦、厉害、nice…） | hidden-blush（被夸后藏脸） |

缺素材的动画会自动跳过。调试：`DESK_PET_DEBUG=1` 时把动画切换打到 stderr，并把空闲计时缩成 8 秒 / 16 秒。

开关 mod：`claude plugin disable desk-pet@local-mods` / `claude plugin enable desk-pet@local-mods`（新会话生效）。
