import { useCallback, useEffect, useRef, useState } from 'react';
import { ArrowDownToLine, ArrowRight, Box, Check, ChevronRight, CircleCheck, Eye, FolderOpen, Info, Layers3, LoaderCircle, MoveHorizontal, Plus, RefreshCw, RotateCcw, Save, ScanFace, ShieldCheck, SlidersHorizontal, X } from 'lucide-react';
import Viewport from './Viewport';
import ParameterNumberInput from './ParameterNumberInput';
import AssetManager from './AssetManager';
import { post, request } from './api';
import { renderViews } from './scene';
import type { AssetInventory, Character, CharacterDocument, ExportResult, FaceMesh, PairedReference, RenderedView, Verification } from './types';
import { VIEWS } from './types';

const DEFAULT_NAME = '初始角色';
function messageOf(error: unknown) {
  const message = error instanceof Error ? error.message : '操作没有完成，请重试。';
  return /fetch|network/i.test(message) ? '无法连接本地角色服务，请确认服务已启动后重试。' : message;
}
function signed(value: number, precision = 2) { return `${value > 0 ? '+' : ''}${value.toFixed(precision)}`; }
function hashOf(doc: CharacterDocument) { return doc.geometry_hash || doc.character.geometry_hash || doc.mesh.geometry_hash || ''; }

