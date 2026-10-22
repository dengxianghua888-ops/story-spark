# 拾篇 · Story Spark

> 质量优先的"爆款神髓复刻"短篇仿写系统。输入一篇爆款短篇,提取读者心理引擎、爽点因果链、情绪债、文风 DNA 与反转机制,产出接近番茄爆款标准的改编作品。

---

## 架构概览

```
source.md
   ↓ Phase 1 · Dissector (解构师)
   ↓   · genre 题材检测(6 枚举)
   ↓   · Beat Sheet(含反转机制字段)
   ↓   · Style DNA(含金句密度)
   ↓   · Soul Contract(读者承诺/情绪债/爽点因果链)
   ↓   · Reader Engine + Tension Ledger + Platform Fit
   ↓
dissection.md + analysis/*
   ↓ Phase 2 · Adapter (改编师)
   ↓   · 3 套方案 + reversal_preservation_check + V4 神髓评分矩阵
   ↓   · blueprint.md(每 Beat 机制执行要点 + 读者状态/情绪债/信息差)
   ↓
adaptation.md + blueprint.md
   ↓ Phase 3 · Writer (写手)
   ↓   · 切片循环 + 读者心理操控 + 照镜子 + 跨篇 few-shot 检索
   ↓   · 按 genre 动态违禁词 + 金句密度对齐
   ↓
draft.md
   ↓ Phase 4 · Editor (审校师) · C0 神髓保真 + 5 Critical + 5 Important
   ↓   C0 神髓禁改项 100% 通过
   ↓   C1 情绪曲线 ≥85% | C2 文风 DNA ≥85% | C3 重复率 ≤5%
   ↓   C4 AI 味(全局+genre 专属=0) | C5 反转机制 100% 保真
   ↓   review.md 的 yaml gate block + quality-report.json 双轨一致
   ↓   I1 节奏 | I2 叙事 | I3 Hook ≥7/10 | I4 金句密度 ±15% | I5 番茄卡点密度
   ↓   (FAIL → 自动回 Phase 3 + draft-v{n}.md 备份, 最多重试 3 次)
   ↓
review.md + diff.md + quality-report.json
   ↓ Phase 5 · Finalizer (定稿师)
   ↓   · 违禁词终扫 · 金句锐度 · 机制收尾 · 番茄章节切分 · story.yaml
   ↓
final.md + craft-notes.md + final-chapters/ + tomato-submission.md + story.yaml
```

所有阶段支持 **human-in-the-loop** 和 `--auto`。V4 的质量门以 `quality-report.json` 和 `review.md` 顶部 yaml gate block 为准,不再 grep 自然语言 PASS。

## Production 产线(V5)

V4 仍保留用于兼容历史 stories。新生产默认使用 `--mode production`,目标是稳定生成番茄短故事投稿稿,不再依赖模型自报 PASS。

```
Market Brief
  ↓ market-brief.json
Source Dissection
  ↓ story-brief.json + analysis/*
Adaptation Room
  ↓ adaptation-room.json + adaptation.md
Beat Bible
  ↓ beat-bible.json + scene-cards/*.json
Scene Writer
  ↓ draft-scenes/*.md + draft.md
Critic Gauntlet
  ↓ 四路 evaluation/*.json + quality-report.json
Final Packager
  ↓ final.md + final-chapters/*.md + tomato-submission.md + story.yaml
Feedback Learning
  ↓ feedback-learning.json
```

Production 硬门槛:

- `production`: 10000-18000 字;`ultra_short`: 6000-9000 字。
- 每章 500-1200 字,`final-chapters/_chapters-map.md` 中章末钩覆盖率必须 100%。
- 每 3500 字至少 1 个付费级卡点,从 `beat-bible.json`/`scene-cards/*.json` 的 `paywall_card` 机器统计。
- `final.md` 必须直接可投:标题后有 `导语：` 开篇导语,正文一句一段,章末自然付费卡点不写内部标记。
- `tomato-submission.md` 必须包含 `付费节点地图（直接投稿版）`,节点数不少于 `ceil(正文字符数/3500)`。
- 连续 source overlap >120 字、硬违禁词、软违禁超限、动作密度过低都会直接失败。
- `quality-report.json` 自报 pass 但机器指标失败时,产线以机器指标为准。

