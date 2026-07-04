import { useEffect, useMemo, useState } from 'react';
import {
  Archive,
  Bot,
  CheckCircle2,
  Database,
  EyeOff,
  FileSearch,
  GitBranch,
  KeyRound,
  Lock,
  Play,
  RefreshCw,
  Rocket,
  Save,
  Search,
  Send,
  Settings,
  Trash2,
  UploadCloud,
} from 'lucide-react';
import type {
  AdminStatus,
  AuditLogRecord,
  ComplianceReport,
  HealthStatus,
  InferredMetadata,
  IngestReport,
  SecureSettingsSchema,
  SecureSettingsStatus,
  WorkflowStatus,
} from '../types.js';

export type OperationsTab = 'admin' | 'audit' | 'knowledge' | 'workflow' | 'batch';

type UploadStatus = 'ready' | 'running' | 'done' | 'error';

interface KnowledgeUploadItem {
  id: string;
  name: string;
  size: number;
  text: string;
  status: UploadStatus;
  report?: IngestReport;
  error?: string;
}

const MAX_KNOWLEDGE_UPLOAD_BYTES = 1_500_000;
const KNOWLEDGE_UPLOAD_EXTENSIONS = new Set(['txt', 'md', 'markdown', 'json', 'csv']);

interface OperationsPanelProps {
  tab: OperationsTab;
  health: HealthStatus | null;
  activeReport: ComplianceReport | null;
  metadata: InferredMetadata;
  onSelectReport: (report: ComplianceReport) => void;
  onReportsProduced: (reports: ComplianceReport[]) => void;
  onRefreshHealth: () => void;
}

export default function OperationsPanel({
  tab,
  health,
  activeReport,
  metadata,
  onSelectReport,
  onReportsProduced,
  onRefreshHealth,
}: OperationsPanelProps) {
  if (tab === 'admin') return <AdminPanel health={health} onRefreshHealth={onRefreshHealth} />;
  if (tab === 'audit') return <AuditLogBrowser />;
  if (tab === 'knowledge') return <KnowledgeIngestPanel />;
  if (tab === 'workflow') return <WorkflowPanel activeReport={activeReport} />;
  return (
    <BatchReviewPanel
      metadata={metadata}
      onSelectReport={onSelectReport}
      onReportsProduced={onReportsProduced}
      onRefreshHealth={onRefreshHealth}
    />
  );
}

function AdminPanel({ health, onRefreshHealth }: { health: HealthStatus | null; onRefreshHealth: () => void }) {
  const [status, setStatus] = useState<AdminStatus | null>(null);
  const [loading, setLoading] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const response = await fetch('/api/admin/status');
      const json = await response.json();
      if (json.status === 'success') setStatus(json.data as AdminStatus);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const modelRows = status ? [
    ['Shallow', status.model_routing.shallow, 'low-cost triage'],
    ['Standard', status.model_routing.standard, 'normal review'],
    ['Deep', status.model_routing.deep, 'complex/high-risk'],
    ['Critic', status.model_routing.critic, 'independent verifier'],
  ] : [];

  return (
    <section className="panel ops-panel">
      <PanelTitle eyebrow="Admin" title="Runtime settings and readiness" icon={Settings} />
      <div className="ops-toolbar">
        <button type="button" className="secondary-button" onClick={() => { void load(); onRefreshHealth(); }} disabled={loading}>
          <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </button>
        <span className="mini-chip">worker: {health?.python_worker?.status || 'unknown'}</span>
        <span className="mini-chip">cache: {health?.review_cache?.enabled ? `${health.review_cache.size}/${health.review_cache.max}` : 'off'}</span>
      </div>

      {status && (
        <>
          <div className="ops-grid">
            {modelRows.map(([label, value, hint]) => (
              <div className="ops-card" key={label}>
                <span>{label}</span>
                <strong>{value}</strong>
                <em>{hint}</em>
              </div>
            ))}
          </div>

          <div className="ops-grid two">
            <StatusMap title="Runtime flags" values={status.runtime_flags} />
            <SecretMap title="Secret readiness" values={status.secrets} />
          </div>

          <div className="ops-grid two">
            <StatusMap title="Project paths" values={status.paths} />
            <JsonBlock title="Worker and cache" value={{ python_worker: status.python_worker, cache: status.cache }} />
          </div>

          <SecureSettingsPanel onApplied={() => { void load(); onRefreshHealth(); }} />
        </>
      )}
    </section>
  );
}

