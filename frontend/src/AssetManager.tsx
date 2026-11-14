import { useEffect, useRef, useState } from 'react';
import { ArrowUpRight, Box, Check, FolderSearch, Info, LoaderCircle, RefreshCw, X } from 'lucide-react';
import { post } from './api';
import type { AssetInfo, AssetInventory, ModelCandidate } from './types';

interface Props {
  open: boolean;
  inventory: AssetInventory | null;
  inventoryError: string;
  onClose: () => void;
  onRefresh: () => Promise<AssetInventory>;
  onImported: (assetId?: string) => void;
}

const messageOf = (error: unknown) => error instanceof Error ? error.message : '操作没有完成，请重试。';
const sizeOf = (bytes: number) => bytes >= 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)} MB` : `${Math.ceil(bytes / 1024)} KB`;

export default function AssetManager({ open, inventory, inventoryError, onClose, onRefresh, onImported }: Props) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [path, setPath] = useState('');
  const [candidates, setCandidates] = useState<ModelCandidate[]>([]);
  const [scanned, setScanned] = useState(false);
  const [scanning, setScanning] = useState(false);
  const [importing, setImporting] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState('');
  const [status, setStatus] = useState('');
  const pending = scanning || importing || refreshing;

  useEffect(() => {
    if (open && !dialog.current?.open) dialog.current?.showModal();
    if (!open && dialog.current?.open) dialog.current?.close();
  }, [open]);

  async function scan() {
    setScanning(true); setError(''); setStatus('正在检查本机下载目录…');
    try {
      const result = await post<{ candidates: ModelCandidate[] }>('/api/flame/discover', {});
      setCandidates(result.candidates); setScanned(true);
      if (result.candidates.length === 1) setPath(result.candidates[0].path);
      setStatus(result.candidates.length ? `找到 ${result.candidates.length} 个模型文件，请选择后导入。` : '目录中尚未找到可导入的模型文件。');
    } catch (err) { setError(messageOf(err)); setStatus(''); }
    finally { setScanning(false); }
  }

  async function refresh() {
    setRefreshing(true); setError('');
    try { await onRefresh(); setStatus('模型列表已更新。'); }
    catch (err) { setError(messageOf(err)); }
    finally { setRefreshing(false); }
  }

  async function importModel() {
    if (!path.trim()) { setError('请先扫描并选择下载文件，或填写下载目录内的文件路径。'); return; }
    setImporting(true); setError(''); setStatus('正在读取并转换模型，请稍候…');
    try {
      const result = await post<{ asset?: AssetInfo; asset_id?: string }>('/api/flame/import', { path: path.trim() });
      const updated = await onRefresh();
      const id = result.asset?.asset_id || result.asset_id;
      const asset = result.asset || updated.assets.find(item => item.asset_id === id);
      onImported(id);
      const needsCalibration = asset?.can_edit_nose === false;
      setStatus(needsCalibration ? '模型已导入。现在可以创建中性角色；鼻翼编辑需先完成该模型的区域校准。' : '模型已导入，可关闭此面板并在基础模型列表中选择它。');
    } catch (err) { setError(messageOf(err)); setStatus(''); }
    finally { setImporting(false); }
  }

  return <dialog ref={dialog} className="model-dialog" aria-labelledby="model-dialog-title" onCancel={onClose} onClose={onClose}>
    <div className="model-dialog-heading"><div><span className="section-eyebrow">CHARACTER MODELS</span><h2 id="model-dialog-title">模型与导入</h2></div><button className="icon-button" onClick={onClose} aria-label="关闭模型管理"><X size={19} aria-hidden="true" /></button></div>
    <div className="model-dialog-content">
      <section className="model-status-card" aria-label="FLAME模型状态"><Box size={22} aria-hidden="true" /><div><strong>{inventory?.flame_status.available ? 'FLAME 模型已在本机' : '等待导入 FLAME 模型'}</strong><p>{inventory?.flame_status.message || '从官方网站下载 FLAME 2023 Open 后，在这里导入本地文件。'}</p></div></section>
      <ol className="model-import-steps"><li><span>1</span><div><strong>从官方网站下载模型</strong><p>请选择 FLAME 2023 Open。如官网提示登录，请在官方页面完成。</p><a className="model-official-link" href={inventory?.flame_status.download_url || 'https://download.is.tue.mpg.de/download.php?domain=flame&sfile=FLAME2023Open.zip'} target="_blank" rel="noreferrer">打开官方模型下载页<ArrowUpRight size={14} aria-hidden="true" /></a></div></li><li><span>2</span><div><strong>将模型文件放入本机下载目录</strong><code className="inbox-path">{inventory?.flame_status.inbox_directory || '正在读取下载目录…'}</code><p>模型文件保留在你的电脑，由本地工作台读取。</p></div></li><li><span>3</span><div><strong>扫描文件并导入</strong><p>导入会校验模型格式，已有角色和扫描示例继续保留。</p></div></li></ol>
      <div className="model-scan-row"><button className="button button-outline" onClick={() => void scan()} disabled={pending}>{scanning ? <LoaderCircle size={15} className="spin" /> : <FolderSearch size={15} />}扫描下载文件</button><button className="toolbar-button" onClick={() => void refresh()} disabled={pending}>{refreshing ? <LoaderCircle size={14} className="spin" /> : <RefreshCw size={14} />}刷新模型列表</button></div>
      {candidates.length > 0 && <div className="model-candidate-list" role="group" aria-label="下载目录中的模型文件">{candidates.map(candidate => <button key={candidate.path} className={`model-candidate ${path === candidate.path ? 'selected' : ''}`} disabled={pending} onClick={() => setPath(candidate.path)}><span><strong>{candidate.name}</strong><code>{candidate.path}</code></span><small>{sizeOf(candidate.size)}</small>{path === candidate.path && <Check size={15} aria-hidden="true" />}</button>)}</div>}
      {scanned && !candidates.length && !error && <p className="model-empty-note">未发现模型文件。请先完成官方下载并放入上方目录，再重新扫描。</p>}
      <label className="model-path-label" htmlFor="model-local-path">下载目录内的模型文件路径</label><input id="model-local-path" className="model-path-input" value={path} onChange={event => { setPath(event.target.value); setError(''); }} placeholder="扫描选择文件，或粘贴完整路径" disabled={pending} autoComplete="off" spellCheck={false} />
      {(error || inventoryError) && <div className="model-inline-error" role="alert"><Info size={16} aria-hidden="true" /><span>{error || inventoryError}</span></div>}
      {status && <p className="model-inline-status" role="status" aria-live="polite" aria-atomic="true">{status}</p>}
      <div className="model-available"><h3>当前基础模型</h3>{inventory?.assets.map(asset => <div key={asset.asset_id} className="model-available-item"><span>{asset.name || asset.asset_id}</span><small>{asset.available === false ? '待下载' : asset.can_edit_nose === false ? '可加载 · 鼻翼待校准' : '可加载和编辑'}</small></div>)}</div>
    </div>
    <div className="model-dialog-footer"><button className="button button-outline" onClick={onClose}>返回工作台</button><button className="button button-dark" onClick={() => void importModel()} disabled={pending || !path.trim()}>{importing ? <LoaderCircle size={15} className="spin" /> : <Box size={15} />}导入本地模型</button></div>
  </dialog>;
}
