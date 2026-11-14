# AIGC Character Studio

基于可编辑三维角色的 AI 视频身份控制研究与开发项目。

编辑器、资产管理与参考渲染在本机运行；视频研究环境单独配置，可在核实显存后使用 Windows NVIDIA 电脑或云端 GPU。

当前已实现扫描头模与 FLAME 2023 Open 两类角色：本地模型导入、鼻翼局部调整、原始对照、版本保存与重载核验、单版本五视角导出，以及编辑前后十张成对参考图和几何差分导出。FLAME 身份与表情参数分开保存，当前按零关节姿态重建；视频生成、完整骨骼驱动与身份控制训练尚未接入。

## 阅读顺序

1. [Windows 安装、启动与研究交接](WINDOWS_HANDOFF.md)
2. [调研结论与候选创新](docs/research/2026-11-14-review.md)
3. [技术路线与里程碑](docs/architecture/technical-route.md)
4. [开源实现及资源核查](docs/research/open-source-audit.md)
5. [近邻论文核查笔记](docs/research/closest-papers.md)
6. [创新与评测细节](docs/research/novelty-evaluation.md)
7. [结构化论文目录](docs/research/papers.json)

## 当前决策

优先研究“数值局部编辑在视频扩散中的可靠传递”。下一步先检查灰模参考的人脸检测与身份编码，再验证 FantasyID 的几何编码是否响应横向鼻翼编辑；这些检查工具尚待开发。通过输入兼容性验证后，再安排 ConsisID / FantasyID 视频基线，后续以固定 checkpoint 做同底模消融。Wan2.2 Animate 用于后续工程集成；Stand-In + VACE 是备选。候选方法是否有效需要实验判断。

## 启动角色编辑器

[Windows 用户请按交接文档操作](WINDOWS_HANDOFF.md)。以下快捷启动方式用于已经安装依赖的 macOS 环境。

在 Finder 中打开本项目，双击“启动角色工作台.command”，待终端显示地址后打开：

http://127.0.0.1:8765

或者在本项目目录运行：

    ./scripts/start_studio.sh

角色、渲染与核验均在本机完成，不需要视频模型或云 GPU。关闭启动它的终端，或按 Control+C，可停止服务。

## 使用流程

1. 从左侧加载已有角色。新建时可在“新角色基础模型”中选择扫描头模或 FLAME 2023 Open。
2. 调整“鼻翼宽度”滑块或数值；“鼻部近看”“调整区域”和“对比原始”帮助检查范围。负值收窄，正值加宽；参数刻度不等于百分比，界面另显示本模型锚点宽度的实际变化。
3. 点击“保存并重载验证”，从磁盘读取保存参数，重新构建全部顶点并核对形状指纹。每次保存产生新版本；旧版文件保留。
4. 点击“导出编辑前后对照包”：先保存，再以同一身份、表情和取景，渲染原始鼻翼与修改后鼻翼各五张768×768 PNG。也可选择“仅导出当前角色包”保留原有五视角单包流程。

导出目录：data/characters/<角色ID>/exports/<导出ID>/，包含五张PNG、contact-sheet.png、mesh.obj、mesh.json、character.json、manifest.json与verification.json。图片是固定灯光的三维渲染，不是AI生成照片。ZIP包含来源署名与许可信息。

成对导出目录：data/characters/<角色ID>/pair-exports/<导出ID>/。baseline与edited各含五张PNG、mesh.json、mesh.obj、character.json；根目录有delta.json（逐顶点变化与区域掩码）、manifest.json、verification.json、两行对照总览与paired-character-bundle.zip。两组参数除nose_width外完全一致，图片共享基准模型的相机取景、缩放、灯光和材质。几何校验不等于自动识别图片内容；实际渲染另经浏览器目视检查。

## FLAME 模型导入