function SecureSettingsPanel({ onApplied }: { onApplied: () => void }) {
  const [schema, setSchema] = useState<SecureSettingsSchema | null>(null);
  const [settings, setSettings] = useState<SecureSettingsStatus | null>(null);
  const [masterPassword, setMasterPassword] = useState('');
  const [models, setModels] = useState<Record<string, string>>({});
  const [routing, setRouting] = useState<Record<string, string>>({});
  const [flags, setFlags] = useState<Record<string, string>>({});
  const [secretDrafts, setSecretDrafts] = useState<Record<string, string>>({});
  const [clearSecrets, setClearSecrets] = useState<Record<string, boolean>>({});
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ tone: 'ok' | 'warn'; text: string } | null>(null);

  const hydrate = (next: SecureSettingsStatus) => {
    setSettings(next);
    if (next.schema) setSchema(next.schema);
    setModels(next.models || {});
    setRouting(next.routing || {});
    setFlags(next.flags || {});
    setSecretDrafts({});
    setClearSecrets({});
  };

  const request = async (url: string, init?: RequestInit) => {
    setBusy(true);
    setMessage(null);
    try {
      const response = await fetch(url, init);
      const json = await response.json();
      if (!response.ok || json.status !== 'success') throw new Error(json.message || 'settings request failed');
      hydrate(json.data as SecureSettingsStatus);
      onApplied();
      return json.data as SecureSettingsStatus;
    } catch (caught) {
      setMessage({ tone: 'warn', text: caught instanceof Error ? caught.message : String(caught) });
      return null;
    } finally {
      setBusy(false);
    }
  };

  const loadStatus = async () => {
    const loaded = await request('/api/settings/status');
    if (loaded) setMessage(null);
  };

  useEffect(() => {
    void loadStatus();
  }, []);

  const payload = () => ({
    master_password: masterPassword,
    settings: {
      secrets: secretDrafts,
      models,
      routing,
      flags,
    },
    clear_secrets: Object.entries(clearSecrets).filter(([, value]) => value).map(([key]) => key),
  });

  const loadEncrypted = async () => {
    const data = await request('/api/settings/load', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ master_password: masterPassword }),
    });
    if (data) setMessage({ tone: 'ok', text: '암호화 설정을 불러와 현재 세션에 적용했습니다.' });
  };

  const applySession = async () => {
    const data = await request('/api/settings/apply', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload()),
    });
    if (data) setMessage({ tone: 'ok', text: '현재 화면 설정을 세션에 적용했습니다. 저장된 암호화 파일은 변경하지 않았습니다.' });
  };

  const saveEncrypted = async () => {
    const data = await request('/api/settings/save', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload()),
    });
    if (data) setMessage({ tone: 'ok', text: '현재 화면 설정을 암호화 저장하고 세션에 적용했습니다.' });
  };

  const deleteEncrypted = async () => {
    if (!window.confirm('암호화 설정 파일을 삭제할까요? 현재 프로세스 환경변수는 서버 재시작 전까지 남을 수 있습니다.')) return;
    const data = await request('/api/settings', { method: 'DELETE' });
    if (data) setMessage({ tone: 'warn', text: '암호화 설정 파일을 삭제했습니다.' });
  };

  if (!schema || !settings) {
    return (
      <div className="ops-card tall">
        <span>Secure settings</span>
        <strong>Loading</strong>
      </div>
    );
  }

  const secretMutation = Object.values(secretDrafts).some((value) => String(value).trim()) || Object.values(clearSecrets).some(Boolean);

  return (
    <div className="settings-console" id="secure-llm-settings-console">
      <div className="section-title">
        <div>
          <p className="eyebrow">Secure Settings</p>
          <h2>LLM 모델 라우팅과 API 키</h2>
        </div>
        <Lock className="h-5 w-5 text-forest-700" />
      </div>

      <div className="settings-lock-row">
        <label className="select-field">
          <span>마스터 비밀번호</span>
          <input
            type="password"
            autoComplete="current-password"
            value={masterPassword}
            onChange={(event) => setMasterPassword(event.target.value)}
            placeholder={settings.encrypted_settings_present ? '암호화 설정 불러오기/저장' : '새 암호화 설정 생성'}
          />
        </label>
        <button type="button" className="secondary-button" onClick={() => void loadEncrypted()} disabled={busy || !masterPassword.trim()}>
          <KeyRound className="h-4 w-4" />
          Load
        </button>
        <button type="button" className="secondary-button" onClick={() => void applySession()} disabled={busy || (secretMutation && !masterPassword.trim())}>
          <RefreshCw className={`h-4 w-4 ${busy ? 'animate-spin' : ''}`} />
          Apply
        </button>
        <button type="button" className="primary-button" onClick={() => void saveEncrypted()} disabled={busy || !masterPassword.trim()}>
          <Save className="h-4 w-4" />
          Save encrypted
        </button>
        <button type="button" className="icon-button" onClick={() => void deleteEncrypted()} disabled={busy || !settings.encrypted_settings_present} title="Delete encrypted settings">
          <Trash2 className="h-4 w-4" />
        </button>
      </div>

      {message && <div className={`settings-message ${message.tone === 'ok' ? 'tone-green' : 'tone-amber'}`}>{message.text}</div>}

      <datalist id="model-presets">
        {schema.model_presets.map((model) => <option key={model} value={model} />)}
      </datalist>

      <div className="settings-layout">
        <div className="settings-group">
          <div className="settings-group-title">
            <Bot className="h-4 w-4" />
            <strong>모델 라우팅</strong>
          </div>
          <div className="settings-grid">
            {schema.model_fields.map((field) => (
              <label className="select-field" key={field.env}>
                <span>{field.label}</span>
                <input
                  list="model-presets"
                  value={models[field.env] || field.default || ''}
                  onChange={(event) => setModels((current) => ({ ...current, [field.env]: event.target.value }))}
                  title={`${field.env} - ${field.help}`}
                />
                <em>{field.env}</em>
              </label>
            ))}
          </div>
        </div>

        <div className="settings-group">
          <div className="settings-group-title">
            <Settings className="h-4 w-4" />
            <strong>라우팅/성능</strong>
          </div>
          <div className="settings-grid">
            {schema.routing_fields.map((field) => (
              <label className="select-field" key={field.env}>
                <span>{field.label}</span>
                {field.options?.length ? (
                  <select value={routing[field.env] || field.default || ''} onChange={(event) => setRouting((current) => ({ ...current, [field.env]: event.target.value }))}>
                    {field.options.map((option) => <option key={option} value={option}>{option}</option>)}
                  </select>
                ) : (
                  <input
                    type={field.kind === 'number' ? 'number' : 'text'}
                    min={field.minimum}
                    max={field.maximum}
                    value={routing[field.env] || field.default || ''}
                    onChange={(event) => setRouting((current) => ({ ...current, [field.env]: event.target.value }))}
                    title={`${field.env} - ${field.help}`}
                  />
                )}
                <em>{field.env}</em>
              </label>
            ))}
          </div>
        </div>

        <div className="settings-group">
          <div className="settings-group-title">
            <CheckCircle2 className="h-4 w-4" />
            <strong>런타임 플래그</strong>
          </div>
          <div className="settings-toggle-grid">
            {schema.flag_fields.map((field) => (
              <label className="toggle-row settings-toggle" key={field.env} title={`${field.env} - ${field.help}`}>
                <input
                  type="checkbox"
                  checked={(flags[field.env] || field.default || '0') === '1'}
                  onChange={(event) => setFlags((current) => ({ ...current, [field.env]: event.target.checked ? '1' : '0' }))}
                />
                {field.label}
              </label>
            ))}
          </div>
        </div>

        {(() => {
          // 필수 API 키 (OpenAI 심의 LLM + 법령정보센터 본문 조회)를 별도 섹션으로 분리해 위에 배치.
          // .env에 있으면 'set'(environment)으로 표시되고, 사용자가 본인 키를 입력하면 그 키가 우선 사용됨.
          const REQUIRED_ENVS = ['OPENAI_API_KEY', 'LAW_OPEN_API_KEY'];
          const renderSecretField = (field: { env: string; label: string; help: string }) => {
            const status = settings.secrets[field.env];
            const present = Boolean(status?.present);
            return (
              <label className="secret-field" key={field.env}>
                <span>
                  {field.label}
                  <em style={{ color: present ? '#059669' : '#d97706', fontWeight: 600 }}>
                    {present ? `set · ${status?.source}` : 'unset'}
                  </em>
                </span>
                <input
                  type="password"
                  autoComplete="new-password"
                  value={secretDrafts[field.env] || ''}
                  placeholder={present ? '설정됨 · 본인 키 입력 시 교체 사용' : '미설정 · 본인 키 입력'}
                  onChange={(event) => setSecretDrafts((current) => ({ ...current, [field.env]: event.target.value }))}
                  title={`${field.env} - ${field.help}`}
                />
                <label className="secret-clear">
                  <input
                    type="checkbox"
                    checked={Boolean(clearSecrets[field.env])}
                    onChange={(event) => setClearSecrets((current) => ({ ...current, [field.env]: event.target.checked }))}
                  />
                  삭제
                </label>
              </label>
            );
          };
          const requiredFields = schema.secret_fields.filter((f) => REQUIRED_ENVS.includes(f.env));
          const otherFields = schema.secret_fields.filter((f) => !REQUIRED_ENVS.includes(f.env));
          // 필수 섹션 순서 고정: OpenAI → LAW
          requiredFields.sort((a, b) => REQUIRED_ENVS.indexOf(a.env) - REQUIRED_ENVS.indexOf(b.env));
          return (
            <>
              <div className="settings-group settings-group-wide">
                <div className="settings-group-title">
                  <KeyRound className="h-4 w-4" />
                  <strong>필수 API 키</strong>
                  <span className="mini-chip">required</span>
                </div>
                <p style={{ fontSize: '12px', color: '#64748b', margin: '4px 0 10px', lineHeight: 1.5 }}>
                  심의 LLM(OpenAI)과 법령 본문 조회(법령정보센터)에 필요합니다. 서버 .env에 설정돼 있으면 <strong style={{ color: '#059669' }}>set</strong>으로 표시되며, 본인 키를 입력하면 해당 세션부터 그 키가 우선 사용됩니다.
                </p>
                <div className="secret-grid">
                  {requiredFields.map(renderSecretField)}
                </div>
              </div>

              <div className="settings-group settings-group-wide">
                <div className="settings-group-title">
                  <EyeOff className="h-4 w-4" />
                  <strong>API 키 / 외부 연동 (선택)</strong>
                  <span className="mini-chip">values hidden</span>
                </div>
                <div className="secret-grid">
                  {otherFields.map(renderSecretField)}
                </div>
              </div>
            </>
          );
        })()}
      </div>
    </div>
  );
}