运行:

```bash
./pipeline.sh --story stories/my_project --mode production --auto --runner agent --no-human-gates
./pipeline.sh --story stories/my_project --mode ultra_short --auto --runner agent --no-human-gates
python3 scripts/validate-production-story.py --story stories/my_project --phase 7 --mode production
```

---

## 目录

```
短篇仿写/
├── README.md                       本文件
├── workspace.yaml                  全局配置(genre_profiles / tomato / quality_gate)
├── pipeline.sh                     5 阶段编排(V4, 带硬质量门/runs 日志/自动返工)
├── context.md                      人类摘要笔记入口
├── context/                        跨案例结构化沉淀
│   ├── forbidden-words-learned.json
│   ├── mechanism-playbook.json
│   ├── style-dna-stats.json
│   └── README.md
├── prompts/
│   ├── dissector.md                V4 系统提示(加神髓合约/读者引擎/情绪债)
│   ├── adapter.md                  V4
│   ├── writer.md                   V4
│   ├── editor.md                   V4 (加 C0 + quality-report.json)
│   ├── finalizer.md                V4 (加 story.yaml + 投稿包闭环)
│   └── patterns/                   机制/Hook/标题/词库(产线核心)
│       ├── reversal-mechanisms.md  8 大机制 M1-M8
│       ├── hook-types.md           4 种 Hook H1-H4
│       ├── title-formulas.md       5 种标题公式 + 古言对仗式
│       └── forbidden-and-preferred.md  按 genre 分层词库 + 金句模板
├── templates/
│   ├── beat-sheet-template.md
│   ├── blueprint-template.md
│   ├── adaptation-template.md
│   ├── soul-contract-template.md
│   ├── reader-engine-template.md
│   ├── tension-ledger-template.md
│   ├── platform-fit-template.md
│   ├── quality-report-template.json
│   ├── story-manifest-template.yaml
│   ├── tomato-submission-template.md
│   └── style-dna-{genre}.md × 6    题材级文风基线模板
├── scripts/
│   ├── build-corpus.sh             从普通 txt 目录导入初始爆款到 corpus/
│   ├── import-corpus-zips.py       从微信/Windows ZIP 批量导入 txt 并按内容去重
│   ├── update-corpus-index.py      扫 dissection.md 生成 _index.json
│   ├── aggregate-style-stats.py    聚合 style-dna.md 到 stats.json
│   ├── validate-story.py           V4 产物完整性与状态校验
│   ├── validate-quality-report.py  V4 双轨质量门校验
│   ├── check-style-metrics.py      文风/违禁词机器指标
│   ├── repair-style-stats.py       修复 style stats 百分比漂移
│   ├── backfill-v4-analysis.py     为已解构 corpus 生成 machine_draft 爆款基因
│   ├── corpus-health.py            corpus 覆盖度/机制/基因健康报告
│   ├── prepare-human-calibration.py 人工校准候选选择与清单生成
│   ├── apply-human-calibration.py  审核通过后升级为 human_calibrated
│   └── batch-run.sh                批跑 corpus-phase1 或多 stories 完整产线
├── corpus/                         爆款参考库 (跨篇 few-shot)
│   ├── _manifest.tsv               slug ↔ filename 映射
│   ├── _index.json                 结构化索引(genre/mechanism/hook/字数)
│   └── {slug}/
│       ├── source.md
│       ├── dissection.md           (seed 7 篇已完成)
│       └── analysis/
└── stories/                        仿写项目
    └── hermes_bag/                 V4 升级后的参考案例
        ├── source.md / dissection.md / analysis/* / adaptation.md
        ├── blueprint.md / draft.md / review.md / final.md / craft-notes.md
        └── runs/{timestamp}/       每次跑批的阶段日志
```

---

## 核心概念(V4)

### 爆款神髓合约(Soul Contract)

V4 新增最高约束,产物为 `analysis/soul-contract.md`。它锁定:

- 读者承诺:读者期待获得的爽感/痛感/反转/补偿
- 情绪债:前半压迫如何累积,后半必须如何清算
- 爽点因果链:施害者如何种因,主角如何用同一规则反杀
- 道德坐标:读者为什么站主角,反派违反了哪条规则
- 主角姿态:隐忍/冷静/疯感/破釜沉舟/克制复仇
- 神髓禁改项与可替换项