开发验收使用了[官方 Open 专用入口](https://download.is.tue.mpg.de/download.php?domain=flame&sfile=FLAME2023Open.zip)的真实模型；验收时该入口无需登录。仓库不提供 FLAME 权重，每台新机器需要单独下载和导入。验收使用的可编辑资产 ID 为 flame2023-open-a6b4c3dc15d569d9-cal-a3717f2607be；其他下载封装可能产生不同 ID。

导入其他机器上的下载文件时：

1. 从官方入口下载 FLAME 2023 Open，把ZIP、PKL或数值NPZ放入 models/flame/inbox。
2. 工作台点击“模型与导入”→“扫描下载文件”→“导入本地模型”。也可运行：

       .venv/bin/python scripts/import_flame.py models/flame/inbox/FLAME2023Open.zip

3. 已审核的模板自动获得单独的鼻翼校准资产。不同模板可中性预览，但在重新校准前禁用鼻翼编辑；扫描头模的遮罩不跨拓扑复用。

FLAME提供300维身份、100维表情；保存文件记录完整参数、源文件与校准标识、几何指纹和顶点快照。此轮支持零关节姿态的参数化重建，未实现颌骨、颈部和眼球的完整蒙皮。当前界面聚焦鼻翼编辑，身份/表情数组由角色协议和API保存，不提供完整表演编辑面板。

模型原文件与内部权重均留在 models/flame，并排除在代码版本管理之外；目录会在首次启动或导入时创建。参考包包含派生网格和参数，不含原始PKL或blendshape基。规范坐标不是毫米。详见[FLAME导入说明](docs/architecture/flame-import.md)、[扫描资产说明](docs/architecture/face-asset.md)和[第三方署名](THIRD_PARTY_NOTICES.md)。

## 首次重建开发环境

Windows 请使用 [Windows 交接步骤](WINDOWS_HANDOFF.md)。macOS / Linux 从项目根目录执行以下步骤；建议 Python 3.11、Node.js 22.x（至少 22.12），项目最低 Python 版本为 3.10。

    python3 -m venv .venv
    .venv/bin/python -m pip install -r requirements-lock.txt
    cd frontend
    npm ci
    npm run build
    cd ..
    ./scripts/start_studio.sh

源网格与原始许可保存在项目内。需要验证离线转换时运行 python3 scripts/prepare_face_asset.py。首次安装依赖需要联网，日常运行无需联网。

开发前端可在后端运行时另执行 frontend 中的 npm run dev；5173端口会将API转发到8765。修改前端后，单端口启动方式需要重新运行 npm run build 并刷新页面。

## 验证与研究工具

    PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
    python3 scripts/make_manifest.py --dry-run --summary

单元及集成测试覆盖几何局部性、端点折面、磁盘保存重建、不可覆盖旧版、损坏检测及导出包校验。API测试的普通PNG夹具只验证文件协议；真实三维渲染通过浏览器操作另行检查。

扫描头模首版本地验收：53项测试通过，前端构建通过；实际浏览器完成创建角色、逐字符输入−0.5、鼻翼区域近看、保存重载与五视角导出。样例变化180个顶点，区域外位移0，9,279个顶点重载后完全一致。

FLAME 集成本地验收：102项检查通过（含12项真实FLAME API检查），前端构建通过；浏览器完成模型发现/导入、创建FLAME角色、鼻翼编辑、保存重载、十张成对参考导出。样例参数−0.5使119个鼻翼顶点改变，锚点跨度约−9.775%，区域外/鼻尖/鼻梁位移0；全部5,023个顶点重载后完全一致。

以上为开发机的历史验收记录。角色档案、PNG、ZIP 和 `outputs/` 中的核验样例均是本地生成产物，不随仓库分发；请用上述流程在新机器上重新生成。没有本地 FLAME 模型时，相关真实模型测试会明确跳过，合成夹具测试仍可运行。Windows 实机验收尚待执行。

公开发布前另用不含权重和现有依赖的源码副本，在 macOS 上完成全新安装验证（Python 3.10.10、Node.js 24.13.0）：`unittest` 输出 90 项、2 项跳过，其余通过；缺失真实模型导致跳过的 API 测试类还包含 12 项未执行检查。前端干净安装、构建、依赖审计均通过。Vite 已固定到 7.3.8，以纳入 [官方安全修复](https://github.com/vitejs/vite/security/advisories/GHSA-p4f5-76q4-ffq7)。

研究试验清单为 data/manifests/pilot.jsonl。dry-run只查看计划。去掉 --dry-run 可写入新清单；更新已有清单需显式指定 --overwrite。54个视频任务仍是研究计划，不能当作已生成视频。

## 目录职责

| 路径 | 职责 |
| --- | --- |
| frontend | React、TypeScript、Three.js 本地角色编辑器 |
| src/character_studio | 几何内核、角色版本存储、FastAPI服务 |
| backend | 服务入口说明 |
| src / scripts / schemas | 共享协议与研究工具 |
| configs | 可复现实验配置 |
| research/baselines | 外部方法复现记录，当前预留 |
| research/benchmarks | 数据划分、动作轨迹与评测定义，当前预留 |
| research/experiments | 模块消融与实验记录，当前预留 |
| models | 模型文件的本地缓存，不纳入版本管理 |
| data | 角色、生成结果、试验清单 |
| docs | 调研证据与研发决策 |

研究代码与视频服务应独立环境；不向系统 Python 批量安装模型依赖。不把模型权重、用户照片、访问密钥或生成视频提交到代码仓库。

## 许可与分发

项目自有代码暂未指定许可证。仓库附带的扫描示例资产按 CC-BY-3.0 分发，依赖及单独下载的 FLAME 模型分别适用其自身条款，详见 [第三方署名](THIRD_PARTY_NOTICES.md)。
