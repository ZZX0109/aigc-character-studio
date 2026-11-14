# 开源实现可落地性核查（2026-11-14）

仅据作者仓库、官方模型卡、作者网站核查；未下载权重，未完成实际GPU复现。以下“训练可用”仅指公开入口，不代表能在单卡完成。

## 建议

主线建议用 **ConsisID 固定 checkpoint + 新增局部编辑增量分支**，原因是官方提供 train.py、数据处理和评估入口，可冻结底模后开展自己的适配器试验。CogVideoX 较旧是外部竞争力限制，需要用近方法做外部比较；不能因此把不同checkpoint比较冒充控制算法消融。

备选现代路线 **Wan2.1 VACE + Stand-In** 适合先做推理阶段的控制图重组和身份/几何冲突实验。官方 infer_with_vace.py 在同一个VACE pipeline里注入Stand-In，能够对同一VACE checkpoint做有/无Stand-In、有/无编辑条件的消融。Stand-In训练数据、预处理、训练代码在README仍为未完成TODO；trainers目录只有 __init__.py 与 utils.py，因此训练闭环需要自行开发。官方也说明VACE的面部预设偏差可能损伤身份，需调整vace_scale。这个冲突是可研究问题，不是加入两者即获得创新。

FantasyID 必须列最近方法，但现有公开主目录提供推理入口，未发现视频生成训练入口；decalib/utils/trainer.py 属于DECA，不能计为FantasyID训练代码。

预算上，1×A100 80GB作为首轮推理/小适配器容量试验的租用目标合理（工程建议）；不能据推理显存承诺适配器训练可行。先测前向、反向、峰值显存和单样本时间，再决定卡数与训练规模。

## 1. ConsisID

- 官方：https://github.com/PKU-YuanGroup/ConsisID
- 论文：Identity-Preserving Text-to-Video Generation by Frequency Decomposition，CVPR2025。
- 状态：推理、train.py、多机脚本、数据预处理、eval均公开；Diffusers支持。
- 输入：公开infer.py为一个img_file_path，提取id_cond、id_vit_hidden、face_kps；不是任意网格或原生多视角集合接口。
- 可改模块：https://github.com/PKU-YuanGroup/ConsisID/blob/main/models/transformer_consisid.py 中 LocalFacialExtractor、PerceiverCrossAttention、local_facial_extractor、perceiver_cross_attention；https://github.com/PKU-YuanGroup/ConsisID/blob/main/models/pipeline_consisid.py 负责传条件，https://github.com/PKU-YuanGroup/ConsisID/blob/main/train.py 负责训练闭环。
- 官方推理显存：720×480、49帧、8FPS约44GB reserved；CPU卸载等累计优化+VAE tiling表中可到7GB reserved，作者提示变慢且可能降质。这是推理，不能用于训练报价。https://github.com/PKU-YuanGroup/ConsisID#gpu-memory-optimization
- 许可：大多数代码Apache2.0；CogVideoX-5B Transformer独立许可；官方模型卡虽标Apache仍不能忽略底模与人脸模型依赖。https://github.com/PKU-YuanGroup/ConsisID#-license ；https://huggingface.co/BestWishYsh/ConsisID-preview ；https://huggingface.co/zai-org/CogVideoX-5b/blob/main/LICENSE

## 2. FantasyID

- 官方：https://github.com/Fantasy-AMAP/fantasy-id
- 权重：https://huggingface.co/acvlab/FantasyID
- 输入：参考照片 + pcd_path .ply 点云 + prompt，点云可由DECA产生。加入3D几何、多视角外观增强、逐层条件注入均已存在，不能作为新创新。
- 可改模块：https://github.com/Fantasy-AMAP/fantasy-id/blob/main/models/transformer_id.py 、models/vertex_encode.py 、models/projectors.py 、models/face_abstractor.py 、models/pipeline_id.py 。
- 状态：公开推理和点云准备；未发现视频模型训练入口；复现训练需补齐。GPU显存官方明确值未核实。
- 许可：仓库标Apache2.0；DECA、FLAME旧版、CogVideoX依赖需分开审视，不能把整体说成无条件商用。

## 3. Stand-In + VACE

- 官方：https://github.com/WeChatCV/Stand-In
- 论文：https://arxiv.org/abs/2508.07901 （CVPR2026）
- 原版新增约153M参数、Wan2.1 T2V14B适配；另有Wan2.2版与VACE兼容入口。官方模型：https://huggingface.co/BowenXue/Stand-In 。
- 实际代码：https://github.com/WeChatCV/Stand-In/blob/main/infer_with_vace.py 先load_wan_pipe(base_path=args.vace_path,use_vace=True)，再set_stand_in。可改 https://github.com/WeChatCV/Stand-In/blob/main/models/set_condition_branch.py 、models/wan_video_dit.py 、models/attention.py 、models/wan_video_vace.py 、pipelines/wan_video.py 。
- 状态：推理及权重开放；完整训练与数据仍TODO。官方推荐清晰正脸、近中景；大角度不是保真保证。
- VACE输入原生支持控制视频/掩码/参考图；深度、姿态信号可通过预处理进入，三维网格仍需渲染。https://github.com/Wan-Video/Wan2.1#run-vace 。
- 许可：Stand-In代码Apache2；默认下载antelopev2，该预训练人脸模型非商用研究限制需要单独记录。GPU精确显存本次未核实，不应引用社区口碑数字作承诺。

