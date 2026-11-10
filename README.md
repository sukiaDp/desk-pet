# desk-pet

羊角修女桌宠（Tauri v2）。透明置顶、透明处点穿、可拖动，空闲时视线跟着鼠标，头顶气泡显示 Claude Code 的状态。

- 启动：`./desk-pet.sh`；退出：托盘图标 →「退出」（也可以在那里显示 / 隐藏）
- 构建：`./build.sh`（Rust 工具链、编译产物都在 `/mnt/data2/desk-pet-build`）
- 放大：`DESK_PET_SCALE=2 ./desk-pet.sh`（整数倍）
- 素材：`assets/` 是素材包解压后的原样内容，运行时直接读，不用重新编译。现在只有 6 号包（视线 180°–337.5°，右侧方向用镜像补），1–5 号包解压到同一目录后，就有待机、工作、等待等动画了。

## 和 CC 联动

`cc-mod/` 是一个 CC mod（已装在用户级：`desk-pet@local-mods`）。每个会话把状态写到
`~/.cache/desk-pet/sessions/<会话id>.json`，每 60 秒写一次心跳。桌宠每秒汇总一次，优先级：等你回复 > 出错 > 工作中 > 完成 > 空闲。
3 分钟没有心跳的会话不计入；完成、出错超过 2 分钟算空闲。

| CC 状态 | 动画 |
| --- | --- |
| 工作中 | running（专注工作） |
| 等你回复（权限、提问） | waiting |
| 完成 | waving |
| 出错 | failed |
| 空闲 | idle + 视线跟随 |

开关 mod：`claude plugin disable desk-pet@local-mods` / `claude plugin enable desk-pet@local-mods`（新会话生效）。
