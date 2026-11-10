# desk-pet

羊角修女桌宠（PySide6，单文件 `pet.py`）。透明置顶、透明处点穿、可拖动。按 Claude Code 的状态切换动画，头顶气泡显示状态；点她一下会行提裙礼，然后看着鼠标一会儿。

- 首次准备：`./setup.sh`（在 `/mnt/data2/desk-pet-build/venv` 建 Python 3.12 venv 装 PySide6；3.10 上 PySide6 会崩）
- 启动：`./desk-pet.sh`；退出：托盘图标 →「退出」（也可以在那里显示 / 隐藏）
- 放大：`DESK_PET_SCALE=2 ./desk-pet.sh`（整数倍）
- 形象：每个形象一个目录 `themes/<id>/`，里面是 `theme.json`（名字、配色、字体、头像位置、界面文字）和素材 `assets/`。托盘「形象」菜单切换；也可以 `DESK_PET_THEME=<id>`。加新形象就是复制一个目录改掉，没写的字段用 `theme.py` 里的默认值。
- 羊角修女（`themes/sheep-nun`）：`assets/` 是 1–6 号完整状态包解压后的原样内容；提裙礼、被夸后藏脸、无聊等待三个附加包整理成 `assets/states/<id>/` 并列在 `assets/extra-states.json`。原始 zip 在 `source-zips/`（不进 git）。
- 以前的 Tauri v2 版本在 `tauri` 分支（Linux 上 WebKitGTK 透明窗口拖动后有重影，所以换了 Qt）。

## 聊天小窗

双击桌宠（或托盘「聊天」）打开，像 TG 一样给开了 `/desk-pet` 的会话发消息、看回复；终端里的对话也会同步过来。开了多个会话时顶上可以切换。

- 窗口没开时来了回复，头顶气泡提示，点她一下就打开。
- 从小窗发起的那一轮里，CC 用提问工具给的选项会显示成按钮（多选是勾选框），点了就回答；终端里同时也有对话框，哪边先答都行。
- 工具权限只能在终端里批准，小窗只提醒在等哪个工具。
- 只有终端里开着的会话能聊；CC 正在忙时发的消息会排队。


`cc-mod/` 是一个 CC mod（已装在用户级：`desk-pet@local-mods`），**按会话开启**：默认不推送，在会话里输入 `/desk-pet` 打开、再输入一次关闭（也可以 `/desk-pet on|off`）；用 `DESK_PET=1 claude` 启动的会话默认打开。打开时提示框右下角显示绿色「● 桌宠」。等你回复只在真的弹出权限对话框时才算（auto 模式自动放行的不算）。

打开的会话把状态写到
`~/.cache/desk-pet/sessions/<会话id>.json`，每 60 秒写一次心跳。桌宠每秒读一次、汇总，优先级：等你回复 > 出错 > 工作中 > 查看中 > 完成 > 空闲。
3 分钟没有心跳的会话不计入；完成、出错超过 2 分钟算空闲。

| 情况 | 动画 |
| --- | --- |
| 工作中 | running（专注工作） |
| 查看中（读文件、搜索） | review（低头检查） |
| 等你回复（权限、提问） | 先 startled-avert（吓一跳），再 waiting；超过 1 分钟没人理 → bored-wait（无聊等待） |
| 完成 | 先 jumping（跳一下），再 waving（招手），约 6 秒后回到待命 |
| 出错 | failed |
| 空闲 | 站着（idle）；偶尔随机 prayer-peek / sneeze / brave-gaze |
| 闲置 30 分钟以上 | 随机 sit-swing（坐下晃脚）或 sleepy-nod（打瞌睡），保持到 CC 有动静或点她 |
| 拖动 | running-left / running-right |
| 点她一下 | modest-curtsy（提裙礼），头顶气泡收起（状态变了再出来），之后 8 秒视线跟着鼠标（16 个方向） |
| 你发给 CC 的消息里有夸奖（谢谢、辛苦、厉害、nice…） | hidden-blush（被夸后藏脸） |

缺素材的动画会自动跳过。调试：`DESK_PET_DEBUG=1` 时把动画切换打到 stderr，并把计时缩短（无聊等待 8 秒、闲置 12 秒）。

整个 mod 停用 / 启用：`claude plugin disable desk-pet@local-mods` / `claude plugin enable desk-pet@local-mods`（新会话生效）。