export default function App() {
  const [characters, setCharacters] = useState<Character[]>([]);
  const [saved, setSaved] = useState<CharacterDocument | null>(null);
  const [document, setDocument] = useState<CharacterDocument | null>(null);
  const [originalMesh, setOriginalMesh] = useState<FaceMesh | null>(null);
  const [name, setName] = useState(DEFAULT_NAME);
  const [noseWidth, setNoseWidth] = useState(0);
  const [loading, setLoading] = useState(true);
  const [previewing, setPreviewing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [verifying, setVerifying] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [pairExporting, setPairExporting] = useState(false);
  const [pairExportResult, setPairExportResult] = useState<ExportResult | null>(null);
  const [inventory, setInventory] = useState<AssetInventory | null>(null);
  const [inventoryError, setInventoryError] = useState('');
  const [selectedAssetId, setSelectedAssetId] = useState('');
  const [showAssetManager, setShowAssetManager] = useState(false);
  const [error, setError] = useState('');
  const [status, setStatus] = useState('');
  const [showOriginal, setShowOriginal] = useState(false);
  const [showRegion, setShowRegion] = useState(false);
  const [focusNose, setFocusNose] = useState(false);
  const [yaw, setYaw] = useState({ degrees: 0, sequence: 0 });
  const [verification, setVerification] = useState<Verification | null>(null);
  const [exportResult, setExportResult] = useState<ExportResult | null>(null);
  const [thumbnails, setThumbnails] = useState<RenderedView[]>([]);
  const [thumbnailError, setThumbnailError] = useState('');
  const operation = useRef(0);
  const dirty = !!saved && (Math.abs(noseWidth - saved.character.nose_width) > 0.000001 || name.trim() !== saved.character.name);
  const busy = loading || saving || verifying || exporting || pairExporting;
  const isFlame = !!document?.asset?.asset_kind?.toLowerCase().includes('flame');
  const canEditNose = !!document && (document.asset?.can_edit_nose ?? (!isFlame || ['reviewed', 'calibrated', 'ready'].includes(document.asset?.calibration_status || '')));
  const metrics = document?.metrics;
  const currentHash = document ? hashOf(document) : '';
  const measure = metrics?.nose_width_measure;
  const baselineMeasure = metrics?.baseline_nose_width;
  const widthChange = typeof measure === 'number' && typeof baselineMeasure === 'number' && baselineMeasure > 0 ? (measure / baselineMeasure - 1) * 100 : null;
  const changedVertices = typeof metrics?.changed_vertices === 'number' ? metrics.changed_vertices : 0;
  const outsideMax = typeof metrics?.outside_max_displacement === 'number' ? metrics.outside_max_displacement : null;

  const listCharacters = useCallback(async () => {
    const result = await request<{ characters: Character[] }>('/api/characters');
    setCharacters(result.characters);
    return result.characters;
  }, []);

  const listAssets = useCallback(async () => {
    try {
      const result = await request<AssetInventory>('/api/assets');
      setInventory(result); setInventoryError('');
      setSelectedAssetId(previous => result.assets.some(asset => asset.asset_id === previous && asset.available !== false)
        ? previous : result.assets.find(asset => asset.available !== false)?.asset_id || '');
      return result;
    } catch (err) { setInventoryError(messageOf(err)); throw err; }
  }, []);

  const applySaved = useCallback((doc: CharacterDocument) => {
    setSaved(doc); setDocument(doc); setName(doc.character.name); setNoseWidth(doc.character.nose_width);
    setShowOriginal(false); setVerification(null); setExportResult(null); setPairExportResult(null);
  }, []);

  const loadCharacter = useCallback(async (id: string) => {
    const serial = ++operation.current;
    setLoading(true); setError(''); setStatus('正在加载角色…'); setOriginalMesh(null);
    try {
      const doc = await request<CharacterDocument>(`/api/characters/${encodeURIComponent(id)}`);
      if (serial !== operation.current) return;
      applySaved(doc);
      if (doc.character.nose_width === 0) setOriginalMesh(doc.mesh);
      else {
        const base = await post<CharacterDocument>('/api/preview', { character_id: id, nose_width: 0 });
        if (serial === operation.current) setOriginalMesh(base.mesh);
      }
      if (serial === operation.current) setStatus('角色已从本地档案加载。');
    } catch (err) { if (serial === operation.current) setError(messageOf(err)); }
    finally { if (serial === operation.current) setLoading(false); }
  }, [applySaved]);

  const initialize = useCallback(async () => {
    setLoading(true); setError('');
    // Model inventory failure must not hide existing, loadable scan characters.
    void listAssets().catch(() => undefined);
    try {
      const list = await listCharacters();
      if (list.length) await loadCharacter(list[0].id);
      else {
        const doc = await post<CharacterDocument>('/api/characters', { name: DEFAULT_NAME, nose_width: 0 });
        applySaved(doc); setOriginalMesh(doc.mesh); await listCharacters(); setLoading(false);
      }
    } catch (err) { setError(messageOf(err)); setLoading(false); }
  }, [applySaved, listAssets, listCharacters, loadCharacter]);

  useEffect(() => { void initialize(); }, [initialize]);

  useEffect(() => {
    if (!saved) return;
    if (Math.abs(noseWidth - saved.character.nose_width) < 0.000001) {
      setDocument(saved); setPreviewing(false); return;
    }
    const controller = new AbortController();
    setPreviewing(true); setVerification(null);
    const timer = window.setTimeout(async () => {
      try {
        const next = await post<CharacterDocument>('/api/preview', { character_id: saved.character.id, nose_width: noseWidth }, controller.signal);
        if (!controller.signal.aborted) { setDocument(next); setError(''); setPreviewing(false); }
      } catch (err) {
        if (!controller.signal.aborted) { setError(messageOf(err)); setPreviewing(false); }
      }
    }, 110);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [noseWidth, saved]);

  useEffect(() => {
    if (!document?.mesh) return;
    let cancelled = false;
    const timer = window.setTimeout(async () => {
      try {
        const views = await renderViews(document.mesh, 224);
        if (!cancelled) { setThumbnails(views); setThumbnailError(''); }
      } catch { if (!cancelled) setThumbnailError('缩略图暂不可用；请确认浏览器支持 WebGL。'); }
    }, 220);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [document?.mesh]);

  async function persistCurrent(): Promise<CharacterDocument> {
    if (!saved) throw new Error('请先加载角色。');
    if (!name.trim()) throw new Error('请为角色填写名称后再保存。');
    if (!dirty) return saved;
    setSaving(true); setStatus('正在保存角色参数与三维形状…');
    try {
      const doc = await post<CharacterDocument>('/api/characters', { name: name.trim(), nose_width: noseWidth, source_character_id: saved.character.id, expected_revision: saved.character.revision });
      applySaved(doc); await listCharacters();
      setStatus('角色已保存到本地，修改拥有独立版本。');
      return doc;
    } finally { setSaving(false); }
  }

  async function save() {
    setError('');
    try { await persistCurrent(); if (!dirty) setStatus('当前角色已保存。'); }
    catch (err) { setError(messageOf(err)); }
  }

  useEffect(() => {
    const handle = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 's') {
        event.preventDefault();
        if (!busy && saved) void save();
      }
    };
    window.addEventListener('keydown', handle);
    return () => window.removeEventListener('keydown', handle);
  });

  async function verify() {
    setError(''); setVerifying(true); setVerification(null);
    try {
      const prior = await persistCurrent();
      setStatus('正在从磁盘重载并逐顶点核对…');
      const result = await post<Verification>(`/api/characters/${encodeURIComponent(prior.character.id)}/verify`, {});
      const reloaded = await request<CharacterDocument>(`/api/characters/${encodeURIComponent(prior.character.id)}`);
      const sameVertices = prior.mesh.vertices.length === reloaded.mesh.vertices.length && prior.mesh.vertices.every((vertex, i) => vertex.every((value, axis) => value === reloaded.mesh.vertices[i][axis]));
      const frontendMatch = sameVertices && hashOf(prior) === hashOf(reloaded);
      applySaved(reloaded);
      setVerification({ ...result, passed: result.passed && frontendMatch, frontend_reload_match: frontendMatch });
      setStatus(result.passed && frontendMatch ? '重载验证通过：保存前后形状完全一致。' : '重载验证未通过，请查看核验详情。');
    } catch (err) { setError(messageOf(err)); }
    finally { setVerifying(false); }
  }

  async function exportViews() {
    setError(''); setExporting(true); setExportResult(null);
    try {
      const ready = await persistCurrent();
      setStatus('正在渲染五个标准视角，随后写入本地导出目录…');
      const views = await renderViews(ready.mesh, 768);
      const result = await post<ExportResult>('/api/exports', { character_id: ready.character.id, revision: ready.character.revision, geometry_hash: hashOf(ready), views });
      setExportResult(result); setStatus('五视角参考图、角色参数与三维网格已导出。');
    } catch (err) { setError(messageOf(err)); }
    finally { setExporting(false); }
  }

  async function exportPair() {
    setError(''); setPairExporting(true); setPairExportResult(null);
    try {
      const ready = await persistCurrent();
      setStatus('正在准备同一角色的编辑前后版本…');
      const pair = await request<PairedReference>(`/api/characters/${encodeURIComponent(ready.character.id)}/pair?revision=${ready.character.revision}`);
      if (!pair.same_identity_expression || pair.baseline.mesh.vertices.length !== pair.edited.mesh.vertices.length) {
        throw new Error('前后版本的身份、表情或网格拓扑不匹配，已停止导出。');
      }
      setStatus('正在渲染编辑前的五个标准视角（1/2）…');
      const baselineViews = await renderViews(pair.baseline.mesh, 768, pair.baseline.mesh);
      setStatus('正在以相同取景渲染编辑后的五个标准视角（2/2）…');
      const editedViews = await renderViews(pair.edited.mesh, 768, pair.baseline.mesh);
      setStatus('正在保存十张成对参考图与几何差分…');
      const result = await post<ExportResult>('/api/pair-exports', {
        character_id: ready.character.id, revision: ready.character.revision,
        baseline_geometry_hash: hashOf(pair.baseline), edited_geometry_hash: hashOf(pair.edited),
        baseline_views: baselineViews, edited_views: editedViews,
      });
      setPairExportResult(result);
      setStatus('编辑前后对照包已导出：十张参考图使用相同相机、缩放与灯光。');
    } catch (err) { setError(messageOf(err)); }
    finally { setPairExporting(false); }
  }

  async function newCharacter() {
    setError(''); setLoading(true);
    try {
      const doc = await post<CharacterDocument>('/api/characters', { name: `新角色 ${String(characters.length + 1).padStart(2, '0')}`, nose_width: 0, ...(selectedAssetId ? { asset_id: selectedAssetId } : {}) });
      applySaved(doc); setOriginalMesh(doc.mesh); await listCharacters(); setStatus('新角色已创建。');
    } catch (err) { setError(messageOf(err)); }
    finally { setLoading(false); }
  }

  const view = (degrees: number) => { setFocusNose(false); setYaw(previous => ({ degrees, sequence: previous.sequence + 1 })); };
  const renderMesh = showOriginal ? originalMesh : document?.mesh;
  const assetLabel = isFlame ? 'FLAME 参数化人脸' : document?.asset?.name || '扫描头模 · 局部编辑验证';

  return <div className="studio-app">
    <a href="#editor" className="skip-link">跳到角色编辑器</a>
    <header className="topbar">
      <a className="brand" href="/" aria-label="Character Studio 首页"><span className="brand-mark"><Box size={21} strokeWidth={1.55} aria-hidden="true" /></span><span>CHARACTER<span className="brand-light"> STUDIO</span></span><span className="version-badge">LOCAL / 01</span></a>
      <div className="topbar-center"><span className="connection-dot" />本地工作区<span className="topbar-divider" />角色身份编辑</div>
      <div className="topbar-actions"><button className="button button-outline" onClick={() => void save()} disabled={!saved || busy} aria-label="保存角色，快捷键 Command 或 Control 加 S">{saving ? <LoaderCircle className="spin" size={15} /> : <Save size={15} />}<span>保存角色</span></button><button className="button button-dark" onClick={() => void exportViews()} disabled={!saved || busy}>{exporting ? <LoaderCircle className="spin" size={15} /> : <ArrowDownToLine size={15} />}<span>导出参考图</span></button></div>
    </header>

    <div className="workspace-layout">
      <aside className="character-sidebar" aria-label="角色档案">
        <div className="sidebar-top"><div className="section-eyebrow">WORKSPACE</div><div className="sidebar-title"><h2>角色档案</h2><span className="count-badge">{characters.length.toString().padStart(2, '0')}</span></div>
          <div className="asset-creation"><label htmlFor="new-character-asset">新角色基础模型</label><select id="new-character-asset" value={selectedAssetId} onChange={event => setSelectedAssetId(event.target.value)} disabled={busy || dirty}>
            {!inventory?.assets.length && <option value="">扫描示例头模</option>}
            {inventory?.assets.map(asset => <option key={asset.asset_id} value={asset.asset_id} disabled={asset.available === false}>{asset.name || asset.asset_id}{asset.available === false ? ' · 待下载' : asset.can_edit_nose === false ? ' · 鼻翼待校准' : ''}</option>)}
          </select><button className="new-character" onClick={() => void newCharacter()} disabled={busy || dirty} title={dirty ? '请先保存或放弃当前修改，再创建新角色' : '基于所选模型创建角色'}><Plus size={16} />新建角色</button><button className="model-manager-button" onClick={() => setShowAssetManager(true)} disabled={busy}><SlidersHorizontal size={14} />模型与导入<span>{inventory?.flame_status.available ? 'FLAME 已导入' : 'FLAME'}</span></button></div>
        </div>
        <nav className="character-list" aria-label="已保存角色">
          {characters.map((character, index) => <button key={character.id} className={`character-item ${saved?.character.id === character.id ? 'selected' : ''}`} disabled={busy || dirty} onClick={() => void loadCharacter(character.id)}><span className="character-avatar"><ScanFace size={29} strokeWidth={1.15} /></span><span className="character-item-text"><strong>{character.name}</strong><small>角色 {String(index + 1).padStart(2, '0')} · v{String(character.revision).padStart(3, '0')}</small></span>{saved?.character.id === character.id && <span className="selection-dot" />}</button>)}
        </nav>
        <div className="sidebar-bottom"><div className="sidebar-note"><ShieldCheck size={18} /><div><strong>角色保存在你的电脑</strong><p>每次修改独立保存，随时重新加载。</p></div></div><div className="sidebar-footer"><span>CHARACTER ASSET</span><span className="mono">V0.1</span></div></div>
      </aside>

      <main className="editor-main" id="editor">
        <div className="workspace-heading"><div><div className="breadcrumb">角色工作区<ChevronRight size={13} /><span>身份编辑</span></div><div className="page-title"><h1>{saved?.character.name || '角色编辑器'}</h1><span className={`save-indicator ${dirty ? 'unsaved' : ''}`}>{dirty ? <span className="unsaved-dot" /> : <Check size={12} />}{dirty ? '有未保存修改' : '已保存'}</span></div><p>从一张确定的脸，开始你的角色创作。</p></div><div className="step-indicator"><span className="step active">01<small>调整角色</small></span><span className="step-line" /><span className="step">02<small>导出参考</small></span></div></div>

        {error && <div className="error-banner" role="alert"><Info size={17} /><span>{error}</span>{!saved && <button onClick={() => void initialize()}>重新连接</button>}<button className="icon-button" onClick={() => setError('')} aria-label="关闭提示"><X size={16} /></button></div>}

        {document && !canEditNose && <div className="calibration-banner" role="status"><Info size={17} aria-hidden="true" /><span>模型已加载，鼻翼区域待校准。当前预览保留原始形状，局部调整暂未启用。</span></div>}

        <section className="viewport-panel" aria-label="三维角色预览">
          <div className="viewport-toolbar"><div className="viewport-label"><span className="tiny-cross" /><span>三维预览</span><span className="subtle-label">中性表情</span></div><div className="display-actions"><button className={`toolbar-button ${showRegion ? 'active' : ''}`} aria-pressed={showRegion} onClick={() => setShowRegion(value => !value)} disabled={!document || !canEditNose}><Layers3 size={14} />调整区域</button><span className="toolbar-separator" /><button className={`toolbar-button ${showOriginal ? 'active' : ''}`} aria-pressed={showOriginal} onClick={() => setShowOriginal(value => !value)} disabled={!originalMesh}><Eye size={14} />{showOriginal ? '返回修改后' : '对比原始'}</button></div></div>
          <div className="viewport-stage">
            <Viewport mesh={renderMesh ?? null} yaw={yaw} showRegion={showRegion && !showOriginal} focusNose={focusNose} onError={setError} />
            <div className="viewport-top-note"><span className="live-indicator" />{showOriginal ? '原始鼻翼 · 对照视图' : '当前角色 · 实时预览'}</div>
            {loading && <div className="viewport-loading"><LoaderCircle className="spin" size={25} /><span>正在加载三维角色</span></div>}
            {!loading && !document && <div className="viewport-loading"><ScanFace size={36} /><span>连接本地服务以加载角色</span><button className="button button-outline" onClick={() => void initialize()}>重新加载</button></div>}
            <div className="viewport-axis" aria-hidden="true"><span className="axis-y">Y</span><span className="axis-x">X</span><span className="axis-z">Z</span><i /></div>
            <div className="viewport-interaction"><MoveHorizontal size={14} /><span>拖动旋转 · 滚轮缩放</span></div>
            {previewing && <div className="preview-progress"><LoaderCircle size={13} className="spin" />正在更新形状</div>}
          </div>
          <div className="viewport-footer"><div className="view-presets" aria-label="快捷视角"><button className={yaw.degrees === 0 ? 'active' : ''} onClick={() => view(0)}>正面</button><button className={yaw.degrees === -45 ? 'active' : ''} onClick={() => view(-45)}>左 45°</button><button className={yaw.degrees === 45 ? 'active' : ''} onClick={() => view(45)}>右 45°</button><button className={yaw.degrees === 90 ? 'active' : ''} onClick={() => view(90)}>侧面</button></div><div className="viewport-focus-actions"><button className={`toolbar-button ${focusNose ? 'active' : ''}`} aria-pressed={focusNose} disabled={!document} onClick={() => { setYaw(previous => ({ degrees: 0, sequence: previous.sequence + 1 })); setFocusNose(value => !value); }}><ScanFace size={14} /><span>{focusNose ? '整体预览' : '鼻部近看'}</span></button><button className="toolbar-button" onClick={() => view(0)} aria-label="重置视角和缩放"><RotateCcw size={14} /><span>重置视角</span></button></div></div>
        </section>

        <section className="reference-panel" aria-label="多视角参考图">
          <div className="reference-heading"><div><h2>多视角参考</h2><span>同一角色，五个标准角度</span></div><span className="format-tag">PNG · 768 × 768</span></div>
          <div className="reference-grid">{VIEWS.map(v => {
            const image = thumbnails.find(t => t.name === v.name);
            return <button className="reference-view" key={v.name} onClick={() => view(v.yaw_degrees)} aria-label={`将预览切换到${v.label}`}><div className="reference-image">{image ? <img src={image.png_base64} alt={`${v.label}的当前角色三维渲染`} /> : <ScanFace size={26} strokeWidth={1} />}</div><div><span>{v.label}</span><small>{v.yaw_degrees === 0 ? '00' : v.yaw_degrees > 0 ? `+${v.yaw_degrees}` : v.yaw_degrees}°</small></div></button>;
          })}</div>
          {thumbnailError && <p className="inline-error">{thumbnailError}</p>}
          <div className="reference-caption"><Info size={13} /><span>参考图由当前三维形状统一渲染，导出时会先保存角色。</span></div>
        </section>
      </main>

      <aside className="properties-sidebar" aria-label="角色参数与验证">
        <section className="property-section character-properties"><div className="property-heading"><h2>角色信息</h2><ScanFace size={17} /></div><label htmlFor="character-name">角色名称</label><input id="character-name" value={name} maxLength={60} onChange={event => setName(event.target.value)} disabled={!saved || busy} placeholder="为角色命名" /><div className="asset-type"><Box size={13} /><span>{assetLabel}</span></div><div className="property-meta"><span>当前版本</span><strong className="mono">v{String(saved?.character.revision ?? 0).padStart(3, '0')}</strong></div></section>

        <section className="property-section edit-properties"><div className="property-heading"><h2>局部调整</h2><span className="editing-tag">鼻部</span></div><div className="active-region"><span className="region-icon"><MoveHorizontal size={20} /></span><div><strong>鼻翼宽度</strong><span>左右对称，平滑过渡</span></div><span className="active-region-dot" /></div><div className="range-value-heading"><label htmlFor="nose-width">调整量</label><div className="number-input-wrap"><ParameterNumberInput value={noseWidth} disabled={!saved || busy || !canEditNose} onChange={next => { setNoseWidth(next); setShowOriginal(false); setExportResult(null); setPairExportResult(null); }} /><span className="number-decoration">↕</span></div></div><input id="nose-width" className="nose-slider" type="range" min="-1" max="1" step="0.01" value={noseWidth} aria-valuetext={`${noseWidth < 0 ? '收窄' : noseWidth > 0 ? '增宽' : '原始'}，调整量${signed(noseWidth)}`} disabled={!saved || busy || !canEditNose} onChange={event => { setNoseWidth(Number(event.target.value)); setShowOriginal(false); setExportResult(null); setPairExportResult(null); }} /><div className="range-labels"><span>收窄 <i>−1</i></span><span>原始</span><span>增宽 <i>+1</i></span></div><div className="measurement-row"><span>相对原始鼻翼宽度</span><strong>{previewing ? '更新中' : widthChange === null ? '—' : `${signed(widthChange, 1)}%`}</strong></div><button className="reset-parameter" disabled={!saved || busy || !canEditNose || noseWidth === 0} onClick={() => { setNoseWidth(0); setShowOriginal(false); setExportResult(null); setPairExportResult(null); }}><RotateCcw size={13} />恢复原始鼻翼</button><p className="help-text">{canEditNose ? '只调整鼻翼区域，鼻梁、鼻尖和其他五官保持原位。' : '当前模型的鼻翼区域尚未校准。可以查看并保存中性角色，完成校准后再启用局部编辑。'}</p></section>

        <section className="property-section validation-properties"><div className="property-heading"><h2>形状核验</h2><ShieldCheck size={17} /></div><div className="validation-item"><span>局部变化顶点</span><strong className="mono">{previewing ? '…' : changedVertices.toLocaleString()}</strong></div><div className="validation-item"><span>其他区域位移</span><strong className={outsideMax === 0 ? 'valid-value' : 'mono'}>{outsideMax === null ? '—' : outsideMax === 0 ? <><Check size={12} />无变化</> : outsideMax.toExponential(2)}</strong></div><div className="hash-row"><span>形状指纹</span><code title={currentHash}>{previewing ? '更新中…' : currentHash ? currentHash.slice(0, 12) : '等待加载'}</code></div><button className="button button-verify" onClick={() => void verify()} disabled={!saved || busy}>{verifying ? <LoaderCircle size={15} className="spin" /> : <RefreshCw size={15} />}<span>{dirty ? '保存并重载验证' : '重新加载并验证'}</span></button>{verification && <div className={`verification-result ${verification.passed ? 'passed' : 'failed'}`} role="status">{verification.passed ? <CircleCheck size={17} /> : <Info size={17} />}<div><strong>{verification.passed ? '重载后完全一致' : '重载核验未通过'}</strong><p>{verification.passed ? '逐顶点与形状指纹均已核对。' : '请检查角色档案与服务核验报告。'}</p></div></div>}{dirty && <button className="discard-changes" onClick={() => { if (saved) { applySaved(saved); setStatus('已恢复到最近保存的版本。'); } }}>放弃未保存修改</button>}</section>

        <section className="export-summary"><div className="export-summary-icon"><FolderOpen size={20} /></div><div><h3>准备好你的角色参考</h3><p>单版本导出五视角图片；成对导出保留同一身份和表情，只比较鼻翼修改。</p></div>
          <button className="button button-export" onClick={() => void exportPair()} disabled={!saved || busy}>{pairExporting ? <LoaderCircle size={15} className="spin" /> : <Layers3 size={15} />}<span>{pairExporting ? '正在生成对照包…' : '导出编辑前后对照包'}</span><ArrowRight size={15} /></button>
          <button className="button button-outline single-export-button" onClick={() => void exportViews()} disabled={!saved || busy}>{exporting ? <LoaderCircle size={15} className="spin" /> : <ArrowDownToLine size={15} />}<span>{exporting ? '正在导出…' : '仅导出当前角色包'}</span></button>
          <p className="pair-export-note">前后各 5 张 PNG · 同相机、缩放与灯光{noseWidth === 0 ? '。当前调整量为 0，前后参考将相同。' : ''}</p>
          {pairExportResult && <div className="export-result" role="status"><CircleCheck size={15} /><span>编辑前后对照包已保存</span><a href={pairExportResult.download_url} download>下载成对 ZIP<ArrowDownToLine size={12} /></a>{pairExportResult.contact_sheet_url && <a href={pairExportResult.contact_sheet_url} target="_blank" rel="noreferrer">查看对照总览</a>}<code title={pairExportResult.output_directory}>{pairExportResult.output_directory}</code></div>}
          {exportResult && <div className="export-result" role="status"><CircleCheck size={15} /><span>当前角色包已保存</span><a href={exportResult.download_url} download>下载 ZIP<ArrowDownToLine size={12} /></a><code title={exportResult.output_directory}>{exportResult.output_directory}</code></div>}
        </section>
      </aside>
    </div>
    <footer className="statusbar"><div><span className="connection-dot" /><span role="status" aria-live="polite" aria-atomic="true">{status || '本地角色编辑器已就绪'}</span></div><span className="statusbar-detail" title={document?.asset?.attribution}><a href={document?.asset?.source_url || (isFlame ? 'https://flame.is.tue.mpg.de/' : 'https://github.com/mrdoob/three.js/tree/r180/examples/models/gltf/LeePerrySmith')} target="_blank" rel="noreferrer">{isFlame ? document?.asset?.name || 'FLAME 模型' : 'Lee Perry-Smith / Infinite-Realities'}</a><span> · </span><a href={document?.asset?.license_url || (isFlame ? 'https://flame.is.tue.mpg.de/modellicense.html' : 'https://creativecommons.org/licenses/by/3.0/')} target="_blank" rel="noreferrer">{document?.asset?.license || (isFlame ? '模型许可' : 'CC BY 3.0')}</a></span></footer>
    <AssetManager open={showAssetManager} inventory={inventory} inventoryError={inventoryError} onClose={() => setShowAssetManager(false)} onRefresh={listAssets} onImported={id => { if (id) setSelectedAssetId(id); setStatus('模型已导入，可选择基础模型后新建角色。'); }} />
  </div>;
}