## 4. Wan2.2 Animate

- 官方：https://github.com/Wan-Video/Wan2.2#run-wan-animate
- 权重：https://huggingface.co/Wan-AI/Wan2.2-Animate-14B （模型卡声明Apache2.0；代码Apache2.0）
- 状态：参考图+驱动视频、animation/replacement、官方推理和Diffusers示例；未发现官方训练quickstart。
- 公开Diffusers输入为image、pose_video、face_video；不是直接读取FLAME网格。--refert_num是前一段衔接条件帧数，在Diffusers中对应prev_segment_conditioning_frames，不能解释成多参考视图数量。
- 预处理含yolov10m、ViTPose、可选SAM2和FLUX.1-Kontext-dev，附加依赖需各自记录许可；--use_flux可选，不应把非必要依赖纳入最小原型。https://github.com/Wan-Video/Wan2.2/blob/main/wan/modules/animate/preprocess/UserGuider.md
- Wan2.2-TI2V-5B官方24GB推理要求不能直接套到Animate14B。Animate具体显存需实测。

## 5. 新版 Wan-Animate-2（更新已有方案所必需）

- 官方：https://github.com/Wan-Video/Wan-Animate-2
- 论文：https://arxiv.org/abs/2608.06009
- 权重：https://huggingface.co/Wan-AI/Wan2.2-Animate-2-14B
- 2026-08-07已开放推理和Base/Distillation权重；直接消费驱动视频，支持文本指定视角；代码和模型卡Apache2.0。
- 官方默认配置8×A800跑720P，测试2×A800跑480P；不宜作为单A100第一版默认。未见完整训练入口。模型支持视角控制不等于支持局部形状增量保真。

## 6. HunyuanCustom

- 官方：https://github.com/Tencent-Hunyuan/HunyuanCustom
- 论文：https://arxiv.org/abs/2505.04512
- 单/多图、音频、视频主体定制，不能假定能直接接受3D局部编辑。可作为强主体一致性外部方法。
- 官方推理：720×1280×129帧峰值80GB，512×896×129帧60GB；最小24GB但很慢，推荐80GB。训练入口本次未确认。
- 许可为Tencent Hunyuan Community License，含地域等条件，与Apache2不同。https://github.com/Tencent-Hunyuan/HunyuanCustom/blob/main/LICENSE

## 7. FLAME / 重建器 / 人脸评估

- FLAME官方：https://flame.is.tue.mpg.de/index.html ；许可：https://flame.is.tue.mpg.de/modellicense.html
- 2025-11发布 **FLAME2023 Open，CC-BY-4.0**；旧2017/2019/2020/2023模型与旧Blender插件仍非商用条款。旧2023表达参数到Open的转换：https://github.com/Suraj-Bhor/flame_to_flame_open_converter 。纹理有独立许可，不会自动跟随模型变为CC-BY。
- FLAME表示可分身份形状、表情和关节，适合作为规范坐标；原生PCA系数不是语义局部滑块，需要局部形变或约束求解层。
- DECA https://github.com/yfeng95/DECA 公开训练/推理，官方代码和模型非商用科研；EMOCA https://github.com/radekd91/emoca 同样非商用且官方已标deprecated、转向inferno。用于研究评估可考虑，不建议作为产品长期默认依赖。
- SMIRK https://github.com/georgeretsi/smirk 代码MIT，公开train.py和demo_video.py；但quick_install.sh明确下载FLAME2020并依赖EMOCA情绪模型和MICA，不能因代码MIT就推断所有资产可商用。https://github.com/georgeretsi/smirk/blob/main/quick_install.sh
- InsightFace https://github.com/deepinsight/insightface 代码MIT；官方预训练模型和相应训练数据非商用研究，包括自动下载模型。ArcFace是损失/方法名称，不单独赋予任意权重商用许可。
- LivePortrait https://github.com/KlingAIResearch/LivePortrait 可作为低成本头像动画参考，官方支持Apple Silicon（较4090慢）；不替代广泛场景视频模型，也不保证新侧脸几何正确。

## 8. 最小研发顺序

1. 先在单A10080上分别完成ConsisID原版推理、FantasyID照片+点云推理；固定同一角色编辑对，观测几何条件是否能覆盖旧身份参考。
2. 建立只渲染的几何真值与失败模式记录；检查中性化几何度量是否能准确识别局部修改。
3. 以ConsisID同checkpoint开始局部编辑增量adapter容量试验，只训练新模块；若训练预算不够，先做规范空间条件重组/门控推理方案，不保证有效。
4. 可另起Wan2.1-VACE+Stand-In同checkpoint实验，比较原始控制、目标身份重渲染控制、编辑区域残差控制；这比贸然补完整训练更容易落地。
5. 不同基础模型作为外部对照，报告各自分辨率、帧数、采样预算、输入能力；不把结果差异完全归因于新模块。
