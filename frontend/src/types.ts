export type Vertex = [number, number, number];
export interface FaceMesh {
  vertices: Vertex[];
  faces: [number, number, number][];
  edit_weights?: number[];
  face_target?: Vertex;
  geometry_hash?: string;
  bounds?: unknown;
}
export interface Character {
  id: string;
  name: string;
  revision: number;
  nose_width: number;
  geometry_hash?: string;
  updated_at?: string;
  asset_name?: string;
  base_asset_id?: string;
  identity_params?: number[];
  expression_params?: number[];
}
export interface AssetInfo {
  asset_id?: string;
  name?: string;
  asset_kind?: string;
  available?: boolean;
  calibration_status?: string;
  can_edit_nose?: boolean;
  license?: string;
  license_url?: string;
  source_url?: string;
  attribution?: string;
}
export interface AssetInventory {
  assets: AssetInfo[];
  flame_status: {
    available: boolean;
    download_url: string;
    inbox_directory: string;
    message: string;
  };
}
export interface ModelCandidate { path: string; name: string; size: number }
export interface Metrics {
  changed_vertices?: number;
  outside_max_displacement?: number;
  nose_width_measure?: number;
  baseline_nose_width?: number;
  [key: string]: unknown;
}
export interface CharacterDocument {
  character: Character;
  mesh: FaceMesh;
  metrics: Metrics;
  geometry_hash: string;
  preview_nose_width?: number;
  is_saved?: boolean;
  bounds?: unknown;
  asset?: AssetInfo;
}
export interface Verification {
  passed: boolean;
  vertex_match?: boolean;
  hash_match?: boolean;
  max_vertex_error?: number;
  vertex_count?: number;
  report_path?: string;
  frontend_reload_match?: boolean;
}
export interface ExportResult {
  id: string;
  download_url: string;
  output_directory: string;
  views: { name: string; url: string; yaw_degrees?: number }[];
  contact_sheet_url?: string;
}
export interface PairedReference {
  character: Character;
  baseline: CharacterDocument;
  edited: CharacterDocument;
  pair_id: string;
  same_identity_expression: boolean;
}
export const VIEWS = [
  { name: 'front', label: '正面', yaw_degrees: 0 },
  { name: 'left45', label: '左侧 45°', yaw_degrees: -45 },
  { name: 'right45', label: '右侧 45°', yaw_degrees: 45 },
  { name: 'left90', label: '左侧面', yaw_degrees: -90 },
  { name: 'right90', label: '右侧面', yaw_degrees: 90 },
] as const;
export type RenderedView = { name: string; yaw_degrees: number; png_base64: string };