缺少 `soul-contract.md`、`reader-engine.md`、`tension-ledger.md` 或 `platform-fit.md` 时,V4 pipeline 直接失败。

### 题材(Genre)6 枚举
每个 genre 有独立的 `style-dna-{genre}.md` + `genre_profiles.{genre}.extra_forbidden` + 偏好词库:

| genre | 典型代表 |
|-------|---------|
| `modern_reversal` | 海关说我的破包是爱马仕 / 成为高考状元却接到断亲书 |
| `ancient_BE` | 残梦不暖九冬寒 / 我死后老公亲手解剖了我的尸体 |
| `ancient_sweet` | 盼我流年花满蹊径 / 相府假千金一事无成 |
| `apocalypse_heroine` | 末世让我滚出基地后所有人都死了 / 她代号深渊 |
| `family_ethics` | 老公给我妈下药后我杀疯了 / 我每月给女儿四千 |
| `urban_sweet_ceo` | 瞒着老公空降公司 / 磕到了钓系总裁他撩疯了 |

### 反转机制(Mechanism)M1-M8

| ID | 名 | 典型识别信号 |
|----|----|------|
| **M1** | 死环反杀 | 二选一逻辑陷阱 + 盖章文书反向使用 |
| **M2** | 身份反差爆发 | 前期隐瞒 + 多层揭身份 + 递进崩塌 |
| **M3** | 因果回旋反讽 | 施害者金句被原结构句回敬 |
| **M4** | 灵魂线视角 | 前 20% 死亡 + 后续灵魂观看 + 信息差爆炸 |
| **M5** | 温度反转曲线 | 对方的爱→冷漠→负值绝望(三段式) |
| **M6** | 多层递进反转 | 3+ 层反转,每层升维,间隔 15-20% 字数 |
| **M7** | 降维打击 | 两套规则 + 跃迁事件 + 旧武器失效 |
| **M8** | 道德模糊结尾 | 赢了但失去,结尾留白,静止物象 |

详见 `prompts/patterns/reversal-mechanisms.md`。

---

## 常用命令

### 新仿写项目

```bash
mkdir stories/my_project
cp /path/to/source.txt stories/my_project/source.md

# 手工模式(默认): 每个 Phase 卡住等你在另一个 Claude 会话里粘 prompt
./pipeline.sh --story stories/my_project

# 自动模式: Python 状态机 + agent runner
./pipeline.sh --story stories/my_project --auto

# 指定 runner: agent / codex / openclaw / claude / mock / local-ollama
./pipeline.sh --story stories/my_project --auto --runner agent

# 离线回归: 不依赖外部 API
./pipeline.sh --story stories/my_project --runner mock --no-human-gates

# 从 Phase 3 恢复(手工或自动都支持)
./pipeline.sh --story stories/my_project --phase 3
./pipeline.sh --story stories/my_project --phase 3 --auto

# 预演不执行
./pipeline.sh --story stories/my_project --dry-run
```

`--phase` / `--from-phase` 和 `--to-phase` 必须处于所选模式的阶段范围:
`v4` 为 1–5,`production` / `ultra_short` 为 1–8,`production_v6` 为 1–9。
CLI 参数解析仅接受 1–9 的整数;超出该全局范围或非整数会以退出码 2 拒绝。
解析通过后再校验模式范围与阶段顺序:超出模式上界或结束阶段早于开始阶段时,
在原文授权检查与创建运行日志前以退出码 11 拒绝,不会截断范围或记录为已完成。

**手工模式 vs 自动模式**:

| 模式 | 怎么工作 | 适合 |
|------|---------|------|
| 手工/接力 | `manual-prompt-pack` 生成 phase prompt 包,由人工或外部 agent 接力 | 想精细控制每一步 / 不跑自动 provider |
| `--auto` | 调 `scripts/storyforge.py` Python 状态机,默认 runner=`agent` | Agent 优先自动跑 |
| `mock` | 从 `tests/fixtures/mock-runs` 输出 artifact bundle | CI / 回归测试 / 离线验证 |
| `local-ollama` | 显式调用本机 Ollama | 有足够本地模型资源时 |

