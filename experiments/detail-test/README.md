# 精致度小实验（2026-11-09）

验证两件事：AI 生成静态道具能不能达到素材商店的水准；动物画布放大或换 Pro 模式后能精致多少。

- `props_test.py` → `props/`、`props_compare.png`、`pixen_sheet_2x.png`：石器时代营地道具，三种模型对比
- `units_test.py` → `units/`、`hyena_compare.png`、`mammoth_compare.png`：斑鬣狗 32→64px（v3 / Pro），猛犸象 64→128px
- `scene_compare.png`：现有素材、放大后的单位、营地道具，放在同一张地图上比较

| 项目 | 接口 | 消耗 |
| --- | --- | --- |
| 整张道具表 384×256 | create-image-pixen | 1 |
| 单个道具 96px | create-image-pixen | 1 |
| 单个道具 96px（4 个变体） | generate-image-v2（Pro） | 10 |
| 单个道具 96px | create-image-pro-flash | 5 |
| 64px 角色 + 1 个方向行走 | create-character-v3 | 3 |
| 64px 角色 + 1 个方向行走 | create-character-pro | 11 |
| 128px 角色 + 1 个方向行走 | create-character-v3 | 6 |

合计 84 次生成。
