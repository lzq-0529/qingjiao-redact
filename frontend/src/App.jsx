import React, { useEffect, useMemo, useRef, useState } from 'react';
import { api } from './api';

const ENTITY_META = {
  PERSON: { label: '人名', color: 'person' },
  ORGANIZATION: { label: '机构', color: 'org' },
  LOCATION: { label: '地名', color: 'loc' },
  PHONE: { label: '电话', color: 'phone' },
  EMAIL: { label: '邮箱', color: 'email' },
  ID_CARD: { label: '身份证号', color: 'id' },
  BANK_ACCOUNT: { label: '银行卡号', color: 'bank' },
  IP_ADDRESS: { label: 'IP地址', color: 'ip' },
};

const ALL_TYPES = Object.keys(ENTITY_META);

const MODES = [
  { id: 'placeholder', label: '可逆占位符', hint: '推荐，可 100% 还原' },
  { id: 'mask', label: '星号 ***', hint: '不可还原' },
  { id: 'blackout', label: '涂黑 ███', hint: '不可还原' },
];

function buildSegments(text, entities) {
  const active = [...entities]
    .filter((e) => e.status !== 'excluded' && e.placeholder)
    .sort((a, b) => a.start - b.start);

  const segments = [];
  let cursor = 0;
  for (const ent of active) {
    if (ent.start < cursor) continue;
    if (ent.start > cursor) {
      segments.push({ type: 'text', start: cursor, text: text.slice(cursor, ent.start) });
    }
    segments.push({ type: 'entity', entity: ent, text: text.slice(ent.start, ent.end) });
    cursor = ent.end;
  }
  if (cursor < text.length) {
    segments.push({ type: 'text', start: cursor, text: text.slice(cursor) });
  }
  return segments;
}

