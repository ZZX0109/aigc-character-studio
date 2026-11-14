# FLAME Open 导入与局部编辑

此模块实际导入了官网 FLAME2023Open.zip，完成了 5,023 顶点、9,976 三角面的真实模型重建与鼻翼编辑。它不把现有扫描头模或测试夹具当作 FLAME。

## 模型取得与来源

官网首页的 FLAME 2023 Open 专用链接在本次访问中可直接下载，无需登录：

- [官网](https://flame.is.tue.mpg.de/)
- [本次使用的 Open 下载入口](https://download.is.tue.mpg.de/download.php?domain=flame&sfile=FLAME2023Open.zip)
- [模型许可](https://flame.is.tue.mpg.de/modellicense.html)

本次 ZIP SHA-256：a6b4c3dc15d569d98136a1e548b6fe532eb2830ca12a4f0d4b3a5dba8ee87a91。

FLAME 2023 Open 与旧版 FLAME、纹理和重建器的许可分别处理。本模块的模型许可元数据仅适用于从官方取得的 Open 文件；任意文件不会因命名为 Open 就被认定为有官方来源。原始 ZIP 与转换后的权重保存在被版本管理排除的 models/flame 内。

## 导入与文件协议

从项目根目录运行：

    .venv/bin/python scripts/import_flame.py models/flame/inbox/FLAME2023Open.zip

支持官方参数字典 .pkl、纯数值 .npz，以及含唯一 Open 模型文件的 ZIP。某些 .pkl 实为 NumPy scalar-object 容器，也走受限读取路径。压缩包只读出选定文件，不按内部路径解压，因此压缩包成员不能写到项目外。

读取 pickle 只允许 NumPy 数值容器，以及官方字典可能包含的 SciPy 稀疏矩阵类型；任意其他全局对象拒绝。没有 chumpy 或任意 pickle.load 的后备路径。内部 model.npz 只保存纯数值数组，运行时用 allow_pickle=False 读取。文件大小、数组维度、索引范围和非有限值均检查。该限制读取器用于官方模型格式，不是面向所有恶意文件的资源隔离执行环境。

每个导入目录的 ID 含源文件 SHA，目录内有 model.npz 与 metadata.json。重新导入相同文件复用已有资产，不覆盖原权重。鼻翼校准产生带 calibration hash 的新资产 ID，父资产不修改。每次重建都检查模型文件 SHA；解压后的只读数组最多缓存三个模型，避免每次拖动滑块重复解压。

## 参数化重建

模型提供 v_template、f 和 shapedirs。依据 FLAME 作者实现的字段布局，前 300 个分量为身份，300 起的 100 个分量为表情。表达形式为：

    vertices = template + identity_basis × identity_parameters
                        + expression_basis × expression_parameters

此式对应零关节姿态的 blendshape 重建。本轮没有宣称实现完整颌骨、颈部、眼球的线性蒙皮或面部动作追踪。默认身份与表情系数为零；数组不足维度以零填充，保存时输出完整 300/100 维参数，避免后续版本误读。身份和表情分支有独立回归测试。

规范坐标保留 FLAME 的 Y 向上、脸朝 +Z，按中性模板总高度固定为 3，并固定平移中心。身份和表情变化不会重新归一化全脸。规范单位不是毫米。重建结果量化到 9 位小数，生成规范 JSON 的几何 SHA；这支持相同环境中保存参数后的逐顶点重建核验。

字段布局依据：[作者 FLAME 实现](https://github.com/soubhiksanyal/FLAME_PyTorch/blob/master/flame_pytorch/flame.py)、[官网链接的 Open 表情转换代码](https://github.com/Suraj-Bhor/flame_to_flame_open_converter)。本项目独立实现数值导入和零姿态重建，没有复制完整第三方渲染器。

## 鼻翼校准

扫描头模的坐标遮罩没有移植到 FLAME。先查看真实 FLAME 的正面、侧面及鼻部三角面投影，再定义鼻翼区域；模板图像已经实际审核。

仅对精确匹配已审核 template hash 和 topology hash 的模型，自动应用当前校准。不同模板即使有 5,023 个顶点，也仅允许中性预览，非零鼻翼编辑会返回“需校准”。新的校准需要 reviewed、审核说明、基础网格 hash、逐顶点权重、两个鼻翼锚点、鼻尖/鼻梁保护点及局部最大位移。

当前已审核模板：

- 模板 hash：db4aaf1d3d326dc64c0870d7163d7a483f1c884f896729085f4e345afe219432
- 拓扑 hash：acc81fdfa47ffc281248e6d150cf5be96042021539213c70f4b1c64696a69fed
- 鼻翼锚点：2762、1645；两者位于实际鼻翼外侧，规范 Y 约 0.122、Z 约 0.94。
- 121 个支持顶点；参数 ±0.5 时有 119 个顶点在量化后发生变化。
- 参数范围 [-1,1]，两侧局部最大位移为 0.025 规范单位；±0.5 的鼻翼锚点跨度约 ±9.775%，端点约 ±19.551%。
- 鼻尖、鼻梁保护点与区域外位移严格为 0。负值收窄、正值加宽；鼻翼编辑从未修改的当前身份/表情网格计算，绝不累积上次形变。

校准两端均检查三角面相对未编辑网格的法线方向；运行时还会对当前身份、表情及调整量做同样检查，出现折面则拒绝，不悄悄夹断参数。它不是完整的三维自交检测。当前手工校准是特定模板的工程定义，不是临床解剖真值。

## 接口

- import_model(path, root=None) 返回可用资产元数据。精确匹配的已审核模板会返回校准后的派生资产。
- list_assets(root=None) 默认隐藏明确标记的合成测试夹具。
- get_asset_info(asset_id, root=None) 返回来源、维度、许可及校准状态。
- build_geometry(asset_id, nose_width=0, identity_params=None, expression_params=None, root=...) 返回 positions、indices、mask_weights、参数、边界、几何指纹和编辑量测。
- calibrate_asset(asset_id, calibration, root=None) 创建不可覆盖的校准派生版本。

实际已导入可编辑资产为 flame2023-open-a6b4c3dc15d569d9-cal-a3717f2607be。该 ID 包含源文件与校准版本；其他下载封装可能产生不同源 ID，模板匹配仍可复用审核过的校准。

## 验证范围

test_flame.py 包含 16 项小型合成夹具测试与 1 项真实模型回归。夹具用于验证格式、数值分离、局部不泄漏、重建一致性、校准版本不可覆盖、异常文件和受限反序列化；它们标记为非真实模型，并不显示在正常资产列表。

真实模型回归检查官方源文件导入、真实顶点/面数量、鼻翼锚点位置、收窄/加宽单调性、区域外与保护区零变化。浏览器中的实际取景、鼻部近看和成对图像内容，仍须通过工作台的人工可视验收。
