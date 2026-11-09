# 生态争夺 · 素材库

《生态争夺》（自然 vs 人类）的像素美术素材库。规范来自《美术方案》：像素风、3/4 斜俯视、32×32 方格；单位做 8 个方向（画 5 个，左侧 3 个由右侧镜像）；1 像素深色描边；光源在左上。

## 网站（Vercel）

素材网站在 `web/`（Vite + PixiJS 纯静态站），部署在 Vercel，生产分支为 `main`。根目录的 `vercel.json` 已配置好构建命令，Vercel 项目的 Root Directory 保持仓库根目录即可。

- **图鉴**（`#/`）：所有已生成素材按同一像素比例并排播放，可切换待机、行走、攻击、休息动作和 8 个方向；下方列出物种表中待生成的物种。
- **素材详情 / 配置**（`#/unit/<id>`）：大图播放器、全部帧、8 方向静态图；物种表中的设定（技能树、捕食、攻击、休眠、寿命等）、生成提示词与参数、动作提示词、来源登记、PNG/JSON 下载、原始 YAML。
- **实验室**（`#/lab`）：用 PixelLab 生成的自动拼接地块（雪地、苔原、水域、泥地）拼出地图。单位可以自己闲逛、追击并攻击敌对阵营，按物种表的休眠时段休息；也可以强制全体或单个单位进入待机、行走、攻击、休息。另有昼夜色调、百人混战压测、放置和清空。

本地预览：

```bash
cd web && npm install && npm run dev
```

`npm run build` 会先运行 `web/scripts/build-data.mjs`，把 `units/`、`prompts/`、`data/`、`tilesets/` 汇总成 `web/public/data/manifest.json`。所以只要提交了素材，Vercel 下一次部署就会自动展示。

## 目录结构

```
prompts/
  style.yaml               全局风格、默认动作（待机/行走/攻击）、生成的 5 个方向、镜像关系、调色板开关
  units/<id>.yaml          每个物种：表格行、提示词、画布、骨骼模板、种子、栖息地、动作覆盖
  tilesets.yaml            实验室地块（Wang 自动拼接）的提示词
data/
  species.json, creatures.csv  物种表快照（scripts/sync_species.py 拉取）
units/<id>/
  raw/                     PixelLab 原始导出（不改动）
  candidates.png           候选对比图（每个物种生成多个候选，挑最好的）
  <id>.png / <id>.json     处理后的精灵图集 + 图集描述（TexturePacker JSON Hash，Phaser 3 / PixiJS 直接加载）
  source.json              来源登记：工具、日期、候选、选中的 character_id、请求参数、消耗
tilesets/<id>.png|json     4×4 地块图集 + 每块的四角地形
web/                       素材网站
scripts/
  pixellab_api.py          PixelLab v2 REST 客户端（API key 只从环境变量读取）
  generate.py              candidates → pick → animate → redo / download
  generate_tilesets.py     生成地块
  postprocess.py           统一画布、镜像出 8 方向、（可选）锁调色板、拼图集、导出 GIF
  sync_species.py          同步物种表
  preview_scene.py         静态预览图（旧，网站实验室已取代）
```

## 生产流程（每个物种）

```bash
export PIXELLAB_API_KEY=pixl_xxx                                   # 不要提交到仓库
python scripts/sync_species.py                                     # 1. 同步物种表
# 2. 新建 prompts/units/<id>.yaml（复制一个现有的改）
python scripts/generate.py candidates prompts/units/<id>.yaml --n 3   # 3. 生成 3 个候选，看 units/<id>/candidates.png
python scripts/generate.py pick prompts/units/<id>.yaml <character_id> # 4. 选定
python scripts/generate.py animate prompts/units/<id>.yaml            # 5. 待机/行走/攻击 × 5 方向（并发）
python scripts/generate.py redo prompts/units/<id>.yaml walk/east     # 6. 不满意的方向单独重做
python scripts/postprocess.py <id>                                    # 7. 处理
```

最后在物种表 K 列打勾，提交并推送；Vercel 会自动部署。

## 生成参数与费用（实测，Tier 2）

| 操作 | 接口 | 消耗 |
| --- | --- | --- |
| 新建 8 方向角色（32px 或 64px） | `create-character-v3`，从文字生成 | 2 次 |
| 动画，每个方向 | `characters/animations`，`mode: v3` | 1 次 |
| Wang 地块（32px，pro 模式） | `create-tileset` | 约 20 次/套 |

每个物种的流程：3 个候选（6 次）+ 待机/行走/攻击 × 5 方向（15 次）+ 重做（0～12 次），约 **21～33 次**。表中现有 30 个物种合计约 1000 次，Tier 2 每月 5000 次足够；同时最多跑 10 个任务。

## 第二轮试做（2026-11-09）

每个体型各做一个物种，都已在物种表 K 列打勾。

| 体型 | 物种 | 画布 | 选中的候选 | 重做 | 消耗 |
| --- | --- | --- | --- | --- | --- |
| 微型 | 古代切叶蜂（3～4 只成群当一个单位，飞行） | 32px | seed 4101 | 攻击·上 | 22 次 |
| 小型 | 撒丁岛巨兔 | 32px | seed 4202 | 行走 ×5、攻击 ×5、攻击·上 ×2 | 33 次 |
| 中型 | 剑齿虎 | 32px | seed 4302 | 无 | 21 次 |
| 大型 | 猛犸象（补齐待机和攻击） | 64px | 试用版 | 攻击 ×5 | 22 次（含试用） |

另做了 3 套地块：雪地/苔原、雪地/水域、雪地/泥地。

### 结论

- **候选机制有效。** 同一提示词的 3 个候选差别很大：剑齿虎有一个直接画成了老虎，蜂有一个只画了一只大蜂。先出候选再挑，是保证质量最划算的一步。
- **蜂群可行。** 一张 32px 图里画 3～4 只蜂，8 个方向一致，动起来像一小群；在实验室里作为飞行单位悬浮，可以越过水面。
- **动作描述要写具体，并写清这个方向能看到什么。**
  - 巨兔第一版的行走和攻击几乎不动；改成"身体明显离地""张嘴露出门牙"之后明显好了。
  - 但同一句描述用在背面时，模型会在背上画出一张嘴；给背面单独写"只看得到背和耳朵"就解决了。生成脚本现在支持 `action_by_dir`，可以按方向单独写描述。
- **大型单位的道具容易变形。** 猛犸象第一版攻击时象牙形状一直在变；在描述里要求"象牙每一帧保持同样形状"之后稳定了。
- **还可以再改进的地方。**
  - 巨兔偏圆，比较像仓鼠，可以在描述里强调更长的身体和后腿。
  - 剑齿虎带条纹；化石证据不支持条纹，但游戏里辨识度更高，保留与否由你决定。
  - 剑齿虎在表中是"大型食肉类"，但按《美术方案》的尺寸表我先做成了中型（32px）；如果想让它更大，可以改成 48px 重做。

### 早期试用（试用账号）

原始人猎人和狼是第一轮试用时做的演示单位，不在物种表中，在网站里标为"演示单位"。人类表格定稿后再正式生成人类单位。