function AuditLogBrowser() {
  const [query, setQuery] = useState('');
  const [records, setRecords] = useState<AuditLogRecord[]>([]);
  const [selected, setSelected] = useState<Record<string, unknown> | null>(null);
  const [routingHistory, setRoutingHistory] = useState<Record<string, unknown>[]>([]);
  const [loading, setLoading] = useState(false);

  const load = async (nextQuery = query) => {
    setLoading(true);
    try {
      const response = await fetch(`/api/audit/logs?limit=40&query=${encodeURIComponent(nextQuery)}`);
      const json = await response.json();
      if (json.status === 'success') {
        setRecords(json.data.records as AuditLogRecord[]);
        setRoutingHistory(json.data.routing_history as Record<string, unknown>[]);
        setSelected(null);
      }
    } finally {
      setLoading(false);
    }
  };

  const openRecord = async (auditId: string) => {
    const response = await fetch(`/api/audit/logs/${encodeURIComponent(auditId)}`);
    const json = await response.json();
    if (json.status === 'success') setSelected(json.data as Record<string, unknown>);
  };

  useEffect(() => {
    void load('');
  }, []);

  return (
    <section className="panel ops-panel">
      <PanelTitle eyebrow="Audit" title="Persistent audit log browser" icon={FileSearch} />
      <div className="ops-toolbar">
        <label className="ops-search">
          <Search className="h-4 w-4" />
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Audit ID, status, route, text" />
        </label>
        <button type="button" className="secondary-button" onClick={() => void load()} disabled={loading}>
          <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
          Search
        </button>
      </div>

      <div className="ops-split">
        <div className="ops-list">
          {records.length === 0 ? (
            <div className="empty-state compact">No audit records found.</div>
          ) : records.map((record) => (
            <button type="button" className="ops-list-item" key={record.audit_log_id} onClick={() => void openRecord(record.audit_log_id)}>
              <span className={`status-pill ${record.human_review_needed ? 'tone-amber' : 'tone-green'}`}>
                {record.human_review_needed ? 'HITL' : 'Auto'}
              </span>
              <strong>{record.audit_log_id}</strong>
              <em>{record.final_status || record.input_type || 'record'} · {record.llm_call_count || 0} LLM calls · {record.trace_count || 0} trace events</em>
              {record.redacted_text && <small>{record.redacted_text}</small>}
            </button>
          ))}
        </div>
        <div className="ops-detail">
          {selected ? <JsonBlock title="Audit record" value={selected} /> : <JsonBlock title="Recent routing history" value={routingHistory} />}
        </div>
      </div>
    </section>
  );
}

