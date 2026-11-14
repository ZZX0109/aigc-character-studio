# Windows 交接与验收

本指南用于在 Windows 11 上恢复当前角色工作台，并准备下一阶段的研究验证。源码仓库：[ZZX0109/aigc-character-studio](https://github.com/ZZX0109/aigc-character-studio)。

以下命令按项目现有文件与接口编写；Windows 实机运行仍待执行确认。当前工作台不需要 CUDA 或视频模型，使用 CPU 完成几何计算、浏览器 WebGL 完成渲染。

## 1. 当前交付范围

| 已实现 | 当前边界 |
| --- | --- |
| 加载扫描示例和本机导入的 FLAME 2023 Open | 仓库不附带 FLAME 权重，需单独从官网下载 |
| 鼻翼局部收窄、加宽，原始对比与调整区域显示 | 仅已审核模板可编辑；身份、表情数组由协议/API 保存，界面尚无完整表演面板 |
| 不可覆盖的角色版本保存、磁盘重载与逐顶点/指纹核验 | 当前 FLAME 重建是零关节姿态，不含完整颌骨、颈部和眼球蒙皮 |
| 单版本五视角 PNG 与网格导出 | 图片为固定材质的三维渲染，尚非 AI 生成照片 |
| 编辑前后成对参考资产导出 | 原始、编辑后各五视角，共十张图；不是十个不同相机角度 |
| 逐顶点编辑差分、区域掩码和导出清单 | 视频生成、身份控制训练及视频自动评测尚未接入 |

两组标准视角均为正面、左右 45°、左右 90°，每图 768×768。成对图共享基准取景、灯光和材质，除 `nose_width` 外身份、表情参数相同。

## 2. 安装环境与取得代码

先安装：

- Git for Windows。
- Python **3.11 x64**，包含 `py` 启动器与 pip。
- Node.js **22.x，至少 22.12**，包含 npm。
- 支持 WebGL 的现代浏览器，例如 Edge 或 Chrome。

打开普通 PowerShell，无需管理员权限。先确认版本：

```powershell
git --version
py -3.11 --version
node --version
npm.cmd --version
```

首次克隆到 Windows 的桌面目录：

```powershell
Set-Location ([Environment]::GetFolderPath("Desktop"))
git clone https://github.com/ZZX0109/aigc-character-studio.git
Set-Location .\aigc-character-studio
```

已有该目录时，直接进入项目根目录，不要重复克隆。以下命令均从包含 `README.md`、`src` 和 `frontend` 的项目根目录开始。

```powershell
py -3.11 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r .\requirements-lock.txt
Push-Location .\frontend
npm.cmd ci
npm.cmd run build
Pop-Location
```

首次安装需要联网。使用虚拟环境内的 Python 和 `npm.cmd`，不需要激活脚本，也不需要修改 PowerShell 执行策略。若任一安装或构建步骤报错，先保留完整错误并处理，再继续下一步。

## 3. 启动与停止工作台

在项目根目录的 PowerShell 中运行：

```powershell
$StudioRoot = (Get-Location).Path
$env:PYTHONUTF8 = "1"
$env:PYTHONPATH = Join-Path $StudioRoot "src"
& .\.venv\Scripts\python.exe -m uvicorn character_studio.api:app --host 127.0.0.1 --port 8765
```

保持此窗口运行，在浏览器打开 [本地工作台](http://127.0.0.1:8765/)。出现默认扫描头模即表示基础页面与几何服务可以工作。首次启动会创建本机数据及模型下载目录，不会恢复 Mac 上已有的个人角色或结果。

在该窗口按 `Ctrl+C` 停止服务。每次新开 PowerShell，都需重新进入项目目录并设置上述环境变量；它们只影响当前窗口。`PYTHONUTF8` 使中文文件在 Windows Python 3.11 中使用统一的 UTF-8 默认编码。端口占用时先关闭重复启动的工作台，避免误连其他进程。Windows 不使用仓库中的 `.command` 或 `.sh` 启动文件。

修改前端源码后，重新执行第 2 节的 `npm.cmd run build` 并刷新页面。当前单端口服务使用 `frontend/dist` 中的构建文件。

## 4. 恢复 FLAME 模型

模型原文件、内部权重及个人生成结果不随代码仓库发布；公开仓库自带的扫描示例可以先独立使用。FLAME 需要按其官方许可单独取得。

1. 打开 [FLAME 官网](https://flame.is.tue.mpg.de/)，选择 **FLAME 2023 Open Model**。也可使用官网当前提供的 [Open 专用下载入口](https://download.is.tue.mpg.de/download.php?domain=flame&sfile=FLAME2023Open.zip)。若官网要求登录，在官方页面完成。旧版本与纹理的许可分别处理，不能替代 Open 文件。[官方模型许可说明](https://flame.is.tue.mpg.de/modellicense.html)
2. 在项目根目录另开 PowerShell，创建下载目录：

   ```powershell
   New-Item -ItemType Directory -Force -Path .\models\flame\inbox | Out-Null
   ```

3. 将下载的 `FLAME2023Open.zip` 放入该目录，无需手动解压。也支持官方 PKL 或受支持的纯数值 NPZ。
4. 工作台中点击“模型与导入”→“扫描下载文件”，选择文件后点击“导入本地模型”。导入完成后返回工作台，在“新角色基础模型”中选择可编辑的 FLAME，再创建角色。

也可先用现有命令行工具导入，再在工作台刷新模型列表：

```powershell
& .\.venv\Scripts\python.exe .\scripts\import_flame.py .\models\flame\inbox\FLAME2023Open.zip
```

已审核模板会自动产生独立校准资产；输出的 `calibration_status` 应为 `ready`。如果显示需校准，只能预览中性头模，应反馈模板信息后重新审核，不应绕过限制。

当前验收所用 ZIP 的 SHA-256 为：

```text
a6b4c3dc15d569d98136a1e548b6fe532eb2830ca12a4f0d4b3a5dba8ee87a91
```

本机查看下载文件指纹：

```powershell
Get-FileHash -Algorithm SHA256 .\models\flame\inbox\FLAME2023Open.zip
```

官网下载内容若更新，指纹可能变化；保留实际指纹与导入输出。当前可编辑性依据模板及拓扑精确匹配判断，不按文件名或顶点数量推断。详细约定见 [FLAME 导入与局部编辑](docs/architecture/flame-import.md) 及 [第三方署名](THIRD_PARTY_NOTICES.md)。

## 5. 工作台验收

按顺序执行并记录结果：

1. **基础加载**：确认扫描示例可见，拖动旋转，检查五个标准视角；页面没有持续报错。
2. **FLAME 创建**：导入官方 Open 文件，选择已校准 FLAME，新建角色。当前模板应为 5,023 顶点、9,976 三角面。
3. **鼻翼编辑**：将“鼻翼宽度”设为 `-0.5`，使用“鼻部近看”“调整区域”“对比原始”，确认鼻翼收窄。再试 `0`、`+0.5`，应能回到原始与加宽；最后恢复 `-0.5`。参数刻度不等于百分比，以当前锚点量测为准。
4. **保存重载**：点击“保存并重载验证”，确认校验通过；刷新页面并重新加载该角色，确认参数与外形保留。再保存应产生新版本，已有版本保留。
5. **成对导出**：点击“导出编辑前后对照包”。解压 `paired-character-bundle.zip`，检查 `baseline/views` 与 `edited/views` 各五张 PNG，并打开 `contact-sheet.png` 对照正面、斜侧面和侧面。两组应保持相同取景，鼻翼变化与界面一致。
6. **几何与记录**：确认包中两组均有 `mesh.json`、`mesh.obj`、`character.json`，根目录有 `delta.json`、`manifest.json` 与 `verification.json`。核验应通过，原始与编辑后网格存在对应的局部差分；这些文件不包含原始 FLAME blendshape 权重。

工作台会把角色版本保存在 `data/characters/<角色ID>/revisions`，成对结果保存在 `data/characters/<角色ID>/pair-exports/<导出ID>`。浏览器下载的 ZIP 也可独立查看。上述文件属于本机结果，默认被 Git 排除。

几何核验覆盖参数重建与导出协议，不自动证明渲染图中的面部内容正确。鼻翼定位、编辑可见性、视角和取景仍需完成目视检查。

## 6. 运行现有测试

在项目根目录的 PowerShell 执行，可与工作台运行窗口分开：

```powershell
$env:PYTHONUTF8 = "1"
$env:PYTHONPATH = Join-Path (Get-Location).Path "src"
& .\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

通过标准为无 `FAIL` 或 `ERROR`。请保留结尾的运行数量、`OK` 和 `skipped` 信息：

- 未下载官方 ZIP 时，真实模型回归会明确跳过。
- 未导入当前验收用的真实校准资产时，真实 FLAME API 测试类会跳过；其固定资产 ID 对应上述 ZIP 与现有校准。即使其他封装导入成功，也应记录该跳过原因。
- 合成夹具测试只验证数值、文件及异常路径，不代替真实模型或浏览器渲染验收。
- Windows 当前会话若没有创建符号链接的权限，符号链接拒绝测试会以 `WinError 1314` 原因跳过；无需为运行工作台开启管理员权限。请一并记录该跳过项。

可选：查看现有研究任务清单，不写入结果：

```powershell
& .\.venv\Scripts\python.exe .\scripts\make_manifest.py --dry-run --summary
```

此命令只预览实验计划，不生成视频；清单中的其他编辑类型也不表示已在工作台实现。

反馈问题时请附上当前提交号、Python/Node 版本、失败步骤、完整报错末尾及测试跳过原因。浏览器问题另附页面错误信息，模型问题附下载文件 SHA-256、导入输出与校准状态。

```powershell
git rev-parse --short HEAD
```

## 7. 核实 NVIDIA 显卡资源

当前工作台无需为此安装 CUDA。为决定后续视频实验配置，在 Windows PowerShell 中执行：

```powershell
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv
```

记录完整输出，核实此前口述的“RTX 4060、4GB”。以 NVIDIA 专用显存为准，不累加 AMD 集显显存或 Windows 共享内存。若命令不可用，先从 NVIDIA 官方渠道检查驱动，再报告显卡型号与专用显存。

不要依据“编辑器运行正常”推断视频模型或训练能运行。[ConsisID 官方显存优化表](https://github.com/PKU-YuanGroup/ConsisID#gpu-memory-optimization) 给出的低显存方案依赖卸载等配置，仅能作为后续推理试验参考；速度、质量与本机兼容性仍需实测。确认本机容量和小规模前向成本后，再选择本机试跑或租用云端 GPU；本轮不启动付费实验。

## 8. 下一阶段研究任务（尚待开发）

下面是下一批工具与实验的开发顺序，当前仓库尚无对应一键运行脚本，也尚未产生视频实验结果。视频模型应使用独立环境，避免与本工作台的依赖混装。

1. **参考输入可用性检查**：对本次导出的灰模参考图运行目标方法的人脸检测、对齐与身份特征提取，同时用其官方真人样例作对照，记录失败率。先确认输入能进入模型，再讨论生成保真；灰模可被人识别为脸，不代表预训练检测器一定接受。
2. **FantasyID 几何编码响应检查**：固定同一外观参考，分别输入未编辑与横向鼻翼编辑后的几何，比较下采样顶点和几何编码的差异。当前本地鼻翼编辑只改变 X；[作者公开的 `vertex_encode.py`](https://github.com/Fantasy-AMAP/fantasy-id/blob/main/models/vertex_encode.py) 中，`VertexSpiralNet.forward` 的深度位置编码使用 `coarse_vertices[:, :, 2:]`。因此仅交换这类几何可能无法改变该编码路径，必须做数值实验确认，不能先把它当作有效控制或已经成立的创新结论。
3. **几何接口对齐**：确认目标方法使用的 FLAME 版本、顶点顺序、坐标系、尺度与表情条件。本工作台坐标经过固定中心与尺度规范化，不能把导出网格直接当成作者要求的原生点云；转换需保留对应关系并验证往返误差。
4. **小规模视频基线**：在前两项通过后，固定 checkpoint、随机种子、提示词及采样预算，先跑少量编辑对。记录局部编辑是否兑现、未编辑区域是否漂移、转头/表情是否完成，再决定局部 XYZ/差分条件分支与训练试验。现阶段不承诺在本机完成视频模型训练。

研究背景与候选路线见 [开源核查](docs/research/open-source-audit.md)、[技术路线](docs/architecture/technical-route.md) 和 [创新与评测细节](docs/research/novelty-evaluation.md)。正式实验需锁定第三方代码与权重版本，并记录各自许可及输入失败样本。
