# 生态争夺 · 素材库

《生态争夺》（自然 vs 人类）的像素美术素材库。规范来自《美术方案》：像素风、3/4 斜俯视、32×32 方格；单位做 8 个方向（画 5 个，左侧 3 个由右侧镜像）；1 像素深色描边；光源在左上。

## 目录结构

```
prompts/
  style.yaml               全局风格：视角、描边、生成哪 5 个方向、镜像关系、主调色板
  units/<id>.yaml          每个单位的提示词、画布尺寸、骨骼模板、种子、动作列表
palettes/endesga-32.hex    主调色板（占位，定调阶段再选定）
units/<id>/
  raw/                     PixelLab 原始导出（8 方向 + 动画帧 + metadata.json），不改动
  <id>.png                 处理后的精灵图集（已锁调色板、已镜像出 8 方向）
  <id>.json                图集描述，TexturePacker JSON Hash 格式，Phaser 3 / PixiJS 可直接加载
  source.json              来源登记：工具、日期、character_id、完整请求参数、消耗次数
preview/                   预览 GIF、比例对照图、百人同屏模拟
scripts/
  pixellab_api.py          PixelLab v2 REST 客户端（API key 从环境变量读取，不落盘）
  generate.py              按 YAML 生成单位：建角色 → 逐方向生成动画 → 下载 ZIP
  postprocess.py           统一画布、镜像、锁色、拼图集、导出 JSON 和 GIF
  preview_scene.py         生成比例对照图和百人同屏模拟场景
```

## 使用

```bash
pip install -r requirements.txt
export PIXELLAB_API_KEY=pixl_xxx              # 不要提交到仓库

python scripts/generate.py prompts/units/nature_ice_wolf.yaml   # 生成（可重跑，已完成的步骤会跳过，不会重复扣费）
python scripts/postprocess.py                                   # 处理所有单位
python scripts/preview_scene.py                                 # 刷新预览
```

新增一个物种，只需复制一份 `prompts/units/*.yaml` 并改描述、尺寸和骨骼模板（人形用 `mannequin`，四足用 `bear`/`cat`/`dog`/`horse`/`lion`），然后运行上面三条命令。

### 在游戏里加载（Phaser 3）

```js
this.load.atlas('wolf', 'units/nature_ice_wolf/nature_ice_wolf.png', 'units/nature_ice_wolf/nature_ice_wolf.json');
// 帧名：<动作>_<方向>_<序号>，如 walk_south-east_0；动作列表在 json 的 "animations" 字段
// meta.unit.anchor 是脚底锚点（用于 y 排序和放阴影/阵营圈），meta.unit.fps 是建议帧率
```

## 生成参数与费用（实测）

| 操作 | 接口 | 消耗 |
| --- | --- | --- |
| 新建 8 方向角色（32px 或 64px） | `create-character-v3`，从文字生成 | 2 次 |
| 动画，每个方向 | `characters/animations`，`mode: v3` | 1 次 |

一个物种 = 建角色 2 次 + 5 个动作 × 5 个方向 × 1 次 = **约 27 次**。与《美术方案》的估算一致：36 个物种约 970 次，加上一倍重试约 2000 次。

## 试用结果（2026-11-09，PixelLab 试用账号）

共用 27 次生成（试用额度 40 次，剩 13 次）。

| 单位 | 画布 | 内容 | 消耗 |
| --- | --- | --- | --- |
| 原始人猎人 `human_ice_hunter` | 32px | 8 方向、走路 ×5 方向、攻击（刺矛）×5 方向 | 12 次 |
| 猛犸象 `nature_ice_mammoth` | 64px | 8 方向、走路 ×5 方向 | 7 次 |
| 狼 `nature_ice_wolf` | 32px | 8 方向、走路 ×5 方向 | 7 次 |
| 对比测试：骨骼模板走路 | — | 猎人朝东，1 个方向（已删除） | 1 次 |

### 百人同屏模拟（2 倍显示，阵营圈和阴影由代码绘制）

![scene](preview/scene.gif)

### 比例对照（32px 格子，3 倍显示）

![lineup](preview/lineup.png)

### 动画（8 个方向，从左到右：下、右下、右、右上、上、左上、左、左下；左侧 3 个是镜像）

![hunter walk](preview/human_ice_hunter_walk.gif)
![hunter attack](preview/human_ice_hunter_attack.gif)
![mammoth walk](preview/nature_ice_mammoth_walk.gif)
![wolf walk](preview/nature_ice_wolf_walk.gif)

### 结论

- **转向图（8 方向静态）质量高。** 1px 黑描边、左上光源、各方向身份一致，32px 下轮廓清楚。猛犸象 64px 效果最好。
- **v3 文字动画：大体可用，但需要筛选。** 猛犸象走路很有重量感。猎人攻击很清楚。猎人朝东走路时矛从竖着慢慢变成平端，循环会跳帧；朝下走路腿部动作偏小。狼 32px 的右下方向偏糊，像哈士奇多于狼。
- **骨骼模板动画（`template` 模式）不能用。** 它丢掉了角色特征：矛和描边都没了，脸也变了。所以统一用 v3。
- **调色板锁定暂时关闭。** Endesga 32 只是占位，会把灰狼变蓝、肤色变粉（见 `preview/palette_compare.png`，上排原图，下排锁色后）。定调阶段选好真正的主调色板后，在 `prompts/style.yaml` 打开即可。
- **免费账号同时只能跑 1 个任务，每个约 3～4 分钟。** 订阅后可以并发，批量生产时会快很多。

### 批量生产时的改进点

1. 动作描述写得更具体，并约束道具姿态（如 “spear stays vertical”），每个动作多生成一版挑选。
2. 小型四足动物考虑用 40～48px 生成，或者先精修朝下的那张作为参考图，再用参考图模式转 8 方向。
3. 定调图确定后，用 `create-character-pro` 的 `style_character_id` 把它作为风格参考（每个角色 10～25 次，较贵），或继续用 v3 加统一的提示词模板。