function KnowledgeIngestPanel() {
  const [text, setText] = useState('');
  const [source, setSource] = useState('react-ui-manual-ingest.md');
  const [apply, setApply] = useState(false);
  const [approvedMemory, setApprovedMemory] = useState(false);
  const [running, setRunning] = useState(false);
  const [report, setReport] = useState<IngestReport | null>(null);
  const [uploadItems, setUploadItems] = useState<KnowledgeUploadItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [knowledgeItems, setKnowledgeItems] = useState<Array<{ id: string; source: string; text: string; created_at: string }>>([]);

  // R8: 저장된 지식(RAG corpus) 목록 로드
  const loadKnowledge = async () => {
    try {
      const response = await fetch('/api/knowledge');
      const json = await response.json();
      if (response.ok && json.status === 'success') setKnowledgeItems(json.data || []);
    } catch {
      /* 목록 로드 실패는 조용히 무시 — ingest 기능에 영향 없음 */
    }
  };

  useEffect(() => {
    void loadKnowledge();
  }, []);

  // R8: 지식 항목 삭제 (서버 ACL: COMPLIANCE_OFFICER|ADMIN, 비권한 시 403)
  const removeKnowledge = async (id: string) => {
    if (!confirm('이 지식 항목을 RAG corpus에서 삭제하시겠습니까?')) return;
    try {
      const response = await fetch(`/api/knowledge/${encodeURIComponent(id)}`, { method: 'DELETE' });
      const json = await response.json();
      if (!response.ok || json.status !== 'success') {
        setError(json.message || '지식 삭제에 실패했습니다. (권한 부족이거나 서버 오류)');
        return;
      }
      await loadKnowledge();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  };

  const batchSummary = useMemo(() => {
    const reports = uploadItems.flatMap((item) => item.report ? [item.report] : []);
    return reports.reduce((summary, item) => ({
      files: summary.files + 1,
      chunks: summary.chunks + item.total_chunks,
      blocked: summary.blocked + item.blocked_chunks,
      skill: summary.skill + (item.target_counts.skill || 0),
      rag: summary.rag + (item.target_counts.rag || 0),
      memory: summary.memory + (item.target_counts.memory || 0),
      writtenSkill: summary.writtenSkill + item.written_skill_items,
      writtenRag: summary.writtenRag + item.written_rag_items,
      writtenMemory: summary.writtenMemory + item.written_memory_items,
    }), {
      files: 0,
      chunks: 0,
      blocked: 0,
      skill: 0,
      rag: 0,
      memory: 0,
      writtenSkill: 0,
      writtenRag: 0,
      writtenMemory: 0,
    });
  }, [uploadItems]);

  const submitIngest = async (payload: { text: string; source: string }) => {
    const response = await fetch('/api/ingest', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...payload, apply, approved_memory: approvedMemory }),
    });
    const json = await response.json();
    if (!response.ok || json.status !== 'success') throw new Error(json.message || 'ingest failed');
    return json.data as IngestReport;
  };

  const run = async () => {
    setRunning(true);
    setError(null);
    try {
      setReport(await submitIngest({ text, source }));
      await loadKnowledge();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setRunning(false);
    }
  };

  const handleUploadFiles = async (files: FileList | null) => {
    const selected = Array.from(files || []);
    if (!selected.length) return;
    setError(null);
    const loaded: KnowledgeUploadItem[] = [];

    for (const [index, file] of selected.entries()) {
      const extension = file.name.split('.').pop()?.toLowerCase() || '';
      const id = `${file.name}-${file.lastModified}-${file.size}-${index}-${Date.now()}`;
      const baseItem = { id, name: file.name, size: file.size, text: '' };

      if (!KNOWLEDGE_UPLOAD_EXTENSIONS.has(extension)) {
        loaded.push({ ...baseItem, status: 'error', error: 'Unsupported file type' });
        continue;
      }
      if (file.size > MAX_KNOWLEDGE_UPLOAD_BYTES) {
        loaded.push({ ...baseItem, status: 'error', error: `File exceeds ${formatBytes(MAX_KNOWLEDGE_UPLOAD_BYTES)}` });
        continue;
      }

      try {
        const fileText = await file.text();
        loaded.push(fileText.trim()
          ? { ...baseItem, text: fileText, status: 'ready' }
          : { ...baseItem, status: 'error', error: 'File is empty' });
      } catch (caught) {
        loaded.push({ ...baseItem, status: 'error', error: caught instanceof Error ? caught.message : String(caught) });
      }
    }

    setUploadItems((items) => [...items, ...loaded]);
  };

  const runUploadQueue = async () => {
    const runnable = uploadItems.filter((item) => item.text.trim() && item.status !== 'done');
    if (!runnable.length) return;
    setRunning(true);
    setError(null);

    try {
      for (const item of runnable) {
        setUploadItems((items) => items.map((current) => current.id === item.id
          ? { ...current, status: 'running', error: undefined }
          : current));

        try {
          const uploadReport = await submitIngest({ text: item.text, source: `expert-upload/${item.name}` });
          setUploadItems((items) => items.map((current) => current.id === item.id
            ? { ...current, status: 'done', report: uploadReport }
            : current));
        } catch (caught) {
          setUploadItems((items) => items.map((current) => current.id === item.id
            ? { ...current, status: 'error', error: caught instanceof Error ? caught.message : String(caught) }
            : current));
        }
      }
    } finally {
      setRunning(false);
    }
  };

  return (
    <section className="panel ops-panel">
      <PanelTitle eyebrow="Knowledge" title="Document ingest into Skill, RAG, and Memory" icon={UploadCloud} />
      <div className="ops-form-grid">
        <label className="select-field">
          <span>Source label</span>
          <input value={source} onChange={(event) => setSource(event.target.value)} />
        </label>
        <label className="toggle-row">
          <input type="checkbox" checked={apply} onChange={(event) => setApply(event.target.checked)} />
          Apply writes
        </label>
        <label className="toggle-row">
          <input type="checkbox" checked={approvedMemory} onChange={(event) => setApprovedMemory(event.target.checked)} />
          Approve memory
        </label>
      </div>
      <div className="knowledge-upload-grid">
        <label className="file-upload-zone">
          <UploadCloud className="h-5 w-5" />
          <strong>Expert document upload</strong>
          <span>TXT, MD, JSON, CSV - max {formatBytes(MAX_KNOWLEDGE_UPLOAD_BYTES)} each</span>
          <input
            className="upload-input"
            type="file"
            multiple
            accept=".txt,.md,.markdown,.json,.csv,text/plain,text/markdown,application/json,text/csv"
            onChange={(event) => {
              void handleUploadFiles(event.currentTarget.files);
              event.currentTarget.value = '';
            }}
          />
        </label>
        <div className="ingest-summary-band">
          <Metric label="Uploaded docs" value={`${uploadItems.length}`} />
          <Metric label="Batch chunks" value={`${batchSummary.chunks}`} />
          <Metric label="Skill" value={`${batchSummary.writtenSkill}/${batchSummary.skill}`} />
          <Metric label="RAG" value={`${batchSummary.writtenRag}/${batchSummary.rag}`} />
          <Metric label="Memory" value={`${batchSummary.writtenMemory}/${batchSummary.memory}`} />
        </div>
      </div>

      {uploadItems.length > 0 && (
        <>
          <div className="ops-toolbar">
            <button
              type="button"
              className="primary-button"
              onClick={() => void runUploadQueue()}
              disabled={running || !uploadItems.some((item) => item.text.trim() && item.status !== 'done')}
            >
              <Database className="h-4 w-4" />
              {running ? 'Processing uploads' : apply ? 'Apply uploaded docs' : 'Dry-run uploaded docs'}
            </button>
            <button type="button" className="secondary-button" onClick={() => setUploadItems([])} disabled={running}>
              Clear uploads
            </button>
            {batchSummary.files > 0 && (
              <span className={`mini-chip ${batchSummary.blocked ? 'tone-amber' : 'tone-green'}`}>
                {batchSummary.files} processed - {batchSummary.blocked} blocked
              </span>
            )}
          </div>
          <div className="upload-list">
            {uploadItems.map((item) => (
              <article className={`upload-item upload-${item.status}`} key={item.id}>
                <div className="upload-status-row">
                  <strong>{item.name}</strong>
                  <span className={`status-pill ${uploadStatusTone(item.status)}`}>{uploadStatusLabel(item.status)}</span>
                </div>
                <em>{formatBytes(item.size)} - {item.report ? ingestTargetSummary(item.report) : item.error || 'Ready for ingest'}</em>
                {item.error && <small className="tone-red">{item.error}</small>}
              </article>
            ))}
          </div>
        </>
      )}

      <textarea
        className="draft-textarea ops-textarea"
        value={text}
        onChange={(event) => setText(event.target.value)}
        placeholder="Paste an internal standard, review guide, or approved reviewer note."
      />
      {error && <div className="error-banner">{error}</div>}
      <div className="ops-toolbar">
        <button type="button" className="primary-button" onClick={() => void run()} disabled={running || !text.trim()}>
          <Database className="h-4 w-4" />
          {running ? 'Running ingest' : apply ? 'Apply ingest' : 'Dry-run ingest'}
        </button>
      </div>

      {report && (
        <>
          <div className="ops-grid">
            <Metric label="Chunks" value={`${report.total_chunks}`} />
            <Metric label="Blocked" value={`${report.blocked_chunks}`} tone={report.blocked_chunks ? 'tone-amber' : 'tone-green'} />
            <Metric label="Skill" value={`${report.written_skill_items}/${report.target_counts.skill || 0}`} />
            <Metric label="RAG" value={`${report.written_rag_items}/${report.target_counts.rag || 0}`} />
            <Metric label="Memory" value={`${report.written_memory_items}/${report.target_counts.memory || 0}`} />
          </div>
          <JsonBlock title="Trust summary" value={report.trust_summary} />
          <div className="ops-list compact-list">
            {report.chunks.slice(0, 8).map((chunk) => (
              <article className="ops-list-item static" key={chunk.id}>
                <strong>{chunk.id}</strong>
                <em>{chunk.targets.join(', ')} · blocked: {chunk.blocked_reasons.join(', ') || 'none'}</em>
                <small>{chunk.text}</small>
              </article>
            ))}
          </div>
        </>
      )}

      <div className="knowledge-list-block">
        <div className="knowledge-list-head">
          <strong>저장된 지식 ({knowledgeItems.length})</strong>
          <button type="button" className="mini-chip" onClick={() => void loadKnowledge()}>새로고침</button>
        </div>
        {knowledgeItems.length === 0 ? (
          <p className="knowledge-empty">저장된 지식 항목이 없습니다. 위에서 ingest하면 여기에 표시됩니다.</p>
        ) : (
          <div className="ops-list compact-list">
            {knowledgeItems.map((item) => (
              <article className="ops-list-item static" key={item.id}>
                <strong>{item.source || '(출처 미상)'}</strong>
                <em>{item.id}{item.created_at ? ` · ${item.created_at}` : ''}</em>
                <small>{item.text.slice(0, 160)}{item.text.length > 160 ? '…' : ''}</small>
                <button type="button" className="mini-chip danger knowledge-delete-btn" onClick={() => void removeKnowledge(item.id)}>
                  삭제
                </button>
              </article>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}

function WorkflowPanel({ activeReport }: { activeReport: ComplianceReport | null }) {
  const [status, setStatus] = useState<WorkflowStatus | null>(null);
  const [publishLive, setPublishLive] = useState(false);
  const [publishTarget, setPublishTarget] = useState<'all' | 'slack' | 'notion' | 'jira'>('all');
  const [publishing, setPublishing] = useState(false);
  const [publishResult, setPublishResult] = useState<Record<string, unknown> | null>(null);

  useEffect(() => {
    const load = async () => {
      const response = await fetch('/api/workflow/status');
      const json = await response.json();
      if (json.status === 'success') setStatus(json.data as WorkflowStatus);
    };
    void load();
  }, []);

  const trace = useMemo(() => {
    const raw = asRecord(activeReport?.raw_report);
    return asArray(raw.trace).map(asRecord);
  }, [activeReport]);

  const runPublish = async () => {
    if (!activeReport) return;
    setPublishing(true);
    try {
      const response = await fetch('/api/workflow/publish', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ report: activeReport, target: publishTarget, live: publishLive }),
      });
      const json = await response.json();
      setPublishResult(json.status === 'success' ? json.data as Record<string, unknown> : { error: json.message });
    } finally {
      setPublishing(false);
    }
  };

  return (
    <section className="panel ops-panel">
      <PanelTitle eyebrow="Workflow" title="Publishing, HITL, LangGraph, and MCP surface" icon={GitBranch} />
      {status && (
        <div className="ops-grid two">
          <JsonBlock title="Workflow readiness" value={status} />
          <div className="ops-card tall">
            <span>Active report</span>
            <strong>{activeReport?.audit_log_id || 'No report selected'}</strong>
            <em>{activeReport ? `${activeReport.approval_status} · ${activeReport.risk_level}` : 'Run or select a review first.'}</em>
            <div className="ops-form-grid single">
              <label className="select-field">
                <span>Target</span>
                <select value={publishTarget} onChange={(event) => setPublishTarget(event.target.value as typeof publishTarget)}>
                  <option value="all">All payloads</option>
                  <option value="slack">Slack</option>
                  <option value="notion">Notion</option>
                  <option value="jira">Jira</option>
                </select>
              </label>
              <label className="toggle-row">
                <input type="checkbox" checked={publishLive} onChange={(event) => setPublishLive(event.target.checked)} />
                Live publish when enabled
              </label>
              <p className={`publish-mode-hint ${publishLive ? 'live' : ''}`}>
                {publishLive
                  ? '⚡ 라이브 모드 — API 키와 CS_ENABLE_WORKFLOW_PUBLISH=1 충족 시 외부로 실제 전송됩니다.'
                  : '🔒 미리보기(dry-run) 모드 — 전송 페이로드만 생성하고 외부로 전송하지 않습니다.'}
              </p>
              <button type="button" className="primary-button" onClick={() => void runPublish()} disabled={!activeReport || publishing}>
                <Send className="h-4 w-4" />
                {publishing ? 'Publishing' : publishLive ? '라이브 전송' : '미리보기(dry-run)'}
              </button>
            </div>
          </div>
        </div>
      )}

      <div className="ops-grid two">
        <div className="ops-card tall">
          <span>LangGraph / HITL timeline</span>
          <strong>{trace.length ? `${trace.length} events` : 'No trace on selected report'}</strong>
          <em>Resume controls are shown as unavailable until persisted checkpoints are configured.</em>
          <div className="timeline">
            {trace.slice(-12).map((event, index) => (
              <div className="timeline-row" key={`${String(event.node || event.event || 'event')}-${index}`}>
                <span />
                <strong>{String(event.node || event.event || event.step || `event-${index + 1}`)}</strong>
                <em>{Object.entries(event).slice(0, 3).map(([key, value]) => `${key}=${String(value).slice(0, 42)}`).join(' · ')}</em>
              </div>
            ))}
          </div>
        </div>
        <JsonBlock title="Publish result" value={publishResult || activeReport?.workflow_exports || { status: 'No publish action yet' }} />
      </div>
    </section>
  );
}

function BatchReviewPanel({
  metadata,
  onSelectReport,
  onReportsProduced,
  onRefreshHealth,
}: {
  metadata: InferredMetadata;
  onSelectReport: (report: ComplianceReport) => void;
  onReportsProduced: (reports: ComplianceReport[]) => void;
  onRefreshHealth: () => void;
}) {
  const [content, setContent] = useState('');
  const [running, setRunning] = useState(false);
  const [reports, setReports] = useState<ComplianceReport[]>([]);
  const [batchMeta, setBatchMeta] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState<string | null>(null);

  const items = useMemo(() => content.split(/\n-{3,}\n|\r?\n\r?\n/).map((item) => item.trim()).filter(Boolean), [content]);

  const runBatch = async () => {
    setRunning(true);
    setError(null);
    try {
      const response = await fetch('/api/batch/review', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ items, metadata }),
      });
      const json = await response.json();
      if (!response.ok || json.status !== 'success') throw new Error(json.message || 'batch review failed');
      const nextReports = json.data as ComplianceReport[];
      setReports(nextReports);
      setBatchMeta(asRecord(json.batch));
      onReportsProduced(nextReports);
      if (nextReports[0]) onSelectReport(nextReports[0]);
      onRefreshHealth();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setRunning(false);
    }
  };

  return (
    <section className="panel ops-panel">
      <PanelTitle eyebrow="Batch" title="Reusable-agent review queue" icon={Archive} />
      <textarea
        className="draft-textarea ops-textarea"
        value={content}
        onChange={(event) => setContent(event.target.value)}
        placeholder="Paste multiple drafts separated by a blank line or a line with ---"
      />
      {error && <div className="error-banner">{error}</div>}
      {items.length > 25 && (
        <div className="error-banner" role="alert">
          한 번에 최대 25건까지 심의할 수 있습니다. 현재 {items.length}건 — {items.length - 25}건을 줄여주세요.
        </div>
      )}
      <div className="ops-toolbar">
        <button type="button" className="primary-button" onClick={() => void runBatch()} disabled={running || items.length === 0 || items.length > 25}>
          <Play className="h-4 w-4" />
          {running ? 'Running batch' : `Run ${items.length || 0} reviews`}
        </button>
        <span className={`mini-chip ${items.length > 25 ? 'danger' : ''}`}>{items.length}/25</span>
      </div>
      {reports.some((report) => report.integration?.backend === 'local-rule-engine') && (
        <div className="warning-banner" role="alert">
          ⚠ Python 심의 엔진에 연결되지 않아 일부 항목이 로컬 룰 엔진으로 처리되었습니다. 심층 LLM 분석이 생략되어 정확도가 낮을 수 있습니다.
        </div>
      )}
      {batchMeta && <JsonBlock title="Batch runtime" value={batchMeta} />}
      <div className="ops-list compact-list">
        {reports.map((report) => (
          <button type="button" className="ops-list-item" key={report.review_request_id} onClick={() => onSelectReport(report)}>
            <span className={`status-pill ${riskTone(report.risk_level)}`}>{report.risk_level}</span>
            <strong>{report.approval_status}</strong>
            <em>{report.audit_log_id} · {report.findings.length} findings</em>
            <small>{report.raw_content}</small>
          </button>
        ))}
      </div>
    </section>
  );
}

