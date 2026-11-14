# 本地服务

当前服务实现在 src/character_studio/api.py，避免前后端各自定义一套几何逻辑。

使用项目 scripts/start_studio.sh 启动，默认仅监听127.0.0.1:8765。生产构建的前端也由该服务提供。

接口：GET /api/characters、GET /api/characters/{id}、POST /api/preview、POST /api/characters、POST /api/characters/{id}/verify、POST /api/exports。详细字段可在服务启动后查看 /docs。

参数预览不保存；保存追加不可覆盖版本；导出必须引用已保存的revision和匹配的geometry_hash。重新加载核验会从磁盘读取参数和顶点快照，而非复用前端预览结果。

FLAME / 配对接口：GET /api/assets、POST /api/flame/discover、POST /api/flame/import、GET /api/characters/{id}/pair、POST /api/pair-exports，以及成对包和总览下载。导入只读取models/flame/inbox内文件；现有扫描角色不会自动换模型。

角色协议新增identity_params（最多300）、expression_params（最多100）和受限asset_metadata。旧schema1缺少这些字段时只在内存补默认值，不改旧文件；保存新版本时继承身份与表情参数。基础模型或拓扑变化需新建角色。
