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