Agent runner 默认 provider 优先级为 `codex -> openclaw -> claude -> manual-prompt-pack`。所有 provider 都必须输出 artifact bundle,由脚本统一解析、落盘和验证。

`corpus-picker.py` 新建的故事默认写入 `source_policy.access: denied`。
使用外部 runner 前需由用户明确批准该故事的原文访问;选样不会继承或生成审批,也不会更改已存在故事的原文与授权。
默认拒绝时,实际执行 `agent` / `codex` / `openclaw` / `claude` 会以退出码 30 停止。
`mock` 和 `manual-prompt-pack` 仍可用于离线验证或生成人工接力材料。
`--dry-run` 只在故事的 `runs/` 目录生成本地 prompt 与运行清单,不会启动 runner,
因此无需源文外发批准,也不会修改源文授权。生成的 prompt 含输入内容,按原文相同规则保管。
新故事先在同父目录的私有 `.故事名.picker-*` 暂存目录写入拒绝策略,再复制原文和选样卡;
全部完成后才用不覆盖目标的原子目录改名发布。写入、中断或发布失败会保留暂存副本,
重试会创建新候选;既有故事(包括缺少 manifest 的兼容故事)及并发出现的目标均保持原样。
新发布故事保留暂存目录的 0700 权限,适用于同一用户运行产线;既有目录权限不变。
失败暂存副本同样为 0700 且被 Git 忽略,仍应按原文隐私规则保管;这里不承诺同用户隔离或掉电持久性。
发布依赖 Linux `renameat2(RENAME_NOREPLACE)` 或 macOS `renamex_np(RENAME_EXCL)`;
不支持的平台或文件系统会报错并保留暂存副本,不会退回覆盖式发布。

`scripts/batch-run.sh --mode random-batch --runner agent` (或 `codex` / `openclaw` / `claude`)
选样后会先检查整批原文授权。任一故事为 `denied` 时,打印全部固定选中路径、待批准路径和逐个恢复命令,
以退出码 30 停止;不会启动任何故事 runner 或生成质量完成报告。请人工核查原文访问批准后,
对打印的固定路径使用 `storyforge.py run` 命令继续,保留默认人工阶段门;不要重新随机选样。
脚本不会替用户批准或修改任何故事的授权。默认 `manual-prompt-pack` 与显式 `mock` 保持离线批跑流程。

### 批量建 corpus few-shot 库

```bash
./scripts/build-corpus.sh                             # 从普通 txt 目录导入初始库
./scripts/import-corpus-zips.py path/to/*.zip          # 批量导入微信/Windows ZIP,自动去重
./scripts/batch-run.sh --mode corpus-phase1           # 逐篇跑 dissector
python3 scripts/update-corpus-index.py                # 刷索引
python3 scripts/aggregate-style-stats.py              # 聚合文风统计
python3 scripts/backfill-v4-analysis.py               # 为已解构样本补 machine_draft V4 基因
python3 scripts/update-corpus-index.py                # 回填后再次刷新爆款基因索引
python3 scripts/prepare-human-calibration.py --overwrite
python3 scripts/corpus-health.py                      # 查看人工校准缺口
# 人工填完 corpus/{slug}/analysis/human-calibration.md 后:
python3 scripts/apply-human-calibration.py --slug hermes_customs_package
python3 scripts/update-corpus-index.py
```

### 批量仿写

```bash
./scripts/batch-run.sh --mode stories-full --stories stories/a stories/b stories/c
```

### 定位跨篇 few-shot

```bash
python3 -c "
import json
with open('corpus/_index.json') as f: d = json.load(f)
for e in d['entries']:
    if e.get('genre')=='ancient_BE' and 'M4' in e.get('reversal_mechanisms',[]):
        print(e['slug'], '→', e['source_path'])
"
```

---

## 质量闸门(V4)

```
C0 爆款神髓禁改项 100% 通过                AND
C1 情绪曲线 ≥ 85%                        AND
C2 文风 DNA ≥ 85%                         AND
C3 原文重复率 ≤ 5%                        AND
C4 全局违禁词=0 + genre 专属违禁=0         AND
C4 情绪物理化覆盖 ≥ 80%                   AND
C5 所有反转机制 checklist 项 100% 通过
→ `gate_status: pass`

任一 Critical 维度未达标
→ `gate_status: fail` → 自动回 Phase 3, draft 备份为 draft-v{n}.md, 重试计入日志
达到 max_retries_per_phase (默认 3) → 人工介入
```