export default function App() {
  const [capabilities, setCapabilities] = useState(null);
  const [samples, setSamples] = useState([]);
  const [sessions, setSessions] = useState([]);
  const [current, setCurrent] = useState(null);

  const [inputText, setInputText] = useState('');
  const [inputTitle, setInputTitle] = useState('');
  const [mode, setMode] = useState('placeholder');
  const [enabledTypes, setEnabledTypes] = useState(ALL_TYPES);

  const [activeTab, setActiveTab] = useState('workbench'); // workbench | restore
  const [restoreInput, setRestoreInput] = useState('');
  const [restoreStrict, setRestoreStrict] = useState(true);
  const [restoreResult, setRestoreResult] = useState(null);

  const [selectionRange, setSelectionRange] = useState(null);
  const [manualType, setManualType] = useState('PERSON');
  const [showCompare, setShowCompare] = useState(false);

  const [loading, setLoading] = useState(false);
  const [toast, setToast] = useState('');
  const [error, setError] = useState('');

  const fileInputRef = useRef(null);
  const sourcePaneRef = useRef(null);

  const showNotice = (msg) => {
    setToast(msg);
    setTimeout(() => setToast((prev) => (prev === msg ? '' : prev)), 2600);
  };

  const refreshSessions = async () => {
    try {
      const data = await api.listSessions();
      setSessions(data.sessions || []);
    } catch {
      // Ignore sidebar refresh errors.
    }
  };

  useEffect(() => {
    (async () => {
      try {
        const [caps, sampleData, sessData] = await Promise.all([
          api.getCapabilities(),
          api.getSamples(),
          api.listSessions(),
        ]);
        setCapabilities(caps);
        setSamples(sampleData.samples || []);
        setSessions(sessData.sessions || []);
      } catch (err) {
        setError(`连接本地服务失败：${err.message}`);
      }
    })();
  }, []);

  const segments = useMemo(() => {
    if (!current) return [];
    return buildSegments(current.source_text, current.entities || []);
  }, [current]);

  const activeSample = useMemo(() => {
    if (!current) return null;
    return samples.find((s) => s.title === current.title || s.filename === current.filename) || null;
  }, [current, samples]);

  const handleAnalyze = async (textOverride, titleOverride, filenameOverride) => {
    const payloadText = (textOverride ?? inputText).trim();
    if (!payloadText) {
      setError('请先粘贴文本、选择示例文稿或上传本地文件。');
      return;
    }
    setLoading(true);
    setError('');
    setRestoreResult(null);
    setSelectionRange(null);
    try {
      const created = await api.analyzeText({
        text: payloadText,
        title: titleOverride ?? (inputTitle.trim() || '粘贴文稿'),
        filename: filenameOverride ?? 'document.txt',
        mode,
        enabled_types: enabledTypes,
      });
      setCurrent(created);
      setActiveTab('workbench');
      await refreshSessions();
      showNotice(`识别完成，耗时 ${created.elapsed_ms} ms`);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleUpload = async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    setLoading(true);
    setError('');
    setRestoreResult(null);
    try {
      const created = await api.uploadFile(file, mode, enabledTypes);
      setCurrent(created);
      setActiveTab('workbench');
      await refreshSessions();
      showNotice(`已导入并识别：${file.name}`);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
      event.target.value = '';
    }
  };

  const handleSelectSession = async (sid) => {
    setLoading(true);
    setError('');
    setRestoreResult(null);
    setSelectionRange(null);
    try {
      const data = await api.getSession(sid);
      setCurrent(data);
      setMode(data.mode);
      setEnabledTypes(data.enabled_types);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleUpdateMode = async (nextMode) => {
    setMode(nextMode);
    if (!current) return;
    try {
      const updated = await api.updateSession(current.session_id, { mode: nextMode });
      setCurrent(updated);
    } catch (err) {
      setError(err.message);
    }
  };

  const handleToggleType = async (typeId) => {
    const exists = enabledTypes.includes(typeId);
    const nextTypes = exists
      ? enabledTypes.filter((t) => t !== typeId)
      : [...enabledTypes, typeId];
    if (nextTypes.length === 0) return;
    setEnabledTypes(nextTypes);
    if (!current) return;
    try {
      const updated = await api.updateSession(current.session_id, {
        enabled_types: nextTypes,
      });
      setCurrent(updated);
    } catch (err) {
      setError(err.message);
    }
  };

  const handleEntityStatus = async (entityId, nextStatus) => {
    if (!current) return;
    const nextEntities = current.entities.map((e) =>
      e.id === entityId ? { ...e, status: nextStatus } : e,
    );
    try {
      const updated = await api.updateSession(current.session_id, {
        entities: nextEntities,
      });
      setCurrent(updated);
    } catch (err) {
      setError(err.message);
    }
  };

  const handleRerun = async () => {
    if (!current) return;
    setLoading(true);
    setError('');
    try {
      const updated = await api.rerunSession(current.session_id);
      setCurrent(updated);
      showNotice('已完成重识别，人工确认与排除判定均已保留');
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleSourceMouseUp = () => {
    if (!current || !sourcePaneRef.current) return;
    const sel = window.getSelection();
    if (!sel || sel.isCollapsed || sel.rangeCount === 0) {
      setSelectionRange(null);
      return;
    }
    const range = sel.getRangeAt(0);
    if (!sourcePaneRef.current.contains(range.commonAncestorContainer)) {
      return;
    }
    const preRange = document.createRange();
    preRange.selectNodeContents(sourcePaneRef.current);
    preRange.setEnd(range.startContainer, range.startOffset);
    const start = preRange.toString().length;
    const selectedText = sel.toString();
    const end = start + selectedText.length;
    if (selectedText.trim() && current.source_text.slice(start, end) === selectedText) {
      setSelectionRange({ start, end, text: selectedText });
    } else {
      setSelectionRange(null);
    }
  };

  const handleAddManual = async () => {
    if (!current || !selectionRange) return;
    try {
      const updated = await api.addManualEntity(current.session_id, {
        start: selectionRange.start,
        end: selectionRange.end,
        entity_type: manualType,
      });
      setCurrent(updated);
      setSelectionRange(null);
      window.getSelection()?.removeAllRanges();
      showNotice(`已手动添加实体「${selectionRange.text}」`);
    } catch (err) {
      setError(err.message);
    }
  };

  const handleRestore = async () => {
    if (!current || !restoreInput.trim()) return;
    setError('');
    try {
      const res = await api.restoreText(current.session_id, restoreInput, restoreStrict);
      setRestoreResult(res);
    } catch (err) {
      setError(err.message);
    }
  };

  const handleCopy = async (text, label) => {
    try {
      await navigator.clipboard.writeText(text);
      showNotice(`已复制${label}`);
    } catch {
      showNotice('复制失败，请手动选中文本复制');
    }
  };

  const activeCount = current
    ? current.entities.filter((e) => e.status !== 'excluded' && e.placeholder).length
    : 0;
  const mappingEntries = current ? Object.entries(current.mapping || {}) : [];

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          <img src="/logo.png" alt="青椒智能脱敏" className="brand-logo" />
          <div>
            <div className="brand-title">
              青椒智能脱敏 <span className="badge-oss">开源版</span>
            </div>
            <div className="brand-sub">
              本地可逆脱敏 · 阿里 ModelScope RaNER + 基础正则（8 类敏感实体）
            </div>
          </div>
        </div>

        <div className="topbar-actions">
          {capabilities && (
            <span className="engine-pill" title={capabilities.engine.model_id}>
              引擎：{capabilities.engine.configured_engine === 'demo' ? 'Demo 预览模式' : 'RaNER + 基础正则'}
            </span>
          )}
          <button className="btn-outline" onClick={() => setShowCompare(true)}>
            F1 评测对比 &amp; 商业版
          </button>
          <a
            className="btn-primary-link"
            href="https://qingjiaolab.com"
            target="_blank"
            rel="noreferrer"
          >
            下载商业桌面版 ↗
          </a>
        </div>
      </header>

      {error && (
        <div className="banner-error">
          <span>{error}</span>
          <button onClick={() => setError('')}>关闭</button>
        </div>
      )}
      {toast && <div className="toast">{toast}</div>}

      <main className="layout">
        {/* Left column: Input, Samples, Settings, Sessions */}
        <aside className="sidebar">
          <section className="panel">
            <h3>快速体验示例</h3>
            <p className="muted">100% 虚构测试数据，点击即可走完「识别 → 复核 → 还原」闭环：</p>
            <div className="sample-list">
              {samples.map((s) => (
                <button
                  key={s.id}
                  className="sample-btn"
                  disabled={loading}
                  onClick={() => handleAnalyze(s.text, s.title, s.filename)}
                >
                  <span className="sample-tag">{s.category}</span>
                  <span>{s.title}</span>
                </button>
              ))}
            </div>
          </section>

          <section className="panel">
            <h3>导入本地文件或粘贴文本</h3>
            <input
              ref={fileInputRef}
              type="file"
              accept=".txt,.md,.markdown,.docx"
              style={{ display: 'none' }}
              onChange={handleUpload}
            />
            <button
              className="btn-upload"
              disabled={loading}
              onClick={() => fileInputRef.current?.click()}
            >
              选择 TXT / Markdown / DOCX 文件
            </button>
            <p className="hint-pro">
              需要 PDF / 扫描件 OCR / Excel / PPT / 印章涂黑？
              <a href="https://qingjiaolab.com" target="_blank" rel="noreferrer">
                查看商业版
              </a>
            </p>
            <input
              className="text-input"
              placeholder="文稿标题（可选）"
              value={inputTitle}
              onChange={(e) => setInputTitle(e.target.value)}
            />
            <textarea
              className="textarea-input"
              rows={5}
              placeholder="在此粘贴中文合同、纪要或访谈文本..."
              value={inputText}
              onChange={(e) => setInputText(e.target.value)}
            />
            <button
              className="btn-primary full"
              disabled={loading || !inputText.trim()}
              onClick={() => handleAnalyze()}
            >
              {loading ? '本地识别中...' : '开始本地 NER 脱敏'}
            </button>
          </section>

          <section className="panel">
            <h3>脱敏方式与实体类型</h3>
            <div className="mode-group">
              {MODES.map((m) => (
                <button
                  key={m.id}
                  className={`mode-chip ${mode === m.id ? 'active' : ''}`}
                  onClick={() => handleUpdateMode(m.id)}
                >
                  <span>{m.label}</span>
                  <small>{m.hint}</small>
                </button>
              ))}
            </div>
            <div className="type-toggles">
              {Object.entries(ENTITY_META).map(([id, meta]) => (
                <label key={id} className="checkbox-pill">
                  <input
                    type="checkbox"
                    checked={enabledTypes.includes(id)}
                    onChange={() => handleToggleType(id)}
                  />
                  <span className={`dot dot-${meta.color}`} />
                  {meta.label}
                </label>
              ))}
            </div>
          </section>

          {sessions.length > 0 && (
            <section className="panel">
              <h3>本地会话记录</h3>
              <div className="session-list">
                {sessions.map((s) => (
                  <button
                    key={s.session_id}
                    className={`session-item ${current?.session_id === s.session_id ? 'active' : ''}`}
                    onClick={() => handleSelectSession(s.session_id)}
                  >
                    <div className="session-title">{s.title}</div>
                    <div className="session-meta">
                      {s.entity_count} 处敏感项 · {s.format.toUpperCase()}
                    </div>
                  </button>
                ))}
              </div>
            </section>
          )}
        </aside>

        {/* Center column: Source vs Redacted preview & AI Restore */}
        <section className="workspace">
          <div className="workspace-header">
            <div className="tabs">
              <button
                className={activeTab === 'workbench' ? 'active' : ''}
                onClick={() => setActiveTab('workbench')}
              >
                原文与脱敏对照
              </button>
              <button
                className={activeTab === 'restore' ? 'active' : ''}
                onClick={() => setActiveTab('restore')}
              >
                AI 回答一键还原
              </button>
            </div>

            {current && (
              <div className="workspace-actions">
                <button className="btn-ghost" onClick={handleRerun} disabled={loading}>
                  重识别（保留人判定）
                </button>
                <button
                  className="btn-ghost"
                  onClick={() => handleCopy(current.redacted_text, '脱敏文本')}
                >
                  复制脱敏稿
                </button>
                <a className="btn-ghost" href={api.exportUrl(current.session_id, 'redacted')}>
                  导出脱敏文件
                </a>
                <a className="btn-ghost" href={api.exportUrl(current.session_id, 'mapping')}>
                  导出映射表 JSON
                </a>
              </div>
            )}
          </div>

          {!current ? (
            <div className="empty-state">
              <h2>把文档交给外部 AI 前，先在本地完成可逆脱敏</h2>
              <p>
                开源版基于阿里开源 <code>ModelScope RaNER</code> 与基础正则规则，纯本地识别中文人名、机构、地名以及电话、邮箱、身份证号、银行卡号、IP 等 8 类常见字段，
                替换为固定占位符（如 <code>{'{{人名_0001}}'}</code>），AI 改写后再按映射表 100% 严格还原。
              </p>
              <div className="empty-cta">
                {samples[0] && (
                  <button
                    className="btn-primary"
                    onClick={() =>
                      handleAnalyze(samples[0].text, samples[0].title, samples[0].filename)
                    }
                  >
                    加载「民事起诉状」演示闭环
                  </button>
                )}
                <button className="btn-outline" onClick={() => setShowCompare(true)}>
                  查看社区版 vs 商业版 F1 指标
                </button>
              </div>
            </div>
          ) : activeTab === 'workbench' ? (
            <div className="split-panes">
              <div className="pane">
                <div className="pane-head">
                  <span>原文高亮（划词可手动补充漏识）</span>
                  <span className="muted">点击高亮项可快速排除</span>
                </div>
                {selectionRange && (
                  <div className="manual-bar">
                    <span>
                      已选中：<strong>{selectionRange.text}</strong>
                    </span>
                    <select
                      value={manualType}
                      onChange={(e) => setManualType(e.target.value)}
                    >
                      {Object.entries(ENTITY_META).map(([id, meta]) => (
                        <option key={id} value={id}>
                          {meta.label}
                        </option>
                      ))}
                    </select>
                    <button className="btn-primary sm" onClick={handleAddManual}>
                      添加实体
                    </button>
                  </div>
                )}
                <div
                  className="doc-body"
                  ref={sourcePaneRef}
                  onMouseUp={handleSourceMouseUp}
                >
                  {segments.map((seg, idx) =>
                    seg.type === 'text' ? (
                      <React.Fragment key={idx}>{seg.text}</React.Fragment>
                    ) : (
                      <mark
                        key={seg.entity.id}
                        className={`hl hl-${ENTITY_META[seg.entity.entity_type]?.color || 'person'}`}
                        title={`${ENTITY_META[seg.entity.entity_type]?.label} → ${seg.entity.placeholder}（点击排除）`}
                        onClick={() => handleEntityStatus(seg.entity.id, 'excluded')}
                      >
                        {seg.text}
                      </mark>
                    ),
                  )}
                </div>
              </div>

              <div className="pane">
                <div className="pane-head">
                  <span>脱敏预览（可直接发给 DeepSeek / GPT / Claude）</span>
                  <span className="muted">
                    {activeCount} 处已脱敏 · {mappingEntries.length} 条映射
                  </span>
                </div>
                <pre className="doc-body redacted-pre">{current.redacted_text}</pre>
              </div>
            </div>
          ) : (
            <div className="restore-pane">
              <div className="restore-bar">
                <div>
                  <h3>粘贴外部 AI 返回的脱敏回复，按本篇映射表 100% 还原</h3>
                  <p className="muted">
                    严格模式下只要存在未匹配的未知占位符就会中止还原，绝不输出半成品。
                  </p>
                </div>
                {activeSample?.sample_ai_reply && (
                  <button
                    className="btn-outline"
                    onClick={() => setRestoreInput(activeSample.sample_ai_reply)}
                  >
                    填入示例 AI 回答
                  </button>
                )}
              </div>

              <textarea
                className="textarea-input restore-textarea"
                rows={7}
                placeholder="在此粘贴包含 {{人名_0001}}、{{机构_0001}} 等占位符的 AI 回复或改稿..."
                value={restoreInput}
                onChange={(e) => setRestoreInput(e.target.value)}
              />

              <div className="restore-controls">
                <label className="checkbox-pill">
                  <input
                    type="checkbox"
                    checked={restoreStrict}
                    onChange={(e) => setRestoreStrict(e.target.checked)}
                  />
                  严格完整还原（遇未匹配占位符中止）
                </label>
                <button
                  className="btn-primary"
                  disabled={!restoreInput.trim()}
                  onClick={handleRestore}
                >
                  立即还原原文
                </button>
              </div>

              {restoreResult && (
                <div className={`restore-box ${restoreResult.ok ? 'ok' : 'fail'}`}>
                  {restoreResult.ok ? (
                    <>
                      <div className="pane-head">
                        <span>还原成功（共替换 {restoreResult.replaced_count} 处占位符）</span>
                        <button
                          className="btn-ghost"
                          onClick={() => handleCopy(restoreResult.restored_text || '', '还原稿')}
                        >
                          复制还原结果
                        </button>
                      </div>
                      <pre className="doc-body">{restoreResult.restored_text}</pre>
                    </>
                  ) : (
                    <div className="restore-error">{restoreResult.error}</div>
                  )}
                </div>
              )}
            </div>
          )}
        </section>

        {/* Right column: Human review checklist + Pro upgrade card */}
        <aside className="review-panel">
          <div className="panel-head-sticky">
            <h3>人工复核清单</h3>
            <span className="muted">{current ? `${current.entities.length} 条记录` : '未加载'}</span>
          </div>

          <div className="entity-list">
            {current && current.entities.length > 0 ? (
              current.entities.map((ent) => {
                const meta = ENTITY_META[ent.entity_type] || { label: ent.entity_type, color: 'person' };
                const isExcluded = ent.status === 'excluded';
                return (
                  <div
                    key={ent.id}
                    className={`entity-card ${isExcluded ? 'excluded' : ''} ${
                      ent.status === 'confirmed' ? 'confirmed' : ''
                    }`}
                  >
                    <div className="entity-top">
                      <span className={`tag tag-${meta.color}`}>{meta.label}</span>
                      <span className="entity-text">{ent.original_text}</span>
                    </div>
                    <div className="entity-mid">
                      <code>{ent.placeholder || '已排除（保持原文）'}</code>
                      <span className="muted">
                        {ent.manual ? '手动添加' : `${Math.round(ent.confidence * 100)}%`}
                      </span>
                    </div>
                    <div className="entity-actions">
                      {isExcluded ? (
                        <button onClick={() => handleEntityStatus(ent.id, 'pending')}>
                          恢复脱敏
                        </button>
                      ) : (
                        <>
                          <button
                            className={ent.status === 'confirmed' ? 'done' : ''}
                            onClick={() =>
                              handleEntityStatus(
                                ent.id,
                                ent.status === 'confirmed' ? 'pending' : 'confirmed',
                              )
                            }
                          >
                            {ent.status === 'confirmed' ? '已确认 ✓' : '确认'}
                          </button>
                          <button onClick={() => handleEntityStatus(ent.id, 'excluded')}>
                            排除
                          </button>
                        </>
                      )}
                    </div>
                  </div>
                );
              })
            ) : (
              <div className="muted empty-review">
                识别完成后，所有实体候选将在此逐项列出供人工核验。
              </div>
            )}
          </div>

          <div className="pro-card">
            <div className="pro-card-title">开源版与商业版边界提示</div>
            <ul>
              <li>开源版搭载阿里 RaNER + 5 类基础正则（共 8 类，CLUENER 机构 F1 0.71）</li>
              <li>商业版：青椒自研高精度引擎（人名 F1 <strong>0.98</strong>，机构 <strong>0.94</strong>，结构化字段 <strong>0.96</strong>）</li>
              <li>覆盖 30+ 敏感类、PDF 原位脱敏/真涂黑、Word/Excel/PPT、扫描件 OCR 与一键桌面安装包</li>
            </ul>
            <a
              className="btn-primary full link-btn"
              href="https://qingjiaolab.com"
              target="_blank"
              rel="noreferrer"
            >
              前往青椒官网升级商业版 ↗
            </a>
          </div>
        </aside>
      </main>

      {showCompare && (
        <div className="modal-backdrop" onClick={() => setShowCompare(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-head">
              <h2>实测基准对比：开源社区版 vs 商业专业版</h2>
              <button className="btn-ghost" onClick={() => setShowCompare(false)}>
                关闭
              </button>
            </div>
            <p className="muted">
              以下数据均来自公开第三方评测集（CLUENER2020 dev）与真实业务多文体金标集实测，不含夸大指标：
            </p>
            <table className="compare-table">
              <thead>
                <tr>
                  <th>对比维度</th>
                  <th>开源社区版（当前）</th>
                  <th>青椒商业版（Desktop / Pro）</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td>识别引擎</td>
                  <td>阿里开源 ModelScope RaNER + 5 类基础正则</td>
                  <td>青椒自研高精度本地识别引擎 + 全套商业校验规则</td>
                </tr>
                <tr>
                  <td>实体覆盖范围</td>
                  <td>8 类（人名/机构/地名 + 电话/邮箱/身份证/银行卡/IP）</td>
                  <td><strong>30+ 类敏感字段</strong> + 印章/签名/二维码/Logo 图像区</td>
                </tr>
                <tr>
                  <td>名称实体 F1（实测）</td>
                  <td>CLUENER 人名 0.79 / 机构 <strong>0.71</strong></td>
                  <td>人名 <strong>0.98</strong> / 机构 <strong>0.94</strong>（公告 0.95）/ 地址 <strong>0.93</strong> / 文件名 <strong>0.95</strong></td>
                </tr>
                <tr>
                  <td>结构化字段 F1</td>
                  <td>基础格式校验（5 类常见字段）</td>
                  <td>30+ 类含上下文语义校验，盲测 <strong>0.96</strong>（遮盖率 0.98）</td>
                </tr>
                <tr>
                  <td>运行开销与 CPU 速度</td>
                  <td>~400 MB 开源权重 · 长文 ~55.3 s</td>
                  <td><strong>轻量本地推理 · 0.45 秒 / 千字</strong>（无需 GPU）</td>
                </tr>
                <tr>
                  <td>支持文件格式</td>
                  <td>TXT / Markdown / 基础 DOCX</td>
                  <td>Word / Excel / PPT / PDF 原位替换&amp;真涂黑 / 扫描件 OCR / 图片</td>
                </tr>
                <tr>
                  <td>部署与协作</td>
                  <td>源码自部署 / Docker / MCP</td>
                  <td>Windows / macOS / Linux 一键安装包 + 批量文件夹处理</td>
                </tr>
              </tbody>
            </table>
            <div className="modal-foot">
              <a
                className="btn-outline"
                href="https://app.qingjiaolab.com"
                target="_blank"
                rel="noreferrer"
              >
                在线免费体验商业工作台
              </a>
              <a
                className="btn-primary link-btn"
                href="https://qingjiaolab.com"
                target="_blank"
                rel="noreferrer"
              >
                访问官网获取桌面专业版 ↗
              </a>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
