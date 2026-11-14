# 最接近论文核查笔记

核查日期：2026-11-14。以下仅依赖作者论文、会议论文集、作者主页和官方仓库。检索不等于穷尽文献；“未找到专项实验”不等于方法不能完成任务。

## 关键结论

“三维形状控制生成视频”“局部改脸后传播到视频”“用数值滑块编辑指定五官且保护无关特征”分别已有明确前作。比较稳妥的研究目标应是：**对可编辑三维身份实施局部干预，在多姿态、多表情和独立生成镜头中，同时获得目标几何保真、非目标身份特征保持和自然动态。** 创新主张需落到新机制及相应联合验证，不能只落到产品流程。

## 1. FantasyID：最直接的形状编辑视频前作

- 标题：FantasyID: Face Knowledge Enhanced ID-Preserving Video Generation。
- 时间：arXiv v1，2025-02-19，2502.13995。
- 来源：[论文全文](https://arxiv.org/html/2502.13995v1)、[作者项目](https://fantasy-amap.github.io/fantasy-id/)、[官方仓库](https://github.com/Fantasy-AMAP/fantasy-id)。
- 方法：从 DECA 得到去除姿态、表情的身份形状点云；融合二维外观和三维顶点特征；多视角增强缓解复制静态脸；采用分层自适应身份注入。
- **直接证据：Fig.3 图注明确展示改变面宽和下颌锐度后，生成视频的面部结构随之变化。** “把可编辑 3D 形状送入视频模型”因此已有先例。
- 评估：参考身份和帧间 ArcFace 相似度、脸部 FID、运动量及用户评价。本文可见部分没有针对鼻翼/眼距等多个局部参数建立“指定变化量—实际变化量—非目标部位泄漏—多镜头”专项联合评估；这属于待实验验证的机会。
- 开放状态：代码、推理入口和模型权重链接已公开，仓库 Apache-2.0；本次可见目录主要是推理与模型实现，未把完整训练复现视为已验证。论文整体训练配置为 16 A100、约 36 小时，不能默认可用单卡复现。

## 2. ViDS：逐帧三维几何与表演分离的最新近邻

- 标题：ViDS: Video Diffusion Shader using 3D Face Tracking。
- 时间：arXiv v1，2026-07-27，2607.24124；截至核查日应称预印本，不推断录用。
- 来源：[论文](https://arxiv.org/html/2607.24124v1)、[项目页](https://fusheng-ji.github.io/ViDS/)。
- 方法：以 Pixel3DMM 获取 FLAME 形状、姿态与表情；固定源身份形状，仅从驱动视频转移姿态和表情；把逐帧法线图、参考图及噪声潜变量拼接送入 Wan，使用多条件 CFG；长视频采用重叠窗口和固定前缀。
- 证据：形状参数消融说明使用驱动者形状会改变比例和轮廓；替换为参考人物形状恢复身份几何。已有“固定身份、改变表情姿态”和稠密法线引导，不能再把此原则本身列为贡献。
- 边界：主要是肖像重演。项目主要展示姿态/表情、身份形状替换，并非用户鼻翼编辑量跨独立场景的专项校准。
- 开放状态：项目页本次仅见论文入口，未确认官方代码或权重。论文采用 CC BY-NC-SA，不能从论文许可推断代码/权重可商用。

## 3. ConsisID：成熟的身份视频基线

- 标题：Identity-Preserving Text-to-Video Generation by Frequency Decomposition。
- 时间：arXiv 2411.17440，2024-11；CVPR 2025 Highlight。
- 来源：[项目页](https://pku-yuangroup.github.io/ConsisID/)、[官方仓库](https://github.com/PKU-YuanGroup/ConsisID)、[CVPR 论文](https://openaccess.thecvf.com/content/CVPR2025/papers/Yuan_Identity-Preserving_Text-to-Video_Generation_by_Frequency_Decomposition_CVPR_2025_paper.pdf)。
- 方法：以低频全局比例和高频身份细节进行分层控制，基于 CogVideoX 的 DiT。
- 用途：作为“整体身份保持好，但是否遵守指定局部编辑”基线；并不提供直接的三维局部形状约束接口。
- 开放：官方实现、权重、数据和推理生态可得。推理时不需要对每个人单独微调，不代表整套方法无需训练。

## 4. ControlFace：参考外观与目标形状冲突的直接参考

- 标题：ControlFace: Harnessing Facial Parametric Control for Face Rigging。
- 时间：arXiv 2412.01160；CVPR 2025。
- 来源：[CVPR 论文](https://openaccess.thecvf.com/content/CVPR2025/papers/Jang_ControlFace_Harnessing_Facial_Parametric_Control_for_Face_Rigging_CVPR_2025_paper.pdf)、[官方仓库](https://github.com/cvlab-kaist/ControlFace)、[项目页](https://cvlab-kaist.github.io/ControlFace/)。
- 方法：双 U-Net 分离参考人脸编码与生成，Control Mixer 编码目标与参考控制的关系，Reference Control Guidance 增强对目标条件的遵守。
- **直接证据：官方推理明确有 pose/expression/light/shape 模式。** 论文也讨论只做重建训练容易让模型复制参考图而忽略控制。
- 用途：适合做局部编辑后参考图准备或图像级强基线；其公开示例是图像 rigging，不能直接视为跨镜头视频算法。
- 开放：代码和权重下载脚本可见。完整训练和所有依赖许可仍需复现时核查。

## 5. FG-Portrait：三维对应关系与可编辑表演

- 标题：FG-Portrait: 3D Flow Guided Editable Portrait Animation。
- 时间：2026-03-24，arXiv 2603.23381；CVPR 2026。
- 来源：[论文](https://arxiv.org/html/2603.23381v1)、[会议版](https://openaccess.thecvf.com/content/CVPR2026/papers/Xu_FG-Portrait_3D_Flow_Guided_Editable_Portrait_Animation_CVPR_2026_paper.pdf)。
- 方法：从统一参数头模型计算目标到源的三维流，用深度引导采样关联二维像素，以 3D flow ControlNet 条件帮助动画；支持推理时指定表情和姿态。
- 关系：三维表面对应、姿态变化与表情控制已有成熟路线。局部编辑区域可以借用相同拓扑的对应关系，但“用 3D flow 对齐”本身不能当新贡献。
- 边界：论文强调姿态/表情编辑，未将局部身份形状编辑与独立镜头联合评估作为主问题。
- 开放状态：在本次核查的摘要和全文页未确认官方代码/权重；应标“未确认”，不写“没有开源”。

## 6. ConsID-Gen：2026 的多视图几何视频基线

- 标题：ConsID-Gen: View-Consistent and Identity-Preserving Image-to-Video Generation。
- 时间：2026-02-10，arXiv 2602.10113；CVPR 2026。
- 来源：[项目](https://mingyang.me/ConsID-Gen/)、[论文摘要](https://arxiv.org/abs/2602.10113)、[官方仓库](https://github.com/eBay/ConsID-Gen)。
- 方法：首帧加两张未标定辅助视图，视觉–几何双编码器与多模态连接器，面向一般物体的多视角身份保持；另有 ConsIDVid 数据及评测。
- 开放：仓库已列推理、训练代码及 checkpoint；基于 Wan2.1-Fun-1.3B-InP 和 VGGT-1B。可作为同类底模的多视图几何基线，但一般物体分数不能替代人脸五官编辑评估。
- 关系：“多视图 + 几何编码改善视频身份”已有强前作。新增法线/参考图数量不足以单独支撑创新。

## 7. Pixel-Perfect Puppetry / FlowGuide：局部语义编辑与保护其他属性

- 标题：Pixel-Perfect Puppetry: Precision-Guided Enhancement for Face Image and Video Editing。
- 时间：ICLR 2026。
- 来源：[ICLR 正式论文页面](https://proceedings.iclr.cc/paper_files/paper/2026/hash/f54bd48aba0dff7acdac86123188f1b6-Abstract-Conference.html)、[官方代码](https://github.com/yl4467/flow_edit)。
- 方法：在 U-Net 中间表征中估计重建和编辑语义方向，利用方向几何关系形成自适应掩码，保护与编辑无关的身份成分。
- 用途：作为后处理/已有视频局部编辑分支参考；提示我们“区域掩码 + 保护原身份”的一般思想已有，不宜包装为全新。
- 边界：这是语义图像和视频编辑，不等同于三维滑块几何数值在新镜头中的可测保持。官方仓库命名 FlowEdit、论文称 FlowGuide，引用时应注明，避免与其他同名 FlowEdit 混淆。

## 8. UP-FacE：数值滑块和非目标特征保护已有前作

- 标题：UP-FacE: User-predictable Fine-grained Face Shape Editing。
- 时间：arXiv 2403.13972，2024-03-20；作者还公开了 2026 workshop 版本文档，需区分预印本与发表版。
- 来源：[arXiv](https://arxiv.org/abs/2403.13972)、[作者论文](https://www.collaborative-ai.org/publications/strohm26_cvprw.pdf)、[补充](https://www.collaborative-ai.org/publications/strohm26_cvprw_sup.pdf)。
- 方法：landmarks 定义 23 个语义脸型数值；通过编辑方向缩放达到目标值，用 semantic face feature loss 保护不相关属性；有滑块式界面。
- 关系：“用户预期的精细变化量”“修改一个特征保护其他无关特征”不是新问题。可借其思想建立视频指标，但需要解决视角投影和表情本身影响形状测量的问题。
- 开放状态：本次未核实官方可运行代码和权重。

## 补充清单：更早的人脸视频形状编辑传播

### Identity-Aware and Shape-Aware Propagation of Face Editing in Videos

- 作者：Yue-Ren Jiang、Shu-Yu Chen、Hongbo Fu、Lin Gao。
- 年份：2023 online，TVCG 30(7):3444–3456，2024；DOI 10.1109/TVCG.2023.3235364。
- 来源：[作者机构条目](https://scholars.cityu.edu.hk/en/publications/identity-aware-and-shape-aware-propagation-of-face-editing-in-vid/)、[作者全文 PDF](https://hongbofu.people.ust.hk/doc/Identity-aware%20and%20Shape-aware%20Propagation%20of%20Face%20Editing%20in%20Videos%20-%20TVCG%202023.pdf)。
- 内容：StyleGAN2 潜空间解耦外观、形状、表情、运动，三维参数监督使单帧形状编辑传播到其余帧。属于已拍摄视频编辑，不能简单拿来解决独立生成镜头，但足以否定“首次三维形状编辑跨帧传播”的主张。

### DeepFaceVideoEditing: Sketch-based Deep Editing of Face Videos

- 年份：SIGGRAPH 2022 / ACM TOG 41(4), Article 167。
- 来源：[官方代码](https://github.com/IGLICT/DeepFaceVideoEditing)、[论文](https://scholars.cityu.edu.hk/files/132514346/3528223.3530056.pdf)。
- 内容：草图局部改脸，按基础形状、表情驱动或局部时间窗传播，区域感知融合多项编辑；基于 StyleGAN3，有公开代码、模型链接和样例。
- 边界：需对输入视频做对齐、反演/PTI 与编辑传播。适合作为相关工作或修复路线参考，完整迁移到现代视频 DiT 需要额外研究。

## 据此可做的研究假设（尚待实验，不能宣称已有优势）

1. **局部三维身份差分条件与外观保护的冲突处理。** 同时输入编辑前后几何、三维局部位移、投影区域和可见性；对目标区域让更新后几何优先，对区域外保留角色外观。必须对比“同底模 + 法线条件 + 普通掩码”，证明差分与冲突解耦本身有效。参考图中的旧鼻形不应通过强身份约束把新鼻形拉回去。
2. **姿态/表情去混淆的编辑剂量保持。** 在规范静止坐标系定义改鼻翼等身份编辑，再随相同表情、姿态变形；评估的是编辑前后输出的局部差分与目标差分，而不是直接比较动态二维宽度。先校准独立重建评估器自身误差，再讨论训练损失。
3. **遮挡后再现及独立镜头的局部编辑记忆。** 将局部身份细节保存在角色三维/UV资产中；不可见时降低几何约束，再可见时从角色标准恢复。需要和普通姿态门控、可见性加权、固定参考库比较，才能判断有无额外价值。
4. **把三目标联合评测做扎实。** 同一人物编辑前后配对、相同动作与随机种子、未见身份/未见编辑强度/未见镜头分离测试；联合报告目标编辑误差、非目标泄漏、自然表演与跨镜头保持；ArcFace 只作辅助。此基准有潜力，但数据与指标本身也需与上述前作区别，不能只重命名常见指标。

## 实验解释的边界

- 不同模型间的排名说明系统效果，不足以说明自研模块增益；核心消融必须在同一底模、相同条件可用性与生成预算下。
- 不能把修改后人脸与修改前 ArcFace 相似度最大化当唯一目标；明显的身份形状编辑本来就会改变识别特征。
- 二维区域外像素完全不变并非合理目标：鼻子改形可能改变邻近遮挡和投影边界；应使用几何对应或设计允许影响带。
- 自拍/肖像重演、已有视频编辑、任意场景独立视频生成三类任务要分别报告，不能把其中一个任务的成功直接外推到全部。