V4 质量门只读取机器结构:

```yaml
gate_status: pass|fail
critical_failures: []
important_failures: []
```

该 yaml block 必须位于 `review.md`,并与 `quality-report.json` 一致。可手动校验:

```bash
python3 scripts/validate-quality-report.py --story stories/my_project
python3 scripts/validate-story.py --story stories/my_project --phase final
python3 scripts/check-style-metrics.py --story stories/my_project --json
python3 scripts/corpus-health.py
```

---

## 从 V3 升级到 V4 的变更

| 维度 | V3 | V4 |
|------|-----|-----|
| 仿写核心 | Beat Sheet + Style DNA + M1-M8 机制 | 新增 Soul Contract,锁定读者承诺、情绪债、爽点因果链 |
| 解构深度 | 拆结构、题材、机制 | 拆读者心理引擎、情绪债账本、番茄平台适配 |
| 改编方式 | 换设定并保机制 | 神髓等价映射,每套方案必须有保真/新鲜/共鸣/逻辑/平台评分 |
| 写作方式 | 逐 Beat 生成 | 逐 Beat 操控读者状态,禁止空 Beat |
| 质量门 | Editor 自评 + 自然语言 PASS/FAIL | `review.md` yaml gate block + `quality-report.json` 双轨校验 |
| 定稿资产 | final + craft-notes + 投稿包 | 额外沉淀可复用题材映射、机制漂移风险、`story.yaml` 状态 |
| corpus 索引 | 案例索引 | 爆款基因索引,新增 reader_promise / emotional_debt_type / payoff_pattern 等字段 |

---

## 故障排查

| 症状 | 原因 | 修复 |
|------|------|------|
| Phase 4 反复 FAIL | 机制流失 / 违禁词遗留 | 看 diff.md 的 C4/C5 细报,按要点改 draft.md |
| 古言改编出现"手机/公司" | genre 专属违禁未加载 | 检查 blueprint.md 是否引用了 `workspace.yaml::genre_profiles.ancient_BE.extra_forbidden` |
| 改编后爽感弱 | M3 回旋金句漏了 | finalizer Step 2g 机制收尾验证, 结尾段补回旋 |
| 文风漂移 | 跨篇 few-shot 未启用 | writer 切片循环 Step 2.5 检索 corpus/_index.json |
| `--auto` 所有 provider 都失败 | Codex/OpenClaw/Claude 不可用或鉴权失败 | 查看 `runs/<id>/phaseN.*.provider.log`,使用生成的 `manual-prompt-pack` 接力 |
| `mock` runner 失败 | fixture 缺失或 artifact bundle 不合规 | 查看 `phaseN.parse-report.json`,修复 `tests/fixtures/mock-runs` |
| artifact bundle 不合规 | 输出了未授权路径、缺文件或空文件 | 重新执行该 phase,确保只输出 `<<<FILE: ...>>>` 文件块 |
| Phase 2 后暂停 | 真实来源默认需要 blueprint 人工 gate | 审阅 `adaptation.md`/`blueprint.md`,再用 `storyforge.py approve-gate` 放行 |

---

## License / 原文版权

`corpus/` 与 `stories/` 下的 source.md 为第三方爆款原文,仅作仿写学习 few-shot 参考,**不得分发**。`.gitignore` 已默认排除这些原文文件。

### Optional scene continuity evidence

The split scene writer can use a human-maintained, position-scoped fact ledger.
Plans and candidates are kept separate from reviewed earlier facts; source
revisions invalidate affected context. See [scope, format and limitations](docs/scene-continuity.md).
This opt-in pilot is tested with synthetic counterexamples, not a claim of
improved literary quality.

### 审批快照与安全续跑

蓝图审批现在绑定候选内容、上游输入、提示词、校验规则和模型配置；变更后需要明确重审。
`--resume` 仅复用输入一致、产物指纹一致且重新校验通过的阶段，旧 `approved` 不会自动升级为历史审批。
分场入口也支持 `--approval-run-id`。操作示例与兼容边界见 [审批快照说明](docs/approval-snapshots.md)。