function PanelTitle({ eyebrow, title, icon: Icon }: { eyebrow: string; title: string; icon: typeof Settings }) {
  return (
    <div className="section-title">
      <div>
        <p className="eyebrow">{eyebrow}</p>
        <h2>{title}</h2>
      </div>
      <Icon className="h-5 w-5 text-forest-700" />
    </div>
  );
}

function StatusMap({ title, values }: { title: string; values: Record<string, boolean> }) {
  return (
    <div className="ops-card tall">
      <span>{title}</span>
      <div className="status-map">
        {Object.entries(values).map(([key, value]) => (
          <div key={key}>
            <span className={`health-dot ${value ? 'health-on' : 'health-warn'}`} />
            <strong>{formatKey(key)}</strong>
            <em>{value ? 'ready' : 'not ready'}</em>
          </div>
        ))}
      </div>
    </div>
  );
}

function SecretMap({ title, values }: { title: string; values: Record<string, { present: boolean; source: string }> }) {
  return (
    <div className="ops-card tall">
      <span>{title}</span>
      <div className="status-map">
        {Object.entries(values).map(([key, value]) => (
          <div key={key}>
            <span className={`health-dot ${value.present ? 'health-on' : 'health-warn'}`} />
            <strong>{formatKey(key)}</strong>
            <em>{value.present ? 'set' : 'unset'}</em>
          </div>
        ))}
      </div>
    </div>
  );
}

