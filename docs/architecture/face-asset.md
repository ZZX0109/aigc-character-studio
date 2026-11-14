# 首版人脸资产与鼻翼局部编辑

首版使用 Lee Perry-Smith / Infinite-Realities 的真实头肩扫描，而非程序球体或 FLAME 替身。来源是 three.js r180 官方示例目录，许可证为 CC-BY-3.0。源 GLB、原始许可证和转换后的网格均保存在 data/base-face。

本文记录扫描头模的首版实现。后续已通过官网首页的 Open 专用链接取得真实 FLAME，并单独实现参数化重建和鼻翼校准，见[FLAME导入说明](flame-import.md)。这里的扫描头模仍不含身份/表情空间或照片重建能力，其局部掩码不能移植到其他拓扑。

## 来源和可复现性

- [源网格](https://github.com/mrdoob/three.js/blob/r180/examples/models/gltf/LeePerrySmith/LeePerrySmith.glb)
- [随模型附带的许可证](https://github.com/mrdoob/three.js/blob/r180/examples/models/gltf/LeePerrySmith/LeePerrySmith_License.txt)
- [CC-BY-3.0](https://creativecommons.org/licenses/by/3.0/)
- 源 GLB SHA256：402b8a8ac9f03232e6d64b5962929703a069daf99d3c49ac8eb0e48bedc9c576
- 许可证 SHA256：7cf4da43a6ae6d32f7f7d063fe129a19468af6f4fe7c53b937f83959709fcb50
- 作者归属：Infinite, 3D Head Scan by Lee Perry-Smith / Infinite-Realities；由 three.js r180 分发。

预处理只解析固定校验值的 glTF 2.0 JSON 与二进制数组，不执行 pickle。运行 python3 scripts/prepare_face_asset.py 可从已保留的源文件离线重新生成相同 JSON；显式 --download 才会重新下载并校验固定来源。运行时无 numpy、GPU 或网络依赖。

转换保留 9,279 顶点、17,684 三角面的拓扑与 UV。坐标为右手系、Y 向上、脸朝 +Z；应用源节点缩放后，将头肩整体中心归零、总高度统一为 3。该规范单位不是毫米，也不能用于临床或物理尺寸结论。bounds、face_target 和 source_to_canonical 保存在资产中。

## 参数及局部范围

nose_width 取值 [-1, 1]，0 精确恢复基准；负值收窄，正值加宽。它是变形强度，不直接等于变化百分比。stats.nose_width_change_ratio 才是基于本资产两个鼻翼锚点跨度的实际变化比例。

每次计算从不可变基准网格出发，使用左右对称的紧支撑平滑权重，只改变鼻翼附近顶点的 X 坐标。鼻尖中央、最前端和鼻梁被保护，区域外的顶点、Y/Z 坐标和三角面索引完全不变。紧支撑边界与保护区边界使用二阶连续衰减，避免硬切掩码。扫描本身略有左右不对称，编辑场保持镜像对称，但不会强制把原始人脸对称化。

这是针对固定扫描人工定义并检查的鼻翼区域，不是自动语义分割。锚点宽度也只是工程量测，不是临床鼻翼边界。当前变形版本为 nasal-ala-anatomical-support-v2。鼻翼定位经前视与侧视网格投影复核：权重峰值及宽度锚点位于规范 Y 约0.33–0.42、Z 约0.80–0.91的实际鼻孔两侧鼻翼。已将早期偏下偏外的鼻唇沟坐标排除，并加入负例顶点回归。支持182个顶点；极小边界位移经过9位小数量化可能为零，参数±0.5时实际改变180个顶点，应以 changed_vertices 的实测值为准。

## 对接接口

load_base_asset() 返回独立副本；get_asset_info() 返回轻量元数据；build_geometry(nose_width=0.0) 返回：

- positions 与 indices：嵌套的三维坐标和三角面数组；uvs 为二维纹理坐标。
- mask_weights：与顶点等长的鼻翼编辑权重。
- geometry_hash、base_geometry_hash、topology_hash：规范 JSON 的 SHA256。
- stats：实际变化顶点数、局部最大位移、区域外/鼻尖/鼻梁最大位移、鼻翼锚点宽度与变化比例。
- bounds、face_target、unit、parameters、asset_id、deformation_version 与归属元数据。

保存应同时记录资产 ID、源哈希、变形版本、参数、形状哈希和必要快照。重新加载后从相同基准重建，再逐顶点及哈希比较；仅“参数文件能读回来”不足以证明形状没变。

## 已覆盖的验证

测试覆盖源文件校验值、离线转换可复现、零编辑精确恢复、区域外严格零变化、鼻尖/鼻梁保护、双方向单调响应、编辑场对称、支撑边界平滑、鼻翼峰值及锚点位置回归、旧鼻唇沟负例排除、异常参数拒绝、保存/重载参数后的逐顶点与哈希一致，以及返回值修改不会污染基准。参数端点也检查全部三角面相对基准的法线方向与非退化性；位移幅度已限为鼻翼锚点跨度约±17.4%的范围（参数±0.5时约±8.7%），避免过度收窄导致局部折面。该检查不是完整自交检测，不能据此保证任意拓扑上的安全形变。