function JsonBlock({ title, value }: { title: string; value: unknown }) {
  return (
    <div className="ops-json">
      <div className="ops-json-title">
        <Bot className="h-4 w-4" />
        <span>{title}</span>
      </div>
      <pre>{JSON.stringify(value, null, 2)}</pre>
    </div>
  );
}

function Metric({ label, value, tone = 'tone-neutral' }: { label: string; value: string; tone?: string }) {
  return (
    <div className="ops-card">
      <span>{label}</span>
      <strong className={tone}>{value}</strong>
    </div>
  );
}

function ingestTargetSummary(report?: IngestReport) {
  if (!report) return 'Not processed';
  const targets = [
    `Skill ${report.written_skill_items}/${report.target_counts.skill || 0}`,
    `RAG ${report.written_rag_items}/${report.target_counts.rag || 0}`,
    `Memory ${report.written_memory_items}/${report.target_counts.memory || 0}`,
  ];
  return `${report.total_chunks} chunks - ${report.blocked_chunks} blocked - ${targets.join(', ')}`;
}

function uploadStatusLabel(status: UploadStatus) {
  if (status === 'running') return 'Running';
  if (status === 'done') return 'Done';
  if (status === 'error') return 'Needs review';
  return 'Ready';
}

function uploadStatusTone(status: UploadStatus) {
  if (status === 'done') return 'tone-green';
  if (status === 'error') return 'tone-red';
  if (status === 'running') return 'tone-amber';
  return 'tone-neutral';
}

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function riskTone(risk: string) {
  if (risk === 'CRITICAL' || risk === 'HIGH') return 'tone-red';
  if (risk === 'MEDIUM') return 'tone-amber';
  return 'tone-green';
}

function formatKey(key: string) {
  return key.replace(/_/g, ' ');
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}
