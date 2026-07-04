/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React, { useState, useEffect, useRef } from "react";
import { createPortal } from "react-dom";
import {
  ShieldAlert,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  HelpCircle,
  Search,
  FileText,
  Database,
  RefreshCw,
  Download,
  UserCheck,
  Server,
  BookOpen,
  Plus,
  Trash2,
  TrendingUp,
  Sliders,
  Sparkles,
  FileSpreadsheet,
  Lock,
  Paperclip,
  History,
  ChevronLeft,
  Copy,
  Printer,
  Eye,
  FileCheck,
  ChevronRight,
  ChevronDown
} from "lucide-react";
import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  BarChart,
  Bar,
  Cell,
  PieChart,
  Pie,
  Legend
} from "recharts";

import {
  ComplianceStatus,
  RiskLevel,
  ChannelType,
  BoardReviewItem,
  ScreeningStage,
  ProjectAuditListItem,
  RealTimeMetrics,
  UserSession
} from "./ui-types.js";
import type { ComplianceReport, HealthStatus, InferredMetadata } from "./types.js";
import OperationsPanel, { type OperationsTab } from "./components/OperationsPanel.js";
import LiveReviewProgress from "./components/LiveReviewProgress.js";
import { streamReview, type ReviewNodeStatus } from "./streamReview.js";
import { canSeeTab, canDelete, canSettings, roleBadge } from "./permissions.js";
import {
  reportToAuditItem,
  reportsToAuditItems,
  channelToBackend,
} from "./adapter.js";

const defaultMetadata: InferredMetadata = {
  language: "ko",
  channel: "AppPush",
  product_type: "general",
  target_audience: "all",
};

export default function App() {
  // -------------------------------------------------------------
  // Application State
  // -------------------------------------------------------------
  const [activeTab, setActiveTab] = useState<"screen" | "dashboard" | "history" | "architecture" | OperationsTab>("screen");
  // GNB 2순위 "운영 ▾" 드롭다운 열림 상태
  const [opsMenuOpen, setOpsMenuOpen] = useState<boolean>(false);
  // 운영 ▾ 드롭다운: nav의 overflow-x:auto가 absolute 메뉴를 세로로 clip하므로
  // 버튼 좌표를 잡아 fixed로 띄운다 (nav 경계 밖에서 렌더 → clip 회피).
  const opsBtnRef = useRef<HTMLButtonElement>(null);
  const [opsMenuPos, setOpsMenuPos] = useState<{ top: number; left: number } | null>(null);
  const [session, setSession] = useState<UserSession | null>(null);

  // Bridges to the real backend contract (operational tabs + report round-trip)
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [activeReport, setActiveReport] = useState<ComplianceReport | null>(null);
  const [metadata, setMetadata] = useState<InferredMetadata>(defaultMetadata);

  // Auth selection mock triggers
  const [selectedRole, setSelectedRole] = useState<"ADMIN" | "COMPLIANCE_OFFICER" | "CONTENT_MANAGER">("ADMIN");
  const [authEmail, setAuthEmail] = useState<string>("rkswkdrpwkd01@gmail.com");

  // Screening input simulator
  const [projectName, setProjectName] = useState<string>("JB 비대면 예금 상품 App Push 사전 심의");
  const [selectedChannel, setSelectedChannel] = useState<ChannelType>(ChannelType.BANNER);
  const [inputText, setInputText] = useState<string>("JB 예금 출시 기념, 누구나 최대 연 8% 혜택을 받을 수 있습니다. 조건 없이 원금 보장과 즉시 가입 혜택을 제공합니다.");
  const [isScreening, setIsScreening] = useState<boolean>(false);
  // 입력 시 "수정 제안 생성" 토글. 체크 시 수정 원고/제안 생성, 미체크(기본)면 심의만 수행.
  const [includeRevision, setIncludeRevision] = useState<boolean>(false);
  const [screeningProgress, setScreeningProgress] = useState<number>(0);
  const [liveNodes, setLiveNodes] = useState<Record<string, ReviewNodeStatus>>({});
  // 사후 on-demand 수정 광고 원고 생성 (심의 시 토글 끄고 결과 받은 뒤 버튼으로 생성)
  const [isGeneratingRewrite, setIsGeneratingRewrite] = useState<boolean>(false);
  const [feedbackVerdict, setFeedbackVerdict] = useState<'good' | 'bad' | null>(null);
  const [activeScreeningResult, setActiveScreeningResult] = useState<ProjectAuditListItem | null>(null);

  // File Attachment States
  const [attachedFileBase64, setAttachedFileBase64] = useState<string | null>(null);
  const [attachedFileName, setAttachedFileName] = useState<string>("");
  const [attachedFileType, setAttachedFileType] = useState<string>("");
  // 추출 정보 표시 (이전 멀티모달 UI의 uploadInfo 복원): 추출 후 "파일명 · extractor · N자" 피드백
  const [extractInfo, setExtractInfo] = useState<{ filename: string; extractor: string; charCount: number } | null>(null);
  // 업로드 즉시 자동 심의 트리거 플래그 (base64 세팅이 비동기라 effect로 처리)
  const [autoReviewPending, setAutoReviewPending] = useState<boolean>(false);
  const [isDragging, setIsDragging] = useState<boolean>(false);
  const [isSidebarOpen, setIsSidebarOpen] = useState<boolean>(true);
  const [resultViewMode, setResultViewMode] = useState<"hybrid" | "executive" | "timeline">("hybrid");

  const processFile = (file: File) => {
    // 백엔드 multimodal_input.MAX_BYTES(20MB)에 맞춤 (이전 10MB 제한은 백엔드보다 좁았음)
    if (file.size > 20 * 1024 * 1024) {
      triggerNotification("error", "파일 규정상 크기는 최대 20MB까지 가능합니다.");
      return;
    }
    setExtractInfo(null);
    const reader = new FileReader();
    reader.onloadend = () => {
      setAttachedFileBase64(reader.result as string);
      setAttachedFileName(file.name);
      setAttachedFileType(file.type);
      triggerNotification("success", `파일 인코딩 수렴 완료: ${file.name} · 자동 심의를 시작합니다.`);
      // 업로드 즉시 자동 심의 (이전 멀티모달 UI 동작 복원)
      setAutoReviewPending(true);
    };
    reader.onerror = () => {
      triggerNotification("error", "파일 수집에 실패했습니다.");
    };
    reader.readAsDataURL(file);
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      processFile(file);
    }
  };

  const removeAttachedFile = () => {
    setAttachedFileBase64(null);
    setAttachedFileName("");
    setAttachedFileType("");
    setExtractInfo(null);
    setAutoReviewPending(false);
    triggerNotification("info", "첨부 가해된 파일이 감사 버퍼에서 해제되었습니다.");
  };

  // 업로드 즉시 자동 심의 (base64 세팅 완료 후 effect로 트리거 — 이전 멀티모달 UI 동작 복원)
  useEffect(() => {
    if (autoReviewPending && attachedFileBase64 && !isScreening) {
      setAutoReviewPending(false);
      void handleScreeningSubmit();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoReviewPending, attachedFileBase64]);

  // 클립보드 이미지 붙여넣기 (이전 멀티모달 UI의 handlePaste 복원)
  const handlePaste = (event: React.ClipboardEvent<HTMLTextAreaElement>) => {
    const items = event.clipboardData?.items;
    if (!items) return;
    for (const item of Array.from(items) as DataTransferItem[]) {
      if (item.type.startsWith("image/")) {
        const blob = item.getAsFile();
        if (blob) {
          event.preventDefault();
          const ext = (item.type.split("/")[1] || "png").split("+")[0];
          const renamed = new File([blob], `clipboard-${Date.now()}.${ext}`, { type: item.type });
          processFile(renamed);
          return;
        }
      }
    }
  };

  // Database lists
  const [auditLogs, setAuditLogs] = useState<ProjectAuditListItem[]>([]);
  const [isLogsLoading, setIsLogsLoading] = useState<boolean>(true);
  const [logSearchQuery, setLogSearchQuery] = useState<string>("");
  const [logChannelFilter, setLogChannelFilter] = useState<string>("ALL");
  const [logRiskFilter, setLogRiskFilter] = useState<string>("ALL");
  
  // Real-time fluctuating metrics
  const [metrics, setMetrics] = useState<RealTimeMetrics>({
    currentTps: 0.0,
    totalAudited: 0,
    criticalRatio: 0,
    avgDurationMs: 0,
    timelineGraph: [],
    termFrequencies: []
  });

  // Highlight/Details state
  const [selectedHistoryItem, setSelectedHistoryItem] = useState<ProjectAuditListItem | null>(null);
  const [showCertModal, setShowCertModal] = useState<boolean>(false);
  const [showResetToast, setShowResetToast] = useState<boolean>(false);
  const [notification, setNotification] = useState<{ type: "success" | "error" | "info"; msg: string } | null>(null);

  // Pre-configured compliant & non-compliant compliance scenarios for one-click testing
  const presetScenarios = [
    {
      id: "sc-1",
      title: "원금 보장/확정 수익 표현",
      projectName: "JB 슈퍼적금 특판 온라인 뉴스레터",
      channel: ChannelType.BANNER,
      text: "JB 예금 출시 기념, 누구나 최대 연 8% 혜택을 받을 수 있습니다. 조건 없이 원금 보장과 즉시 가입 혜택을 제공합니다."
    },
    {
      id: "sc-2",
      title: "무조건 승인 대출 문구",
      projectName: "JB 직장인 모바일 신용대출 App Push",
      channel: ChannelType.APP_PUSH,
      text: "[전북은행] 무조건 승인! 연 4.5% 최저마진 모바일 다이렉트 직장인 신용론 출시."
    },
    {
      id: "sc-3",
      title: "개인정보 이메일 접수",
      projectName: "JB우리캐피탈 다이렉트 오토론 리스 설명문구 메일",
      channel: ChannelType.EMAIL,
      text: "고객님의 신분증 복사본을 jbcapital@gmail.com으로 상시 접수해주시면 무조건 연 2.9% 금리 우선순위 승인!"
    },
    {
      id: "sc-4",
      title: "정상 규정 준수 문구",
      projectName: "광주은행 비대면 개인형 IRP 공식 SNS 카드뉴스",
      channel: ChannelType.SNS,
      text: "[광주은행 IRP] 세액공제 한도와 가입 조건을 확인해보세요. 상품 설명서와 유의사항을 확인한 뒤 가입하실 수 있습니다."
    }
  ];

  // -------------------------------------------------------------
  // Data Fetching Hooks & Actions
  // -------------------------------------------------------------
  const fetchSession = async () => {
    try {
      const res = await fetch("/api/auth/session");
      if (res.ok) {
        const data = await res.json();
        if (data.session) {
          setSession(data.session);
          setAuthEmail(data.session.email);
          setSelectedRole(data.session.role);
        }
      }
    } catch (e) {
      console.error("Session fetch failed, using fallback:", e);
    }
  };

  const fetchHealth = async () => {
    try {
      const res = await fetch("/api/health");
      if (res.ok) setHealth(await res.json());
    } catch {
      setHealth(null);
    }
  };

  const fetchAuditLogs = async () => {
    setIsLogsLoading(true);
    try {
      const res = await fetch("/api/history");
      const data = await res.json();
      if (data.status === "success") {
        const reports = (data.data as ComplianceReport[]) || [];
        setAuditLogs(reportsToAuditItems(reports));
      }
    } catch (e) {
      console.error("Audit logs fetch failed:", e);
    } finally {
      setIsLogsLoading(false);
    }
  };

  const fetchRealTimeMetrics = async () => {
    try {
      const res = await fetch("/api/analytics/realtime");
      if (res.ok) {
        const data = await res.json();
        // Shape guard: only trust a well-formed metrics object (avoid crashing
        // on an error JSON / proxy HTML response).
        if (
          data &&
          typeof data.currentTps === "number" &&
          Array.isArray(data.timelineGraph) &&
          Array.isArray(data.termFrequencies)
        ) {
          setMetrics(data);
        }
      }
    } catch (e) {
      console.error("Metrics fetch failed:", e);
    }
  };

  // Perform standard initial mount data fetching
  useEffect(() => {
    fetchSession();
    fetchHealth();
    fetchAuditLogs();
    fetchRealTimeMetrics();

    // Setup periodic metrics update to simulate live operations
    const interval = setInterval(() => {
      fetchRealTimeMetrics();
    }, 4000);

    return () => clearInterval(interval);
  }, []);

  // R1: 현재 활성 탭이 역할 권한 밖이면 안전한 기본 탭(screen)으로 강제 이동
  // (역할 변경/로그아웃 시 stale 탭에 머무는 것 방지)
  useEffect(() => {
    if (!canSeeTab(session?.role, activeTab)) {
      setActiveTab("screen");
    }
  }, [session, activeTab]);

  // Show auto-dismiss notifications helper
  const triggerNotification = (type: "success" | "error" | "info", msg: string) => {
    setNotification({ type, msg });
    setTimeout(() => {
      setNotification(null);
    }, 4580);
  };

  // 2. Clear / Reset Log Database
  const handleResetLogs = async () => {
    if (!canDelete(session?.role)) {
      triggerNotification("error", "감사 기록 초기화는 보안 감사 책임자(ADMIN) 권한이 필요합니다.");
      return;
    }
    try {
      const res = await fetch("/api/history/clear", { method: "POST" });
      const data = await res.json();
      if (data.status === "success") {
        const reports = (data.data as ComplianceReport[]) || [];
        setAuditLogs(reportsToAuditItems(reports));
        fetchRealTimeMetrics();
        setShowResetToast(true);
        triggerNotification("success", "감사 DB 로그가 초기 원본 스냅샷으로 정상 복원되었습니다.");
        setTimeout(() => setShowResetToast(false), 3000);
      }
    } catch (e) {
      triggerNotification("error", "DB 리셋 수행 중 거부 상호작용 오류.");
    }
  };

  // 3. Delete Audit Log Entry (Admin Only)
  const handleDeleteLog = async (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (!canDelete(session?.role)) {
      triggerNotification("error", "이 작업은 보안 감사 책임자(ADMIN) 권한이 필요합니다.");
      return;
    }
    if (!confirm("해당 검토 기록을 현재 목록에서 제거하시겠습니까?\n\n※ 변조 방지(tamper-evidence) 규정상 영속 감사 로그(compliance_audit.jsonl)는 보존되며, 서버 재시작 시 목록에 다시 표시됩니다.")) {
      return;
    }

    try {
      const res = await fetch(`/api/history/${encodeURIComponent(id)}`, { method: "DELETE" });
      if (res.ok) {
        setAuditLogs(prev => prev.filter(item => item.id !== id));
        fetchRealTimeMetrics();
        triggerNotification("success", `로그 ID: ${id} 항목이 현재 목록에서 제거되었습니다. (영속 감사 추적은 규정상 보존)`);
        if (selectedHistoryItem?.id === id) {
          setSelectedHistoryItem(null);
        }
      }
    } catch (e) {
      triggerNotification("error", "로그 파기 실행 중 네트워크 오류 발생.");
    }
  };

  // R3: 클릭한 버튼이 속한 인증서 카드(.cert-card)만 인쇄. @media print가 그 외 영역을 숨긴다.
  const handlePrintCertificate = (e: React.MouseEvent) => {
    const card = (e.currentTarget as HTMLElement).closest(".cert-card");
    if (card) {
      card.classList.add("print-area");
      window.print();
      window.setTimeout(() => card.classList.remove("print-area"), 300);
    } else {
      window.print();
    }
  };

  // 수정 광고 원고 사후 생성 — /api/review/rewrite 호출 후 결과를 현재 리포트에 반영.
  // 심의 결과(findings)는 불변, rewrite만 추가 생성한다.
  const handleGenerateRewrite = async () => {
    if (!activeScreeningResult || isGeneratingRewrite) return;
    setIsGeneratingRewrite(true);
    try {
      const res = await fetch("/api/review/rewrite", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          content: activeScreeningResult.inputContent,
          review_request_id: activeScreeningResult.id,
        }),
      });
      const data = await res.json();
      if (res.ok && data.status === "success" && data.data?.rewritten) {
        setActiveScreeningResult((prev) => (prev ? { ...prev, rewrittenAd: data.data.rewritten } : prev));
        triggerNotification("success", "AI 수정 광고 원고가 생성되었습니다. 바로 복사해 사용할 수 있습니다.");
      } else {
        triggerNotification("error", data.message || "수정 원고 생성에 실패했습니다. (LLM 런타임 확인 필요)");
      }
    } catch (e) {
      triggerNotification("error", "수정 원고 생성 중 네트워크 오류가 발생했습니다.");
    } finally {
      setIsGeneratingRewrite(false);
    }
  };

  // 리포트 👍/👎 피드백 → 자동 학습 루프에 '사람 검증' 신호 주입 (good=정확, bad=오탐/오심).
  const handleFeedback = async (verdict: 'good' | 'bad') => {
    if (!activeScreeningResult || feedbackVerdict) return;
    setFeedbackVerdict(verdict);
    try {
      const res = await fetch("/api/review/feedback", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          content: activeScreeningResult.inputContent,
          verdict,
          review_request_id: activeScreeningResult.id,
        }),
      });
      const data = await res.json();
      // 알림 없이 조용히 반영 — 성공 시 버튼 색 유지, 실패 시 색 원복.
      if (!(res.ok && data.status === "success")) {
        setFeedbackVerdict(null);
      }
    } catch (e) {
      setFeedbackVerdict(null);
    }
  };

  // 다른 리포트 선택 시 피드백 상태 초기화 (리포트별 1회 피드백).
  useEffect(() => {
    setFeedbackVerdict(null);
  }, [activeScreeningResult?.id]);

  // 4. Run Active Sentinel Screening Algorithm
  // R9: overrideContent 지정 시(재심의) 해당 원문으로 심의 — setState 비동기 stale 회피
  const handleScreeningSubmit = async (e?: React.FormEvent, overrideContent?: string) => {
    e?.preventDefault();
    if (!overrideContent && !inputText.trim() && !attachedFileBase64) {
      triggerNotification("error", "심의할 광고안 텍스트를 기입하거나, 이미지 또는 문서 파일을 탑재해 주십시오.");
      return;
    }

    setIsScreening(true);
    setScreeningProgress(1);
    setActiveScreeningResult(null);

    // 실제 백엔드 단계(6인 보드→verifier→cross-model) 완료 시점을 알 수 없어,
    // 가짜 단계 진행(1→7 타이머)을 제거한다. 진행은 indeterminate(불확정)로 표시한다.
    // interval은 아래 clearInterval들의 cleanup 호환을 위한 no-op placeholder.
    const interval = setInterval(() => {}, 1 << 30);

    try {
      // 멀티모달 버그 수정: 첨부 파일은 base64를 /api/extract로 보내 실제 텍스트를 추출한 뒤
      // 그 텍스트를 심의 대상 content로 사용한다. (이전엔 파일명 placeholder만 전송돼 내용이 심의에서 누락됨)
      let reviewContent = (overrideContent ?? inputText).trim();
      if (!overrideContent && attachedFileBase64) {
        try {
          // attachedFileBase64는 data URL("data:<mime>;base64,XXXX") — /api/extract는 순수 base64만 받는다.
          const contentBase64 = attachedFileBase64.includes(",")
            ? attachedFileBase64.slice(attachedFileBase64.indexOf(",") + 1)
            : attachedFileBase64;
          const extractRes = await fetch("/api/extract", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ filename: attachedFileName, content_base64: contentBase64 }),
          });
          const extractData = await extractRes.json();
          if (extractRes.ok && extractData.status === "success") {
            const extractedText = String(extractData.data?.text || "").trim();
            // 추출 정보 표시 (이전 멀티모달 UI의 uploadInfo 복원)
            setExtractInfo({
              filename: String(extractData.data?.source_filename || attachedFileName),
              extractor: String(extractData.data?.extractor || "unknown"),
              charCount: Number(extractData.data?.char_count || extractedText.length),
            });
            // 본문 텍스트가 있으면 추출 텍스트를 덧붙이고, 없으면 추출 텍스트만 사용
            reviewContent = reviewContent
              ? `${reviewContent}\n\n${extractedText}`
              : extractedText;
          } else if (!reviewContent) {
            clearInterval(interval);
            setIsScreening(false);
            triggerNotification("error", extractData.message || "첨부 파일 텍스트 추출에 실패했습니다.");
            return;
          }
        } catch {
          if (!reviewContent) {
            clearInterval(interval);
            setIsScreening(false);
            triggerNotification("error", "첨부 파일 추출 채널 장애.");
            return;
          }
        }
      }

      // T4: 실시간 SSE 스트림 구독 — 노드별 진행을 liveNodes에 반영한다.
      // 스트림이 불가하거나 실패하면 기존 비스트리밍 /api/review로 폴백해 심의 결과를 보존한다.
      const reviewBody = {
        content: reviewContent || `(첨부 파일 심의 요청: ${attachedFileName})`,
        metadata: {
          ...metadata,
          channel: channelToBackend(selectedChannel),
        },
        // 입력 시 토글: true면 수정 제안/원고 생성, false면 심의만 (광고/약관 공통).
        include_revision: includeRevision,
      };
      setLiveNodes({});

      let report: ComplianceReport | null = null;
      try {
        report = await streamReview(reviewBody, {
          onNode: (node, status) => {
            setLiveNodes((prev) => ({ ...prev, [node]: status }));
          },
        });
      } catch {
        // 스트리밍 미지원/실패(워커 OFF, 네트워크 등) → 비스트리밍 폴백
        const res = await fetch("/api/review", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(reviewBody),
        });
        const data = await res.json();
        if (res.ok && data.status === "success") {
          report = data.data as ComplianceReport;
        } else {
          clearInterval(interval);
          setIsScreening(false);
          triggerNotification("error", data.message || "서버 준법 심사 분석 수행 실패.");
          return;
        }
      }

      if (!report) {
        clearInterval(interval);
        setIsScreening(false);
        triggerNotification("error", "서버 준법 심사 분석 수행 실패.");
        return;
      }

      const item = reportToAuditItem(report, {
        projectName,
        channel: selectedChannel,
        userEmail: session?.email,
        fileName: attachedFileName || undefined,
        fileMimeType: attachedFileType || undefined,
        fileData: attachedFileBase64 || undefined,
      });
      clearInterval(interval);
      setActiveReport(report);
      setActiveScreeningResult(item);
      setAuditLogs(prev => [item, ...prev]);
      setIsScreening(false);
      // Purge transient attached file state upon successful audit log entry
      setAttachedFileBase64(null);
      setAttachedFileName("");
      setAttachedFileType("");
      triggerNotification("success", "AI Agent의 원스톱 실시간 준법 심의가 결판되었습니다.");
    } catch (e) {
      clearInterval(interval);
      setIsScreening(false);
      triggerNotification("error", "프런트 인터랙션 채널 장애.");
    }
  };

  // Quick preset scenario loader inline click
  const loadPreset = (preset: typeof presetScenarios[0]) => {
    setProjectName(preset.projectName);
    setSelectedChannel(preset.channel);
    setInputText(preset.text);
    setActiveScreeningResult(null);
    triggerNotification("info", `샘플 시나리오가 로드되었습니다: "${preset.projectName}"`);
  };

  // Filter logs logic
  const filteredLogs = auditLogs.filter(item => {
    const query = logSearchQuery.toLowerCase();
    const matchesSearch = 
      item.projectName.toLowerCase().includes(query) ||
      item.id.toLowerCase().includes(query) ||
      item.inputContent.toLowerCase().includes(query) ||
      (item.findingsSum && item.findingsSum.toLowerCase().includes(query));

    const matchesChannel = logChannelFilter === "ALL" || item.channel === logChannelFilter;
    const matchesRisk = logRiskFilter === "ALL" || item.riskLevel === logRiskFilter;

    return matchesSearch && matchesChannel && matchesRisk;
  });

  // Group logs by date for ChatGPT-like sidebar grouping
  const groupLogsByDate = (logs: ProjectAuditListItem[]) => {
    const groups: { [key: string]: ProjectAuditListItem[] } = {};
    
    logs.forEach(log => {
      const dateObj = new Date(log.createdAt);
      let dateStr = "";
      
      if (isNaN(dateObj.getTime())) {
        dateStr = "기타 이전 기록";
      } else {
        const today = new Date();
        const yesterday = new Date();
        yesterday.setDate(today.getDate() - 1);
        
        const isToday = dateObj.toDateString() === today.toDateString();
        const isYesterday = dateObj.toDateString() === yesterday.toDateString();
        
        if (isToday) {
          dateStr = "오늘";
        } else if (isYesterday) {
          dateStr = "어제";
        } else {
          const diffTime = Math.abs(today.getTime() - dateObj.getTime());
          const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));
          if (diffDays <= 7) {
            dateStr = "최근 7일";
          } else if (diffDays <= 30) {
            dateStr = "최근 30일";
          } else {
            dateStr = `${dateObj.getFullYear()}년 ${dateObj.getMonth() + 1}월`;
          }
        }
      }
      
      if (!groups[dateStr]) {
        groups[dateStr] = [];
      }
      groups[dateStr].push(log);
    });
    
    return groups;
  };

  // Calculate high-fidelity stats for visual graphs from dynamic logs array
  const riskCounts = {
    [RiskLevel.LOW]: auditLogs.filter(l => l.riskLevel === RiskLevel.LOW).length,
    [RiskLevel.MEDIUM]: auditLogs.filter(l => l.riskLevel === RiskLevel.MEDIUM).length,
    [RiskLevel.HIGH]: auditLogs.filter(l => l.riskLevel === RiskLevel.HIGH).length,
    [RiskLevel.CRITICAL]: auditLogs.filter(l => l.riskLevel === RiskLevel.CRITICAL).length,
  };

  const channelCounts = {
    [ChannelType.BANNER]: auditLogs.filter(l => l.channel === ChannelType.BANNER).length,
    [ChannelType.APP_PUSH]: auditLogs.filter(l => l.channel === ChannelType.APP_PUSH).length,
    [ChannelType.SNS]: auditLogs.filter(l => l.channel === ChannelType.SNS).length,
    [ChannelType.EMAIL]: auditLogs.filter(l => l.channel === ChannelType.EMAIL).length,
    [ChannelType.LANDING]: auditLogs.filter(l => l.channel === ChannelType.LANDING).length,
  };

  const riskChartData = [
    { name: "CRITICAL (치명)", value: riskCounts[RiskLevel.CRITICAL] || 2, color: "#be123c" },
    { name: "HIGH (고위험)", value: riskCounts[RiskLevel.HIGH] || 4, color: "#e11d48" },
    { name: "MEDIUM (주의)", value: riskCounts[RiskLevel.MEDIUM] || 8, color: "#f59e0b" },
    { name: "LOW (안전)", value: riskCounts[RiskLevel.LOW] || 15, color: "#10b981" }
  ];

  const channelChartData = [
    { name: "온라인 배너", value: channelCounts[ChannelType.BANNER] || 5 },
    { name: "앱푸시 알림", value: channelCounts[ChannelType.APP_PUSH] || 4 },
    { name: "공식 SNS", value: channelCounts[ChannelType.SNS] || 3 },
    { name: "고객 이메일", value: channelCounts[ChannelType.EMAIL] || 2 },
    { name: "원물 랜딩", value: channelCounts[ChannelType.LANDING] || 1 }
  ];

  const statusCounts = {
    [ComplianceStatus.APPROVED]: auditLogs.filter(l => l.status === ComplianceStatus.APPROVED).length,
    [ComplianceStatus.REJECTED]: auditLogs.filter(l => l.status === ComplianceStatus.REJECTED).length,
    [ComplianceStatus.AMENDED]: auditLogs.filter(l => l.status === ComplianceStatus.AMENDED).length,
    [ComplianceStatus.PENDING]: auditLogs.filter(l => l.status === ComplianceStatus.PENDING).length
  };

  // Quick helper to download compliance report as text summary / digital log
  const handleDownloadCsv = () => {
    let csvContent = "data:text/csv;charset=utf-8,";
    csvContent += "심의 고유번호,프로젝트명,광고채널,위험수준,최종판정,심의일시,위반표현,검토상세 요약\n";
    
    auditLogs.forEach(item => {
      const row = [
        item.id,
        `"${item.projectName.replace(/"/g, '""')}"`,
        item.channel,
        item.riskLevel,
        item.status,
        item.createdAt,
        `"${item.detectedViolations.join(', ')}"`,
        `"${(item.findingsSum || '').replace(/"/g, '""')}"`
      ].join(",");
      csvContent += row + "\n";
    });

    const encodedUri = encodeURI(csvContent);
    const link = document.createElement("a");
    link.setAttribute("href", encodedUri);
    link.setAttribute("download", `JB-Sentinel-FullAuditReport_${new Date().toISOString().substring(0,10)}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    triggerNotification("success", "전체 감사 로그 테이블이 CSV 파일 규격으로 산출 및 다운로드되었습니다.");
  };

  const workerStatus = health?.python_worker?.status || "standby";

  return (
    <div className="premium-app-shell min-h-screen flex flex-col font-sans text-slate-800">
      
      {/* -------------------------------------------------------------
          Header Area (Redesigned to white brand layout from user's image)
          ------------------------------------------------------------- */}
      <header className="premium-header sticky top-0 z-40 py-3.5 px-6 flex flex-col md:flex-row justify-between items-center gap-4">
        
        {/* Logo & Application Name (아이콘 마크 제거 — 텍스트 "율리"만) */}
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2">
            <span className="font-sans font-bold text-base text-slate-800 tracking-tight">율리</span>
            <span className="text-slate-300">|</span>
            <span className="text-xs text-slate-500 font-medium font-sans whitespace-nowrap">AI 준법 심의 시스템</span>
          </div>
        </div>

        {/* Navigation Bar Header Links — 3단 위계 IA (GNB 재설계) */}
        <nav className="premium-nav flex flex-nowrap items-center justify-center p-0.5 rounded-xl gap-0.5">
          {/* 1순위 · 핵심 업무 (심의 → 결과 → 이력 흐름) */}
          <button
            id="nav-tab-screen"
            onClick={() => {
              setActiveTab("screen");
              setActiveScreeningResult(null);
              setIsScreening(false);
            }}
            className={`px-3.5 py-1.5 text-xs font-semibold rounded-lg transition-all cursor-pointer ${
              activeTab === "screen"
                ? "bg-white text-slate-800 shadow-[0_2px_8px_-1px_rgba(0,0,0,0.06)]"
                : "text-slate-600 hover:text-slate-800"
            }`}
          >
            AI 심의
          </button>
          <button
            id="nav-tab-history"
            onClick={() => setActiveTab("history")}
            className={`px-3.5 py-1.5 text-xs font-semibold rounded-lg transition-all cursor-pointer ${
              activeTab === "history"
                ? "bg-white text-slate-800 shadow-[0_2px_8px_-1px_rgba(0,0,0,0.06)]"
                : "text-slate-600 hover:text-slate-800"
            }`}
          >
            심의 이력 ({auditLogs.length})
          </button>
          {canSeeTab(session?.role, "dashboard") && (
            <button
              id="nav-tab-dashboard"
              onClick={() => setActiveTab("dashboard")}
              className={`px-3.5 py-1.5 text-xs font-semibold rounded-lg transition-all cursor-pointer ${
                activeTab === "dashboard"
                  ? "bg-white text-slate-800 shadow-[0_2px_8px_-1px_rgba(0,0,0,0.06)]"
                  : "text-slate-600 hover:text-slate-800"
              }`}
            >
              분석 대시보드
            </button>
          )}

          {/* 2순위 · 운영·지식 (운영 ▾ 드롭다운으로 접음) */}
          {(() => {
            const opsItems = ([
              ["knowledge", "규정·지식"],
              ["workflow", "심사 절차"],
              ["batch", "일괄 심의"],
              ["audit", "감사 추적"],
            ] as [OperationsTab, string][]).filter(([key]) => canSeeTab(session?.role, key));
            if (opsItems.length === 0) return null;
            const opsActive = opsItems.some(([key]) => key === activeTab);
            return (
              <div className="relative">
                <button
                  ref={opsBtnRef}
                  id="nav-ops-menu"
                  onClick={() => setOpsMenuOpen((v) => {
                    const next = !v;
                    if (next && opsBtnRef.current) {
                      const r = opsBtnRef.current.getBoundingClientRect();
                      setOpsMenuPos({ top: r.bottom + 6, left: r.left });
                    }
                    return next;
                  })}
                  className={`flex items-center gap-1 px-3.5 py-1.5 text-xs font-semibold rounded-lg transition-all cursor-pointer ${
                    opsActive
                      ? "bg-white text-slate-800 shadow-[0_2px_8px_-1px_rgba(0,0,0,0.06)]"
                      : "text-slate-600 hover:text-slate-800"
                  }`}
                >
                  운영
                  <ChevronDown className={`w-3.5 h-3.5 transition-transform ${opsMenuOpen ? "rotate-180" : ""}`} />
                </button>
                {opsMenuOpen && createPortal(
                  <>
                    <div className="fixed inset-0 z-[90]" onClick={() => setOpsMenuOpen(false)} />
                    <div
                      className="fixed z-[100] min-w-[160px] bg-white border border-slate-200 rounded-xl shadow-lg p-1"
                      style={{ top: opsMenuPos?.top ?? 0, left: opsMenuPos?.left ?? 0 }}
                    >
                      {opsItems.map(([key, label]) => (
                        <button
                          key={key}
                          id={`nav-tab-${key}`}
                          onClick={() => { setActiveTab(key); setOpsMenuOpen(false); }}
                          className={`w-full text-left px-3 py-1.5 text-xs font-semibold rounded-lg transition-all cursor-pointer ${
                            activeTab === key
                              ? "bg-slate-100 text-slate-800"
                              : "text-slate-600 hover:bg-slate-50 hover:text-slate-800"
                          }`}
                        >
                          {label}
                        </button>
                      ))}
                    </div>
                  </>,
                  document.body
                )}
              </div>
            );
          })()}
        </nav>

        {/* 우측 클러스터: 시스템/계정 (엔진 상태칩 · 역할 배지 제거) */}
        <div className="flex items-center gap-0.5">
          <button
            id="nav-tab-architecture"
            onClick={() => setActiveTab("architecture")}
            className={`px-3.5 py-1.5 text-xs font-semibold rounded-lg transition-all cursor-pointer ${
              activeTab === "architecture"
                ? "bg-white text-slate-800 shadow-[0_2px_8px_-1px_rgba(0,0,0,0.06)]"
                : "text-slate-500 hover:text-slate-800"
            }`}
          >
            시스템 구성
          </button>
          {canSeeTab(session?.role, "admin") && (
            <button
              id="nav-tab-admin"
              onClick={() => setActiveTab("admin")}
              className={`px-3.5 py-1.5 text-xs font-semibold rounded-lg transition-all cursor-pointer ${
                activeTab === "admin"
                  ? "bg-white text-slate-800 shadow-[0_2px_8px_-1px_rgba(0,0,0,0.06)]"
                  : "text-slate-500 hover:text-slate-800"
              }`}
            >
              관리자
            </button>
          )}
        </div>

      </header>

      {/* -------------------------------------------------------------
          Notification Banner
          ------------------------------------------------------------- */}
      {notification && (
        <div className={`fixed bottom-4 right-4 z-50 flex items-center gap-2.5 px-4 py-3 rounded-lg shadow-xl text-xs font-medium border transition-all transform scale-100 duration-300 animate-bounce ${
          notification.type === "success" 
            ? "bg-[#ecfdf5] text-emerald-800 border-emerald-200 shadow-emerald-100" 
            : notification.type === "error"
            ? "bg-[#fff1f2] text-rose-800 border-rose-200 shadow-rose-100"
            : "bg-[#f5f3ff] text-indigo-900 border-indigo-200 shadow-indigo-100"
        }`}>
          {notification.type === "success" && <CheckCircle2 className="w-4.5 h-4.5 text-emerald-500" />}
          {notification.type === "error" && <XCircle className="w-4.5 h-4.5 text-rose-500" />}
          {notification.type === "info" && <Sliders className="w-4.5 h-4.5 text-indigo-500" />}
          <span>{notification.msg}</span>
        </div>
      )}

      {/* -------------------------------------------------------------
          Main Content Container
          ------------------------------------------------------------- */}
      <main className="flex-grow max-w-[1520px] w-full mx-auto p-4 md:p-8">

        {/* -------------------------------------------------------------
            TAB 1: Real-time Compliance Screening (실시간 AI 심의기)
            ------------------------------------------------------------- */}
        {activeTab === "screen" && (
          <div className="premium-workspace-grid flex flex-col lg:flex-row gap-6 items-start relative select-none w-full">
            
            {/* 1. Left Collapsible History Sidebar like ChatGPT/Claude/Gemini */}
            <div 
              className={`shrink-0 transition-all duration-300 ease-in-out ${
                isSidebarOpen 
                  ? "order-2 lg:order-none w-full lg:w-[280px] opacity-100 block text-left"
                  : "w-0 h-0 lg:w-0 lg:h-auto overflow-hidden opacity-0 hidden"
              }`}
            >
              <div className="premium-sidebar-panel p-4 flex flex-col h-[700px] w-full">
                
                {/* Sidebar Header */}
                <div className="flex items-center justify-between gap-2 pb-3 border-b border-slate-200/60 mb-3.5">
                  <div className="flex items-center gap-1.5 min-w-0">
                    <History className="w-4 h-4 text-slate-600 shrink-0" />
                    <span className="text-xs font-bold text-slate-800 truncate font-sans tracking-tight">최근 심의 작업 이력</span>
                  </div>
                  <button
                    type="button"
                    onClick={() => setIsSidebarOpen(false)}
                    className="p-1.5 hover:bg-slate-200/60 text-slate-500 hover:text-slate-700 rounded-lg cursor-pointer transition-all"
                    title="사이드바 접기"
                  >
                    <ChevronLeft className="w-4 h-4" />
                  </button>
                </div>

                {/* New Screening Button (새 심의 시작) like New Chat */}
                <button
                  type="button"
                  onClick={() => {
                    setActiveScreeningResult(null);
                    setIsScreening(false);
                    setInputText("");
                    setProjectName(`신규 상품 심의-${new Date().toLocaleDateString('ko-KR')}`);
                    setAttachedFileBase64(null);
                    setAttachedFileName("");
                    setAttachedFileType("");
                    triggerNotification("info", "새로운 준법 심의 작업창이 시작되었습니다.");
                  }}
                  className="w-full premium-secondary-action text-[#0f172a] font-bold text-xs p-3 rounded-xl mb-4 transition-all cursor-pointer flex items-center justify-center gap-2 select-none active:scale-98"
                >
                  <Plus className="w-3.5 h-3.5 text-slate-500" />
                  새로 심의하기
                </button>

                {/* Scrollable Grouped History Logs */}
                <div className="flex-grow overflow-y-auto space-y-4 pr-1 scrollbar-thin">
                  {isLogsLoading ? (
                    <div className="text-center py-10 text-xs text-slate-400 font-medium animate-pulse">
                      기록 불러오는 중...
                    </div>
                  ) : Object.keys(groupLogsByDate(auditLogs)).length === 0 ? (
                    <div className="text-center py-20 text-xs text-slate-400 font-medium">
                      최근 심의한 내역이 없습니다.
                    </div>
                  ) : (
                    Object.entries(groupLogsByDate(auditLogs)).map(([dateLabel, logs]) => (
                      <div key={dateLabel} className="space-y-1.5 text-left">
                        <span className="text-[10px] text-slate-400 font-extrabold tracking-wider uppercase block px-1">
                          {dateLabel}
                        </span>
                        <div className="space-y-1">
                          {logs.map((log) => {
                            const isSelected = activeScreeningResult?.id === log.id;
                            return (
                              <div key={log.id} className="relative group/item">
                              <button
                                type="button"
                                onClick={() => {
                                  setActiveScreeningResult(log);
                                  setIsScreening(false);
                                  setInputText(log.inputContent);
                                  setProjectName(log.projectName);
                                  setSelectedChannel(log.channel);
                                  if (log.fileName) {
                                    setAttachedFileName(log.fileName);
                                    setAttachedFileType(log.fileMimeType || "");
                                    setAttachedFileBase64(log.fileData || "");
                                  } else {
                                    setAttachedFileName("");
                                    setAttachedFileType("");
                                    setAttachedFileBase64(null);
                                  }
                                  triggerNotification("success", `심의 기록 [${log.projectName}]을(를) 로드했습니다.`);
                                }}
                                className={`w-full text-left p-2.5 rounded-xl text-xs transition-all relative flex flex-col gap-1 cursor-pointer group ${
                                  isSelected
                                    ? "bg-[#1e293b] text-white shadow-sm font-semibold"
                                    : "bg-white hover:bg-slate-100 border border-slate-200/50 text-slate-700"
                                }`}
                              >
                                <div className="flex items-center justify-between gap-1.5 min-w-0">
                                  <span className={`text-[9px] uppercase font-bold tracking-wider px-1.5 py-0.5 rounded ${
                                    isSelected
                                      ? "bg-slate-700 text-slate-200"
                                      : log.riskLevel === RiskLevel.CRITICAL
                                      ? "bg-rose-50 text-rose-600"
                                      : log.riskLevel === RiskLevel.HIGH
                                      ? "bg-amber-50 text-amber-600"
                                      : "bg-emerald-50 text-emerald-600"
                                  }`}>
                                    {log.riskLevel}
                                  </span>
                                  <span className={`text-[9px] font-mono font-medium shrink-0 ${isSelected ? "text-slate-300" : "text-slate-400"}`}>
                                    {log.id}
                                  </span>
                                </div>
                                <div className="font-bold truncate w-full pr-1 font-sans">
                                  {log.projectName}
                                </div>
                                <div className={`text-[10px] truncate w-full ${isSelected ? "text-slate-300" : "text-[#64748b]"}`}>
                                  {log.inputContent ? log.inputContent : (log.fileName ? `[첨부 파일]: ${log.fileName}` : "")}
                                </div>
                                {log.fileName && (
                                  <div className={`flex items-center gap-0.5 text-[9px] mt-0.5 font-semibold ${isSelected ? "text-indigo-200" : "text-indigo-600"}`}>
                                    <Paperclip className="w-2.5 h-2.5 shrink-0" /> {log.fileName}
                                  </div>
                                )}
                              </button>
                              {canDelete(session?.role) && (
                                <button
                                  type="button"
                                  onClick={(e) => handleDeleteLog(log.id, e)}
                                  className="absolute bottom-1.5 right-1.5 p-1 rounded-md bg-white/90 border border-slate-200 text-slate-400 opacity-0 group-hover/item:opacity-100 hover:bg-rose-50 hover:border-rose-200 hover:text-red-600 transition-all cursor-pointer z-10"
                                  title="심의 기록 삭제 (Admin 전용)"
                                >
                                  <Trash2 className="w-3 h-3" />
                                </button>
                              )}
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    ))
                  )}
                </div>
                
                {/* Footer status */}
                <div className="mt-2 pt-2 border-t border-slate-200/60 flex items-center justify-between text-[10px] text-slate-400 select-none">
                  <span>이력 자동 보존</span>
                  <span>누적 {auditLogs.length}건</span>
                </div>

              </div>
            </div>

            {/* Close side controls. If Sidebar is closed, show dynamic trigger handle */}
            {!isSidebarOpen && (
              <button
                type="button"
                onClick={() => setIsSidebarOpen(true)}
                className="hidden lg:flex fixed left-0 top-1/4 z-30 bg-slate-900 hover:bg-slate-800 text-white p-2.5 rounded-r-xl shadow-lg cursor-pointer transition-all items-center justify-center border-l-0 group"
                title="심의 이력 사이드바 열기"
              >
                <History className="w-5 h-5" />
                <span className="max-w-0 overflow-hidden group-hover:max-w-24 group-hover:ml-2 text-xs font-bold transition-all duration-300 ease-out whitespace-nowrap">
                  이력 열기
                </span>
              </button>
            )}

            {/* 2. Main content area (right side) */}
            <div className="order-1 lg:order-none flex-grow w-full max-w-full min-w-0">
              
              {/* Show/Hide drawer button for Tablet/Mobile if sidebar is closed, and alternative button on upper workspace */}
              {!isSidebarOpen && (
                <div className="flex lg:hidden items-center mb-4">
                  <button
                    type="button"
                    onClick={() => setIsSidebarOpen(true)}
                    className="flex items-center gap-1.5 bg-white hover:bg-slate-50 text-slate-700 font-bold text-xs px-3.5 py-2 rounded-xl border border-slate-200 shadow-sm cursor-pointer select-none"
                  >
                    <History className="w-3.5 h-3.5 text-slate-500 animate-pulse" />
                    <span>작업 이력 보이기</span>
                  </button>
                </div>
              )}

              <div className="animate-fade-in w-full">
            
            {/* If not screening and no result yet: Render EXACT replica of the uploaded image! */}
            {!isScreening && !activeScreeningResult ? (
              <div id="pristine-landing-view" className="max-w-4xl mx-auto text-center py-6 md:py-12">
                
                {/* Hero Headers */}
                <div className="mb-10 text-center font-sans tracking-tight">
                  <span className="block text-xs font-bold text-[#475569] uppercase tracking-widest mb-3.5">
                    JB 금융그룹 · 대고객 콘텐츠 준법 심의
                  </span>
                  <h1 className="text-3xl md:text-[44px] font-extrabold text-[#0f172a] mb-5 tracking-tight leading-snug">
                    심의할 콘텐츠를 입력해 주십시오
                  </h1>
                  <p className="text-xs md:text-[13px] text-slate-500 leading-relaxed max-w-xl mx-auto font-medium">
                    입력된 마케팅 콘텐츠는 6인 준법 보드의 다관점 검토를 거쳐
                    <br />
                    표현 리스크 · 필수 고지 · 수정 권고가 산출됩니다.
                  </p>
                </div>

                {/* Central Submission Card with Drag & Drop */}
                <div 
                  className={`premium-input-panel p-6 md:p-8 text-left max-w-3xl mx-auto relative mb-6 transition-all ${
                    isDragging 
                      ? "is-dragging scale-[1.01]"
                      : ""
                  }`}
                  onDragOver={(e) => {
                    e.preventDefault();
                    setIsDragging(true);
                  }}
                  onDragLeave={() => setIsDragging(false)}
                  onDrop={(e) => {
                    e.preventDefault();
                    setIsDragging(false);
                    const file = e.dataTransfer.files?.[0];
                    if (file) processFile(file);
                  }}
                >
                  
                  {/* Textarea inside the card */}
                  <div className="relative">
                    <textarea
                      id="input-pristine-textarea"
                      className="premium-textarea w-full text-xs md:text-sm text-slate-850 placeholder-[#94a3b8] focus:outline-none resize-none h-40 font-sans leading-relaxed"
                      placeholder="심의 대상 문구를 입력하거나 이미지/문서 파일을 업로드하십시오 (PDF/DOCX/XLSX/RTF/HTML/HWPX/이미지 OCR, ~20MB · 클립보드 이미지 붙여넣기 가능). 예) JB 슈퍼적금 출시, 누구나 연 8% 확정 수익..."
                      value={inputText}
                      onChange={(e) => setInputText(e.target.value)}
                      onPaste={handlePaste}
                    />

                    {/* File preview / selection indicator panel */}
                    {attachedFileBase64 ? (
                      <div className="mt-3 p-3 bg-slate-50 border border-slate-200/60 rounded-xl flex items-center justify-between gap-3 animate-fade-in text-left">
                        <div className="flex items-center gap-3 overflow-hidden">
                          {attachedFileType.startsWith("image/") ? (
                            <img
                              src={attachedFileBase64}
                              alt="Attached Preview"
                              className="w-12 h-12 object-cover rounded-lg border border-slate-200/80 shadow-sm shrink-0"
                              referrerPolicy="no-referrer"
                            />
                          ) : (
                            <div className="w-12 h-12 bg-slate-100 text-[#475569] flex items-center justify-center rounded-lg border border-slate-200/80 shadow-sm shrink-0">
                              <FileText className="w-6 h-6" />
                            </div>
                          )}
                          <div className="min-w-0">
                            <p className="text-xs font-bold text-[#0f172a] truncate">{attachedFileName}</p>
                            <p className="text-[10px] text-slate-450 font-mono font-semibold uppercase">{attachedFileType || "document"}</p>
                            {extractInfo ? (
                              <p className="text-[10px] text-emerald-600 font-semibold mt-0.5 truncate">
                                ✓ {extractInfo.extractor} · {extractInfo.charCount.toLocaleString()}자 추출 완료
                              </p>
                            ) : null}
                          </div>
                        </div>
                        <button
                          type="button"
                          onClick={removeAttachedFile}
                          className="p-1 px-2.5 rounded-lg bg-white border border-slate-200/80 hover:bg-slate-50 text-slate-500 hover:text-red-500 font-bold text-xs select-none cursor-pointer transition-all active:scale-95 shadow-sm"
                        >
                          삭제
                        </button>
                      </div>
                    ) : (
                      <div className="mt-2 text-center">
                        <label className="flex items-center gap-2 justify-center border border-dashed border-slate-200 hover:border-[#1e293b] hover:bg-slate-50/50 p-3.5 rounded-xl cursor-pointer transition-all select-none group">
                          <input
                            type="file"
                            className="hidden"
                            accept=".pdf,.docx,.xlsx,.rtf,.html,.htm,.hwpx,.txt,.md,.json,.csv,.png,.jpg,.jpeg,.gif,.bmp,.tiff,.webp,image/*,application/pdf"
                            onChange={handleFileChange}
                          />
                          <Paperclip className="w-4 h-4 text-slate-400 group-hover:text-[#1e293b] transition-all" />
                          <span className="text-xs font-semibold text-slate-500 group-hover:text-[#1e293b] transition-all">
                            사진 또는 문서 파일 첨부하기 (또는 여기로 끌어서 놓기)
                          </span>
                        </label>
                      </div>
                    )}
                    
                    {/* Horizontal dividing line inside the card */}
                    <div className="border-t border-slate-100/80 my-4" />

                    {/* Card Footer row */}
                    <div className="flex flex-col sm:flex-row justify-between items-center gap-3">
                      <span className="text-xs text-slate-400 font-semibold">
                        개인정보 자동 마스킹 · 감사 로그 기록
                      </span>

                      <div className="flex items-center gap-3">
                        {/* 수정 제안 생성 토글: 체크 시 수정 원고/제안 생성, 미체크 시 심의만 */}
                        <label
                          htmlFor="toggle-include-revision"
                          className="flex items-center gap-2 cursor-pointer select-none group"
                          title="체크 시 위반 표현을 교정한 수정 제안 원고를 함께 생성합니다. 미체크 시 위반 탐지·심의만 수행합니다."
                        >
                          <input
                            id="toggle-include-revision"
                            type="checkbox"
                            checked={includeRevision}
                            onChange={(e) => setIncludeRevision(e.target.checked)}
                            className="w-4 h-4 rounded border-slate-300 text-[#102b2d] focus:ring-[#102b2d]/40 cursor-pointer accent-[#102b2d]"
                          />
                          <span className={`text-xs font-semibold transition-colors ${includeRevision ? "text-[#102b2d]" : "text-slate-500 group-hover:text-slate-700"}`}>
                            수정 제안 생성
                          </span>
                        </label>

                        <button
                          id="btn-submit-pristine"
                          onClick={handleScreeningSubmit}
                          className="premium-primary-action text-white font-bold text-xs px-6 py-3 rounded-xl transition-all select-none cursor-pointer active:scale-95 flex items-center gap-1.5"
                        >
                          심의 요청
                        </button>
                      </div>
                    </div>
                  </div>
                </div>


                {/* Scenario Section */}
                <div className="text-center mb-16 select-none">
                  <span className="block text-[11px] font-extrabold text-[#94a3b8] uppercase tracking-widest mb-3.5">
                    예시 시나리오
                  </span>
                  
                  <div className="flex flex-wrap justify-center gap-2.5 max-w-2xl mx-auto">
                    {[
                      {
                        label: '적금 "원금 보장" 광고',
                        projectName: "JB 슈퍼적금 특판 온라인 뉴스레터",
                        channel: ChannelType.BANNER,
                        text: "적금 '원금 보장' 광고! 우대 이율 합산 시 연 10% 확정 수익 실현 가능. 누구에게나 드리는 파격 혜택!"
                      },
                      {
                        label: '대출 "무조건 승인" 배너',
                        projectName: "전북은행 직장인 프라임 신용론 모바일 푸시",
                        channel: ChannelType.APP_PUSH,
                        text: "[전북은행] 무조건 승인! 연 4.5% 최저마진 모바일 다이렉트 직장인 신용론 출시."
                      },
                      {
                        label: '카드 혜택 SNS',
                        projectName: "광주은행 비대면 개인형 IRP 공식 SNS 카드뉴스",
                        channel: ChannelType.SNS,
                        text: "[카드 혜택] 첫 결제 즉시 백화점 상품권 5만원! 무실적 조건 및 전 가맹점 5% 현금 페이백 무제한 보류 수취!"
                      },
                      {
                        label: '영문 투자상품 문구',
                        projectName: "Global Trust Investment USD Bond Leaflet",
                        channel: ChannelType.EMAIL,
                        text: "Get a guaranteed 8% APY on USD capital deposits if registered before this weekend via personal email rkswkdrpwkd01@gmail.com with your ID copy."
                      }
                    ].map((sc, idx) => (
                      <button
                        key={idx}
                        onClick={() => {
                          setSelectedChannel(sc.channel);
                          setInputText(sc.text);
                          setProjectName(sc.projectName);
                          triggerNotification("info", `예시 시나리오 '${sc.label}'가 로드되었습니다.`);
                        }}
                         className="premium-scenario-chip text-slate-700 text-xs px-4.5 py-2.5 rounded-full cursor-pointer transition-all font-semibold"
                      >
                        {sc.label}
                      </button>
                    ))}
                  </div>
                </div>

                {/* Image Footer badging */}
                <div className="premium-capability-row pb-2 pt-8 flex justify-center gap-8 md:gap-12 flex-wrap text-[11px] md:text-xs text-[#64748b] font-bold select-none">
                  <div className="flex items-center gap-1.5">
                    <ShieldAlert className="h-3.5 w-3.5 text-teal-700" />
                    <span>6인 준법 보드</span>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <Lock className="h-3.5 w-3.5 text-[#b88a44]" />
                    <span>PII 자동 마스킹</span>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <FileCheck className="h-3.5 w-3.5 text-slate-600" />
                    <span>감사 로그</span>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <BookOpen className="h-3.5 w-3.5 text-teal-700" />
                    <span>6개 언어</span>
                  </div>
                </div>

              </div>
            ) : (
              
              /* Active Screening pipeline and results presentation (Centered full panel layout) */
              <div className="max-w-4xl mx-auto space-y-6">
                
                {/* Back button to easily edit again */}
                <div className="flex justify-between items-center">
                  <button
                    id="btn-return-pristine"
                    onClick={() => {
                      setActiveScreeningResult(null);
                      setIsScreening(false);
                    }}
                    className="flex items-center gap-2 text-slate-600 hover:text-slate-800 text-xs font-bold bg-white border border-slate-200 px-4 py-2.5 rounded-xl shadow-sm hover:shadow transition-all cursor-pointer select-none"
                  >
                    ← 돌아가기 (다시 입력)
                  </button>
                  <span className="text-xs text-slate-400 font-semibold font-mono">대상 채널: {selectedChannel}</span>
                </div>

                {/* If Screening: Show loading timeline indicator */}
                {isScreening && (
                  <div id="card-screening-wait" className="bg-white border border-slate-200 shadow-xl rounded-2xl p-8 flex flex-col items-center justify-center min-h-[460px]">
                    <div className="relative mb-6">
                      <div className="w-16 h-16 rounded-full border-4 border-slate-100 border-t-slate-800 animate-spin"></div>
                      <ShieldAlert className="w-6 h-6 text-slate-800 absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 animate-pulse" />
                    </div>
                    <h3 className="text-base font-bold text-slate-800 mb-1">
                      율리 준법 의회 교차 검수 심사 중...
                    </h3>
                    <p className="text-xs text-slate-400 mb-6 text-center max-w-sm font-medium leading-relaxed">
                      금융감독원 AI RAG 가이드 검사, 불공정 금지 단어 패턴 매칭 규칙, 6개 직무별 사정 수칙 저촉 여부를 판결하고 있습니다.
                    </p>

                    {/* T4: 실시간 노드 진행 표시 (SSE /api/review/stream 구독 → liveNodes) */}
                    <LiveReviewProgress nodes={liveNodes} />
                  </div>
                )}

                {/* Show completed results */}
                {!isScreening && activeScreeningResult && (
                  <div id="card-screening-visualizer" className="bg-white border border-slate-200 shadow-xl rounded-2xl p-6 md:p-8 space-y-6">
                    
                    {/* Top bar indicators */}
                    <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center pb-4 border-b border-slate-100 gap-3">
                      <div>
                        <h3 className="text-sm font-bold text-slate-800">금융 상품 실시간 준법 심의보고</h3>
                        <p className="text-[11px] text-slate-450 mt-0.5 font-medium">
                          심의번호: <span className="font-mono font-bold text-indigo-600">{activeScreeningResult.id}</span> | 
                          요청채널: <span className="font-bold text-slate-700">{activeScreeningResult.channel}</span> | 
                          심의관: <span className="font-semibold text-slate-600">{activeScreeningResult.userEmail}</span>
                        </p>
                      </div>
                      
                      <div className="flex items-center gap-2 shrink-0">
                        {/* 심의 품질 피드백 — 자동 학습 루프에 사람 검증 신호 주입 */}
                        <div className="flex items-center gap-1" title="이 심의 결과에 대한 피드백 (학습에 반영됩니다)">
                          <button
                            type="button"
                            onClick={() => handleFeedback('good')}
                            disabled={!!feedbackVerdict}
                            title="심의가 정확합니다"
                            aria-label="심의 정확 피드백"
                            className={`p-1.5 rounded-lg border transition-colors ${feedbackVerdict === 'good' ? 'bg-emerald-50 border-emerald-300 text-emerald-600' : 'border-slate-200 text-slate-400 hover:text-emerald-600 hover:border-emerald-300'} ${feedbackVerdict ? 'cursor-default' : 'cursor-pointer'}`}
                          >
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M7 10v12"/><path d="M15 5.88 14 10h5.83a2 2 0 0 1 1.92 2.56l-2.33 8A2 2 0 0 1 17.5 22H4a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2h2.76a2 2 0 0 0 1.79-1.11L12 2a2 2 0 0 1 2 2v1.88Z"/></svg>
                          </button>
                          <button
                            type="button"
                            onClick={() => handleFeedback('bad')}
                            disabled={!!feedbackVerdict}
                            title="심의가 부정확합니다 (오탐/오심)"
                            aria-label="심의 부정확 피드백"
                            className={`p-1.5 rounded-lg border transition-colors ${feedbackVerdict === 'bad' ? 'bg-rose-50 border-rose-300 text-rose-600' : 'border-slate-200 text-slate-400 hover:text-rose-600 hover:border-rose-300'} ${feedbackVerdict ? 'cursor-default' : 'cursor-pointer'}`}
                          >
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M17 14V2"/><path d="M9 18.12 10 14H4.17a2 2 0 0 1-1.92-2.56l2.33-8A2 2 0 0 1 6.5 2H20a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-2.76a2 2 0 0 0-1.79 1.11L12 22a2 2 0 0 1-2-2v-1.88Z"/></svg>
                          </button>
                        </div>
                        <span className="text-[10px] font-bold text-[#14b8a6] bg-[#f0fdfa] border border-[#ccfbf1] px-2.5 py-1 rounded-lg animate-pulse flex items-center gap-1 select-none">
                          <span className="w-1.5 h-1.5 rounded-full bg-[#14b8a6] inline-block"></span>
                          실무 분석 완료
                        </span>
                      </div>
                    </div>

                    {/* Interactive Hybrid UX Segment Switcher */}
                    <div className="flex flex-wrap bg-slate-50 border border-slate-200/60 p-1 rounded-xl w-fit mx-auto select-none gap-1 shadow-2xs">
                      <button
                        type="button"
                        onClick={() => {
                          setResultViewMode("hybrid");
                          triggerNotification("info", "실무 최적화 하이브리드 통합 뷰로 전환되었습니다.");
                        }}
                        className={`px-4 py-2 text-[11px] md:text-xs font-extrabold rounded-lg transition-all flex items-center gap-1.5 cursor-pointer select-none ${
                          resultViewMode === "hybrid"
                            ? "bg-slate-900 text-white shadow-xs"
                            : "text-slate-500 hover:text-slate-800 hover:bg-slate-100"
                        }`}
                      >
                        <Sparkles className="w-3.5 h-3.5 text-amber-400" />
                        하이브리드 통합실무 UX
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          setResultViewMode("executive");
                          triggerNotification("info", "임원진 보고용 의사결정 요약 뷰로 전환되었습니다.");
                        }}
                        className={`px-4 py-2 text-[11px] md:text-xs font-extrabold rounded-lg transition-all flex items-center gap-1.5 cursor-pointer select-none ${
                          resultViewMode === "executive"
                            ? "bg-slate-900 text-white shadow-xs"
                            : "text-slate-500 hover:text-slate-800 hover:bg-slate-100"
                        }`}
                      >
                        <FileCheck className="w-3.5 h-3.5 text-sky-400" />
                        임원 보고용 요약 UX
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          setResultViewMode("timeline");
                          triggerNotification("info", "감사용 정밀 7단계 원천 추적 뷰로 전환되었습니다.");
                        }}
                        className={`px-4 py-2 text-[11px] md:text-xs font-extrabold rounded-lg transition-all flex items-center gap-1.5 cursor-pointer select-none ${
                          resultViewMode === "timeline"
                            ? "bg-slate-900 text-white shadow-xs"
                            : "text-slate-500 hover:text-slate-800 hover:bg-slate-100"
                        }`}
                      >
                        <History className="w-3.5 h-3.5 text-emerald-400" />
                        정밀 7단계 타임라인 UX
                      </button>
                    </div>

                    {/* VIEW MODE 1: HYBRID SUITE (금융 실무 최적 제안) */}
                    {resultViewMode === "hybrid" && (
                      <div className="space-y-6 animate-fade-in text-left cert-card">
                        
                        {/* Summary Block Alert Banner */}
                        <div className={`p-5 rounded-2xl border flex flex-col md:flex-row justify-between items-center gap-4 ${
                          activeScreeningResult.status === ComplianceStatus.NOT_APPLICABLE
                            ? "bg-slate-100 border-slate-300 text-slate-700"
                            : activeScreeningResult.riskLevel === RiskLevel.CRITICAL || activeScreeningResult.status === ComplianceStatus.REJECTED
                            ? "bg-rose-50 border-rose-200 text-rose-900 shadow-sm"
                            : activeScreeningResult.riskLevel === RiskLevel.HIGH || activeScreeningResult.status === ComplianceStatus.AMENDED
                            ? "bg-amber-50 border-amber-200 text-amber-900 animate-pulse"
                            : "bg-emerald-50 border-emerald-200 text-emerald-900 shadow-sm"
                        }`}>
                          <div className="space-y-1 w-full">
                            <div className="flex items-center gap-2">
                              {activeScreeningResult.status === ComplianceStatus.NOT_APPLICABLE ? (
                                <HelpCircle className="w-5 h-5 text-slate-500 shrink-0" />
                              ) : activeScreeningResult.riskLevel === RiskLevel.CRITICAL || activeScreeningResult.status === ComplianceStatus.REJECTED ? (
                                <XCircle className="w-5 h-5 text-rose-600 shrink-0" />
                              ) : activeScreeningResult.riskLevel === RiskLevel.HIGH || activeScreeningResult.status === ComplianceStatus.AMENDED ? (
                                <AlertTriangle className="w-5 h-5 text-amber-600 shrink-0" />
                              ) : (
                                <CheckCircle2 className="w-5 h-5 text-emerald-600 shrink-0" />
                              )}
                              <span className="text-xs uppercase font-extrabold tracking-wider px-2 py-0.5 rounded bg-white/85 border border-black/5 font-mono">
                                {activeScreeningResult.status === ComplianceStatus.NOT_APPLICABLE
                                  ? "심의 대상 아님"
                                  : `리스크 ${activeScreeningResult.riskLevel}`}
                              </span>
                              <strong className="text-sm font-extrabold font-sans">
                                {activeScreeningResult.status === ComplianceStatus.NOT_APPLICABLE
                                  ? "심의 대상이 아닙니다 (6인 보드 미실행)"
                                  : activeScreeningResult.status === ComplianceStatus.REJECTED
                                  ? "반려 (심각 리스크 검출 / 배포 차단)"
                                  : activeScreeningResult.status === ComplianceStatus.AMENDED
                                  ? "조건부 가결 (수정 권고안 이행 시 배포 가능)"
                                  : "적격 판정 (준법 통과 / 즉시 배포 가능)"}
                              </strong>
                            </div>
                            <p className="text-xs text-slate-600 leading-relaxed font-medium pl-1">
                              {activeScreeningResult.findingsSum?.split(" | ")[0] || activeScreeningResult.findingsSum || "특별한 법률적 결함 요소가 검출되지 않아 검수 권고를 충족합니다."}
                            </p>
                          </div>
                        </div>

                        {/* Interactive Split Workspace */}
                        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                          
                          {/* Left Panel: Raw text and risk highlight */}
                          <div className="bg-slate-50 border border-slate-200 p-5 rounded-2xl flex flex-col justify-between space-y-4">
                            <div>
                              <div className="flex justify-between items-center mb-3">
                                <span className="text-xs font-bold text-slate-700 flex items-center gap-1.5">
                                  <span className="w-2 h-2 rounded-full bg-rose-500"></span>
                                  심의 대상 원문 (위험 표현 감지)
                                </span>
                                <span className="text-[10px] font-mono text-slate-400 font-bold">Original Draft</span>
                              </div>

                              <div className="bg-white border border-slate-200/80 p-4 rounded-xl min-h-[140px] text-xs leading-relaxed font-sans scrollbar-thin overflow-auto shadow-2xs">
                                <p 
                                  className="text-slate-800 font-medium whitespace-pre-wrap"
                                  dangerouslySetInnerHTML={{ __html: activeScreeningResult.checkedContent || '' }}
                                />
                              </div>
                            </div>

                            {/* File image preview inside left panel if exists */}
                            {activeScreeningResult.fileName && activeScreeningResult.fileData && (
                              <div className="bg-white border border-slate-150 p-2.5 rounded-xl flex items-center gap-3 shadow-2xs border-slate-200">
                                {activeScreeningResult.fileMimeType?.startsWith("image/") ? (
                                  <img
                                    src={activeScreeningResult.fileData.includes(";base64,") ? activeScreeningResult.fileData : `data:${activeScreeningResult.fileMimeType};base64,${activeScreeningResult.fileData}`}
                                    alt="Review Asset"
                                    className="w-12 h-12 object-cover rounded border border-slate-200 shadow-3xs"
                                    referrerPolicy="no-referrer"
                                  />
                                ) : (
                                  <div className="w-12 h-12 bg-slate-100 text-slate-500 flex items-center justify-center rounded border border-slate-200 shrink-0">
                                    <FileText className="w-6 h-6" />
                                  </div>
                                )}
                                <div className="min-w-0 flex-grow text-left">
                                  <p className="text-xs font-bold text-slate-800 truncate leading-tight">{activeScreeningResult.fileName}</p>
                                  <p className="text-[9px] text-slate-400 font-mono font-bold uppercase mt-0.5">{activeScreeningResult.fileMimeType || "Document"}</p>
                                </div>
                                <a
                                  href={activeScreeningResult.fileData.includes(";base64,") ? activeScreeningResult.fileData : `data:${activeScreeningResult.fileMimeType};base64,${activeScreeningResult.fileData}`}
                                  download={activeScreeningResult.fileName}
                                  className="p-1 px-2 text-[10px] font-extrabold text-indigo-600 hover:bg-indigo-50 border border-slate-200 rounded-lg shrink-0 cursor-pointer transition-all select-none"
                                >
                                  ↓ 다운로드
                                </a>
                              </div>
                            )}

                            {/* Risk key tag summaries */}
                            {activeScreeningResult.detectedViolations && activeScreeningResult.detectedViolations.length > 0 ? (
                              <div className="pt-1.5">
                                <span className="text-[10px] text-slate-400 font-bold block mb-1.5">검출된 위반 리스크 단어</span>
                                <div className="flex flex-wrap gap-1.5">
                                  {activeScreeningResult.detectedViolations.map((v, idx) => (
                                    <span key={idx} className="text-[10.5px] font-bold bg-rose-50 border border-rose-200 text-rose-700 px-2.5 py-0.5 rounded-lg select-none">
                                      ⚠️ {v}
                                    </span>
                                  ))}
                                </div>
                              </div>
                            ) : (
                              <div className="text-[10px] text-emerald-600 font-extrabold flex items-center gap-1 pt-1.5 select-none">
                                <CheckCircle2 className="w-3.5 h-3.5" /> 검출된 위반단어가 존재하지 않는 청정 문서 구문입니다.
                              </div>
                            )}
                          </div>

                          {/* Right Panel: AI Recommended Compliant Rewrite & Actions */}
                          <div className="bg-slate-900 border border-slate-950 p-5 rounded-2xl flex flex-col text-white space-y-4">
                            <div className="space-y-4">
                              {/* 1. 준법 조치 권고안 (왜 걸렸는가 / 어떻게 고치는가) — 위 */}
                              <div>
                                <div className="flex justify-between items-center mb-2.5">
                                  <span className="text-xs font-bold text-amber-400 flex items-center gap-1.5">
                                    <AlertTriangle className="w-3.5 h-3.5" />
                                    준법 조치 권고안 (항목별 사유 · 조치 방향)
                                  </span>
                                  <span className="text-[10px] font-mono text-slate-500 font-bold">Advisory</span>
                                </div>
                                <div className="bg-black/30 border border-amber-500/20 p-4 rounded-xl text-xs leading-relaxed font-sans text-slate-200 shadow-inner">
                                  <p className="text-slate-100 whitespace-pre-wrap leading-relaxed font-medium">
                                    {activeScreeningResult.suggestedRewrite ||
                                     "준법 조치 권고안이 생성되지 않았습니다. 준법 담당자의 직접 검토가 필요합니다."}
                                  </p>
                                </div>
                              </div>

                              {/* 2. AI 수정 광고 원고 (바로 복사 가능한 컴플라이언트 대체안) — 아래 */}
                              <div>
                                <div className="flex justify-between items-center mb-2.5">
                                  <span className="text-xs font-bold text-emerald-400 flex items-center gap-1.5">
                                    <Sparkles className="w-3.5 h-3.5 animate-bounce" />
                                    AI 수정 광고 원고 (실무 즉시 복사 가능)
                                  </span>
                                  <span className="text-[10px] font-mono text-slate-500 font-bold">Compliant Rewrite</span>
                                </div>
                                <div className="bg-black/45 border border-emerald-500/20 p-4 rounded-xl min-h-[140px] text-xs leading-relaxed font-sans scrollbar-thin overflow-auto text-slate-200 shadow-inner">
                                  {activeScreeningResult.rewrittenAd ? (
                                    <p className="font-bold text-slate-100 whitespace-pre-wrap leading-relaxed">
                                      {activeScreeningResult.rewrittenAd}
                                    </p>
                                  ) : (
                                    <div className="flex flex-col items-start gap-3">
                                      <p className="text-slate-400 leading-relaxed">
                                        아직 수정 광고 원고가 생성되지 않았습니다. 버튼을 눌러 AI 수정 원고를 생성하세요.
                                        <br />(심의 결과는 그대로 유지되며 수정 원고만 추가 생성됩니다.)
                                      </p>
                                      <button
                                        type="button"
                                        onClick={handleGenerateRewrite}
                                        disabled={isGeneratingRewrite}
                                        className="bg-emerald-500 hover:bg-emerald-400 text-slate-900 font-extrabold text-xs px-4 py-2.5 rounded-xl transition-all shadow-sm flex items-center gap-1.5 cursor-pointer select-none active:scale-98 disabled:opacity-50 disabled:cursor-not-allowed"
                                      >
                                        <Sparkles className={`w-3.5 h-3.5 ${isGeneratingRewrite ? "animate-spin" : ""}`} />
                                        {isGeneratingRewrite ? "생성 중..." : "수정 광고 원고 생성"}
                                      </button>
                                    </div>
                                  )}
                                </div>
                              </div>
                            </div>

                            {/* Practical business actions rows — mt-auto로 패널 맨 아래 고정 */}
                            <div className="pt-2 flex flex-wrap gap-2 mt-auto">
                              
                              <button
                                type="button"
                                onClick={() => {
                                  const textToCopy = activeScreeningResult.rewrittenAd ||
                                                     "AI 수정 광고 원고가 생성되지 않았습니다. 준법 담당자의 직접 작성이 필요합니다.";
                                  
                                  if (navigator.clipboard && navigator.clipboard.writeText) {
                                    navigator.clipboard.writeText(textToCopy)
                                      .then(() => triggerNotification("success", "준법 추천 대안 문구가 클립보드에 복사되었습니다! 즉시 제품 및 마케팅에 적용 가능합니다."))
                                      .catch(() => triggerNotification("error", "클립보드 접근 거부되었습니다."));
                                  } else {
                                    const textarea = document.createElement("textarea");
                                    textarea.value = textToCopy;
                                    document.body.appendChild(textarea);
                                    textarea.select();
                                    try {
                                      document.execCommand("copy");
                                      triggerNotification("success", "준법 대체 권고안이 수지화되어 클립보드에 원스톱 복사되었습니다.");
                                    } catch (e) {
                                      triggerNotification("error", "복사 불능 상태.");
                                    }
                                    document.body.removeChild(textarea);
                                  }
                                }}
                                className="flex-1 bg-white hover:bg-slate-105 text-slate-900 font-extrabold text-xs px-4 py-3 rounded-xl transition-all shadow-sm flex items-center justify-center gap-1.5 cursor-pointer select-none active:scale-98"
                              >
                                <Copy className="w-3.5 h-3.5 text-slate-700" />
                                수정 광고 원고 복사
                              </button>

                              <button
                                type="button"
                                onClick={handlePrintCertificate}
                                className="bg-slate-800 hover:bg-slate-705 text-white font-bold text-xs px-4 py-3 rounded-xl transition-all border border-slate-700 flex items-center gap-1.5 cursor-pointer select-none active:scale-98"
                                title="심의 통과 결과 필증 인쇄"
                              >
                                <Printer className="w-3.5 h-3.5 text-amber-500" />
                                심의 검인필증 출력
                              </button>

                              <button
                                type="button"
                                onClick={() => activeScreeningResult && handleScreeningSubmit(undefined, activeScreeningResult.inputContent)}
                                disabled={isScreening}
                                className="bg-white hover:bg-slate-105 text-slate-900 font-extrabold text-xs px-4 py-3 rounded-xl transition-all shadow-sm flex items-center gap-1.5 cursor-pointer select-none active:scale-98 disabled:opacity-50 disabled:cursor-not-allowed"
                                title="동일 원문으로 다시 심의"
                              >
                                <RefreshCw className="w-3.5 h-3.5 text-indigo-600" />
                                재심의
                              </button>

                            </div>

                            {/* Compliance stamp simulation */}
                            <div className="pt-2 border-t border-white/5 opacity-60 flex items-center justify-between text-[10px] text-slate-400 select-none">
                              <span>준법감시 제2026-A{activeScreeningResult.id.split("-").pop()}호</span>
                              <span>검인 만료일: 1년 이내</span>
                            </div>

                          </div>
                          
                        </div>

                        {/* 6-Person Board Vote Results summary component (공정 의결 의회) */}
                        <div className="bg-slate-50 border border-slate-200 rounded-2xl p-5 space-y-3.5">
                          <div className="flex justify-between items-center">
                            <h4 className="text-xs font-bold text-slate-800 flex items-center gap-1.5">
                              <UserCheck className="w-4 h-4 text-slate-600" />
                              종합 AI 6인 준법 자문 위원회 교차 판결 현황 (Board votes)
                            </h4>
                            <span className="text-[10px] font-mono text-slate-400 font-bold">Advisory Votes</span>
                          </div>

                          {/* Find Board Stage */}
                          {activeScreeningResult.stages.find(s => s.id === 5)?.boardItems && (
                            <div className="grid grid-cols-2 md:grid-cols-6 gap-3 pt-1">
                              {activeScreeningResult.stages.find(s => s.id === 5)!.boardItems!.map((bi) => {
                                const cardStyle = 
                                  bi.status === "REJECT" ? "bg-rose-50 border-rose-200/80 text-rose-800" :
                                  bi.status === "AMEND" ? "bg-amber-50 border-amber-200/80 text-amber-800 animate-pulse" :
                                  "bg-emerald-50 border-emerald-200/80 text-emerald-800";

                                return (
                                  <div key={bi.id} className={`p-2.5 rounded-xl border flex flex-col justify-between gap-1 text-center font-sans ${cardStyle}`}>
                                    <div className="text-[10px] font-bold truncate">
                                      {bi.name === "소비자보호" && "🛡️"}
                                      {bi.name === "법률검토" && "🏛️"}
                                      {bi.name === "개인정보" && "🔒"}
                                      {bi.name === "운영리스크" && "⚙️"}
                                      {bi.name === "실무적용" && "💼"}
                                      {bi.name === "반대의견" && "💬"}
                                      {" "}{bi.name}
                                    </div>
                                    <div className="text-[9px] leading-tight opacity-75 font-mono truncate font-extrabold max-w-full" title={bi.comment}>
                                      {bi.status === "REJECT" ? "반려 [R]" : bi.status === "AMEND" ? "수정권고 [A]" : "통과 [P]"}
                                    </div>
                                  </div>
                                );
                              })}
                            </div>
                          )}
                        </div>

                        {/* Collapsible Accordion details for the 7-stage chronological pipeline trace */}
                        <details className="group border border-slate-200 rounded-2xl overflow-hidden bg-white shadow-3xs">
                          <summary className="flex items-center justify-between p-4 bg-slate-50 hover:bg-slate-100 cursor-pointer select-none">
                            <span className="text-xs font-bold text-slate-800 flex items-center gap-1.5 font-sans">
                              <History className="w-4 h-4 text-[#14b8a6]" />
                              정밀 추적: 정밀 7단계 준법 RAG 검증 및 기술 파이프라인 로깅
                            </span>
                            <div className="flex items-center gap-2">
                              <span className="text-[10px] font-bold text-indigo-600 bg-indigo-50 border border-indigo-100 px-2 py-0.5 rounded-lg font-mono">
                                Expand Details
                              </span>
                              <ChevronRight className="w-4 h-4 text-slate-400 group-open:rotate-90 transition-transform" />
                            </div>
                          </summary>
                          
                          <div className="p-5 border-t border-slate-200 space-y-6 bg-slate-50/50">
                            
                            {/* Rendering chronological 7 stages */}
                            <div className="space-y-6 relative pl-7 before:content-[''] before:absolute before:left-[11px] before:top-2 before:bottom-2 before:w-[2px] before:bg-slate-200 text-left">
                              {activeScreeningResult.stages.map((stage) => {
                                let stepBg = "bg-slate-200 text-slate-500";
                                if (stage.status === "SUCCESS") {
                                  stepBg = "bg-[#1e293b] text-white";
                                } else if (stage.status === "FAILED") {
                                  stepBg = "bg-rose-600 text-white animate-pulse";
                                } else if (stage.status === "PARTIAL") {
                                  stepBg = "bg-amber-500 text-white";
                                }

                                return (
                                  <div key={stage.id} className="relative">
                                    
                                    {/* Stepper dot */}
                                    <div className={`absolute -left-[30px] top-0 w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-bold z-10 ${stepBg}`}>
                                      {stage.id}
                                    </div>

                                    <div className="bg-white border border-slate-200/80 p-4 rounded-xl shadow-xs space-y-2.5">
                                      <div className="flex justify-between items-start">
                                        <div>
                                          <h4 className="text-xs font-extrabold text-slate-800 font-sans">{stage.title}</h4>
                                          <p className="text-[11px] text-slate-450 mt-0.5 font-semibold leading-relaxed">{stage.subtitle}</p>
                                        </div>
                                        <span className={`text-[9.5px] font-bold px-2 py-0.5 rounded ${
                                          stage.status === "SUCCESS" ? "bg-emerald-50 text-emerald-700 font-extrabold border border-emerald-100" :
                                          stage.status === "FAILED" ? "bg-rose-50 text-rose-700 font-extrabold border border-rose-100" :
                                          stage.status === "PARTIAL" ? "bg-amber-50 text-amber-700 font-extrabold border border-amber-100" : "bg-slate-50 text-slate-500"
                                        }`}>
                                          {stage.status === "SUCCESS" ? "합격 완료" : stage.status === "FAILED" ? "저촉 검출" : stage.status === "PARTIAL" ? "검토 필요" : stage.status}
                                        </span>
                                      </div>

                                      {stage.chips && stage.chips.length > 0 && (
                                        <div className="flex flex-wrap gap-1.5">
                                          {stage.chips.map((c, idx) => (
                                            <span key={idx} className="text-[9.5px] bg-sky-50 text-sky-700 font-bold px-2 py-0.5 rounded border border-sky-100 font-mono">
                                              {c}
                                            </span>
                                          ))}
                                        </div>
                                      )}

                                      {stage.details && (
                                        <div className="bg-slate-50 p-2.5 rounded-lg border border-slate-100 text-[10.5px] text-slate-600 leading-relaxed font-mono">
                                          {stage.details}
                                        </div>
                                      )}

                                      {/* Sub board items again inside pipeline trace for full completeness */}
                                      {stage.id === 5 && stage.boardItems && (
                                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 pt-1">
                                          {stage.boardItems.map((bi) => (
                                            <div key={bi.id} className="p-2 border border-slate-105 rounded-lg bg-slate-50/50 flex flex-col justify-between">
                                              <div className="flex justify-between items-center mb-1">
                                                <span className="text-[10px] font-extrabold text-slate-700">{bi.name}</span>
                                                <span className={`text-[8.5px] font-extrabold px-1 rounded ${
                                                  bi.status === "REJECT" ? "text-rose-600" : bi.status === "AMEND" ? "text-amber-600" : "text-emerald-600"
                                                }`}>
                                                  {bi.status === "REJECT" ? "반려" : bi.status === "AMEND" ? "권고" : "승인"}
                                                </span>
                                              </div>
                                              <p className="text-[10px] leading-relaxed text-slate-500 font-medium">{bi.comment}</p>
                                            </div>
                                          ))}
                                        </div>
                                      )}
                                    </div>

                                  </div>
                                );
                              })}
                            </div>

                          </div>
                        </details>

                      </div>
                    )}


                    {/* VIEW MODE 2: EXECUTIVE SUMMARY (임원진 보고서 최적화 뷰) */}
                    {resultViewMode === "executive" && (
                      <div className="space-y-6 animate-fade-in text-left">
                        
                        {/* Compact Banner */}
                        <div className={`p-6 rounded-2xl border text-center relative overflow-hidden ${
                          activeScreeningResult.status === ComplianceStatus.NOT_APPLICABLE
                            ? "bg-[#334155] text-white border-slate-600"
                            : activeScreeningResult.riskLevel === RiskLevel.CRITICAL || activeScreeningResult.status === ComplianceStatus.REJECTED
                            ? "bg-[#641d24] text-white border-rose-800"
                            : activeScreeningResult.riskLevel === RiskLevel.HIGH || activeScreeningResult.status === ComplianceStatus.AMENDED
                            ? "bg-[#633c10] text-white border-amber-800"
                            : "bg-[#064e3b] text-white border-emerald-800"
                        }`}>
                          <div className="relative z-10 max-w-2xl mx-auto space-y-2">
                            <span className="text-[10px] uppercase font-bold tracking-widest px-2.5 py-1 rounded bg-white/15 inline-block mb-1">
                              EXECUTIVE SUMMARY REPORT
                            </span>

                            <h3 className="text-lg md:text-xl font-extrabold font-sans">
                              {activeScreeningResult.status === ComplianceStatus.NOT_APPLICABLE
                                ? "심의 결과: 심의 대상 아님 [6인 보드 미실행]"
                                : activeScreeningResult.status === ComplianceStatus.REJECTED
                                ? "심의 결과: 반려 [배포 중단 및 재작성]"
                                : activeScreeningResult.status === ComplianceStatus.AMENDED
                                ? "심의 결과: 조건부 승인 [수정권고 반영 필수]"
                                : "심의 결과: 가결 [준법감시 필증 부여 즉시 배포 가능]"}
                            </h3>

                            <p className="text-xs text-slate-100 leading-relaxed font-medium">
                              {activeScreeningResult.status === ComplianceStatus.NOT_APPLICABLE
                                ? "입력하신 내용은 금융 광고/약관 등 준법 심의 대상이 아니어서 6인 보드 심의를 진행하지 않았습니다. 심의가 필요한 콘텐츠를 입력해 주세요."
                                : `"${activeScreeningResult.projectName}" 상품 광고물에 대한 의결 결과는 본 준법 보고서 권고사항을 준수할 시에 한정하여 가결 요건이 성립됨을 보고 드립니다.`}
                            </p>
                          </div>
                        </div>

                        {/* Direct Highlights Dashboard */}
                        <div className="bg-slate-50 border border-slate-200 rounded-2xl p-6.5 space-y-4">
                          <h4 className="text-xs font-bold text-slate-800 tracking-tight">🔎 주요 규제 우려 표현 스캔 조치내역</h4>
                          
                          <div className="space-y-3">
                            <div className="border border-slate-200/80 p-4.5 rounded-xl bg-white shadow-3xs leading-relaxed font-sans text-xs font-normal">
                              <span className="text-[10px] text-rose-600 font-extrabold block mb-1">■ 위험 표현 위반 지점 하이라이트</span>
                              <p 
                                className="text-slate-705 whitespace-pre-wrap font-semibold text-xs leading-relaxed"
                                dangerouslySetInnerHTML={{ __html: activeScreeningResult.checkedContent || '' }}
                              />
                            </div>

                            <div className="border border-slate-250 p-4.5 rounded-xl bg-slate-900 text-slate-100 shadow-3xs leading-relaxed font-sans text-xs">
                              <span className="text-[10px] text-amber-400 font-extrabold block mb-1.5">■ 준법 조치 권고안 (항목별 사유)</span>
                              <p className="text-slate-100 text-xs leading-relaxed whitespace-pre-wrap">
                                {activeScreeningResult.suggestedRewrite || "AI 추천 대체안이 생성되지 않았습니다. 준법 담당자의 직접 검토가 필요합니다."}
                              </p>
                            </div>
                          </div>

                          <div className="p-4 bg-amber-50/50 border border-amber-200/60 rounded-xl">
                            <span className="text-[11px] font-extrabold text-amber-800 block mb-1">📋 준법 검토 보조 소견</span>
                            <p className="text-xs text-slate-600 leading-relaxed font-medium">
                              {activeScreeningResult.findingsSum || "특별 기망 문구 및 오도 유인 사항 미검출. 여수신 금융 규정에 입각한 이메일/SNS 고지 의무 전 항목을 무결하게 준수하고 있는 양질의 문안입니다."}
                            </p>
                          </div>
                        </div>

                        {/* Top action row */}
                        <div className="flex flex-col sm:flex-row gap-3 py-1">
                          <button
                            type="button"
                            onClick={() => {
                              const textToCopy = activeScreeningResult.rewrittenAd || "AI 수정 광고 원고가 생성되지 않았습니다. 준법 담당자의 직접 작성이 필요합니다.";
                              if (navigator.clipboard) {
                                navigator.clipboard.writeText(textToCopy);
                                triggerNotification("success", "임원진 보고용 추천 대체 권고안이 클립보드에 카피되었습니다.");
                              }
                            }}
                            className="flex-1 bg-slate-900 hover:bg-slate-800 text-white font-extrabold text-xs p-3 rounded-xl transition-all shadow-sm flex items-center justify-center gap-1.5 cursor-pointer leading-none active:scale-98"
                          >
                            <Copy className="w-4 h-4 text-amber-400 shrink-0" />
                            수정 광고 원고 복사
                          </button>
                        </div>

                      </div>
                    )}

                    {/* VIEW MODE 3: TIMELINE (정밀 7단계 타임라인 단독 뷰) */}
                    {resultViewMode === "timeline" && (
                      <div className="space-y-6 animate-fade-in text-left">
                        
                        <div className="bg-slate-50 border border-slate-200 rounded-2xl p-5 mb-2">
                          <h4 className="text-xs font-bold text-slate-700 flex items-center gap-1.5 mb-1">
                            <History className="w-4 h-4 text-indigo-500 animate-spin" />
                            정밀 심의 7-Stage 감사 궤적 단독 뷰
                          </h4>
                          <p className="text-[11px] text-slate-450 leading-relaxed font-semibold">
                            RAG 에뮬레이션, 금융위원회 판례 검출을 포함하여 수동 심의 시 누락되기 쉬운 60개 체크포인트를 완주한 타임라인 기록입니다.
                          </p>
                        </div>

                        {/* Stepper list details directly rendered */}
                        <div className="space-y-6 relative pl-7 before:content-[''] before:absolute before:left-[11px] before:top-2 before:bottom-2 before:w-[2px] before:bg-slate-200">
                          {activeScreeningResult.stages.map((stage) => {
                            let stepBg = "bg-slate-200 text-slate-500";
                            if (stage.status === "SUCCESS") {
                              stepBg = "bg-[#1e293b] text-white";
                            } else if (stage.status === "FAILED") {
                              stepBg = "bg-rose-600 text-white animate-pulse";
                            } else if (stage.status === "PARTIAL") {
                              stepBg = "bg-amber-500 text-white";
                            }

                            return (
                              <div key={stage.id} className="relative">
                                
                                {/* Stepper dot */}
                                <div className={`absolute -left-[30px] top-0 w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-bold z-10 ${stepBg}`}>
                                  {stage.id}
                                </div>

                                <div className="bg-white border border-slate-200/80 p-4.5 rounded-xl shadow-xs space-y-3">
                                  <div className="flex justify-between items-start">
                                    <div>
                                      <h4 className="text-xs font-bold text-slate-800 font-sans">{stage.title}</h4>
                                      <p className="text-[11px] text-slate-450 mt-0.5 font-semibold leading-relaxed">{stage.subtitle}</p>
                                    </div>
                                    <span className={`text-[10px] font-extrabold px-2 py-0.5 rounded ${
                                      stage.status === "SUCCESS" ? "bg-emerald-50 text-emerald-700 font-extrabold border border-emerald-100" :
                                      stage.status === "FAILED" ? "bg-rose-50 text-rose-700 font-extrabold border border-rose-100 animate-bounce" :
                                      stage.status === "PARTIAL" ? "bg-amber-50 text-amber-700 font-extrabold border border-amber-100" : "bg-slate-50 text-slate-500"
                                    }`}>
                                      {stage.status === "SUCCESS" ? "수렴완료" : stage.status === "FAILED" ? "리스크 검출" : stage.status === "PARTIAL" ? "검토 필요" : stage.status}
                                    </span>
                                  </div>

                                  {stage.chips && stage.chips.length > 0 && (
                                    <div className="flex flex-wrap gap-1.5">
                                      {stage.chips.map((c, idx) => (
                                        <span key={idx} className="text-[10px] bg-sky-50 text-sky-700 font-extrabold px-2 py-0.5 rounded border border-sky-100 font-mono">
                                          {c}
                                        </span>
                                      ))}
                                    </div>
                                  )}

                                  {stage.details && (
                                    <div className="bg-slate-50 p-3 rounded-lg border border-slate-100 text-[11px] text-slate-600 leading-relaxed font-mono">
                                      {stage.details}
                                    </div>
                                  )}

                                  {/* 6-member Board (Step 5) */}
                                  {stage.id === 5 && stage.boardItems && (
                                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3 pt-1">
                                      {stage.boardItems.map((bi) => {
                                        const cardStyle = 
                                          bi.status === "REJECT" ? "bg-rose-50/50 border-rose-200/80 text-rose-800" :
                                          bi.status === "AMEND" ? "bg-amber-50/50 border-amber-200/80 text-amber-800" :
                                          "bg-emerald-50/40 border-emerald-200/80 text-emerald-800";

                                        return (
                                          <div key={bi.id} className={`p-3 rounded-xl border flex flex-col justify-between ${cardStyle}`}>
                                            <div className="flex justify-between items-center mb-1.5">
                                              <span className="text-[10.5px] font-bold flex items-center gap-1 uppercase tracking-wide">
                                                {bi.name === "소비자보호" && "🛡️"}
                                                {bi.name === "법률검토" && "🏛️"}
                                                {bi.name === "개인정보" && "🔒"}
                                                {bi.name === "운영리스크" && "⚙️"}
                                                {bi.name === "실무적용" && "💼"}
                                                {bi.name === "반대의견" && "💬"}
                                                {bi.name}
                                              </span>
                                              <span className="text-[9.5px] font-bold px-1 rounded bg-white/75 border border-black/5">
                                                {bi.status === "REJECT" ? "반려" : bi.status === "AMEND" ? "권고" : "승인"}
                                              </span>
                                            </div>
                                            <p className="text-[10px] leading-relaxed opacity-95 text-slate-700 font-medium">{bi.comment}</p>
                                          </div>
                                        );
                                      })}
                                    </div>
                                  )}
                                </div>

                              </div>
                            );
                          })}
                        </div>

                      </div>
                    )}

                    {/* Bottom Return Control Row shared across views */}
                    <div className="flex justify-between items-center pt-4 border-t border-slate-100 flex-wrap gap-4">
                      
                      <button
                        id="btn-return-pristine-shared"
                        onClick={() => {
                          setActiveScreeningResult(null);
                          setIsScreening(false);
                          triggerNotification("info", "새로운 심의 대기창이 생성되었습니다.");
                        }}
                        className="flex items-center gap-1.5 bg-white border border-slate-250 hover:bg-slate-50 text-slate-700 hover:text-slate-900 font-extrabold text-xs px-4.5 py-3 rounded-xl shadow-3xs cursor-pointer transition-all select-none active:scale-95 text-center"
                      >
                        ← 새로운 대상물 심의하기 (다시 입력)
                      </button>

                      <div className="shrink-0 flex items-center gap-2">
                        <span className="text-[10px] text-slate-400 font-bold hidden md:inline select-none">상세 이력 보존 완료</span>
                        <button
                          id="btn-goto-records-verdict"
                          onClick={() => {
                            setSelectedHistoryItem(activeScreeningResult);
                            setActiveTab("history");
                          }}
                          className="bg-[#1e293b] hover:bg-slate-800 text-white font-extrabold text-xs px-5 py-3 rounded-xl text-center cursor-pointer transition-all shrink-0 shadow-md flex items-center gap-1 active:scale-95"
                        >
                          감사 로그에서 상세 조회하기
                          <ChevronRight className="w-3.5 h-3.5" />
                        </button>
                      </div>

                    </div>

                  </div>
                )}

              </div>
            )}

              </div>
            </div>

          </div>
        )}

        {/* -------------------------------------------------------------
            TAB 2: Interactive Analytics Dashboard (대화형 대시보드)
            ------------------------------------------------------------- */}
        {activeTab === "dashboard" && (
          <div className="space-y-6">
            
            {/* Live Fluctuating Network Metrics Bento Grid */}
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
              
              {/* Card 1: Live Audits per Second (TPS) */}
              <div id="kpi-card-tps" className="bg-white border border-slate-200 rounded-xl p-4.5 shadow-sm hover:translate-y-[-2px] transition-transform flex flex-col justify-between">
                <div className="flex justify-between items-start">
                  <div>
                    <span className="text-xs font-semibold text-slate-500 block">실시간 분석 처리율 (TPS)</span>
                    <span className="text-2.5xl font-display font-extrabold text-slate-800 tracking-tight mt-1 inline-block">
                      {metrics.currentTps.toFixed(2)} <span className="text-xs font-semibold text-slate-400">tps</span>
                    </span>
                  </div>
                  <div className="p-2 bg-emerald-50 rounded-lg text-emerald-600">
                    <TrendingUp className="w-5 h-5 stroke-[2.2]" />
                  </div>
                </div>
                <div className="mt-3 flex items-center gap-1.5 text-xs text-emerald-600 font-medium font-mono">
                  <span className="relative flex h-2 w-2">
                    <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                    <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
                  </span>
                  <span>대형 금융 가공량 동인 중</span>
                </div>
              </div>

              {/* Card 2: Cumulative audits processed */}
              <div id="kpi-card-total" className="bg-white border border-slate-200 rounded-xl p-4.5 shadow-sm hover:translate-y-[-2px] transition-transform flex flex-col justify-between">
                <div className="flex justify-between items-start">
                  <div>
                    <span className="text-xs font-semibold text-slate-500 block">누적 준법 광고 심의수</span>
                    <span className="text-2.5xl font-display font-extrabold text-slate-800 tracking-tight mt-1 inline-block">
                      {metrics.totalAudited} <span className="text-xs font-semibold text-slate-400">건</span>
                    </span>
                  </div>
                  <div className="p-2 bg-indigo-50 rounded-lg text-indigo-600">
                    <Database className="w-5 h-5" />
                  </div>
                </div>
                <div className="mt-3 text-xs text-slate-500 leading-none">
                  전북은행·광주은행·JB우리캐피탈 총합
                </div>
              </div>

              {/* Card 3: High/Critical Risk ratio */}
              <div id="kpi-card-ratio" className="bg-white border border-slate-200 rounded-xl p-4.5 shadow-sm hover:translate-y-[-2px] transition-transform flex flex-col justify-between">
                <div className="flex justify-between items-start">
                  <div>
                    <span className="text-xs font-semibold text-slate-500 block">고위험군 광고물 비율</span>
                    <span className="text-2.5xl font-display font-extrabold text-rose-600 tracking-tight mt-1 inline-block">
                      {metrics.criticalRatio}%
                    </span>
                  </div>
                  <div className="p-2 bg-rose-50 rounded-lg text-rose-600">
                    <ShieldAlert className="w-5 h-5" />
                  </div>
                </div>
                <div className="mt-3 text-xs text-rose-600 hover:underline cursor-pointer font-bold flex items-center gap-0.5" onClick={() => { setLogRiskFilter(RiskLevel.CRITICAL); setActiveTab("history"); }}>
                  ⚠️ 초고위험 반려 대상 필터 검토 →
                </div>
              </div>

              {/* Card 4: Average Response Duration */}
              <div id="kpi-card-duration" className="bg-white border border-slate-200 rounded-xl p-4.5 shadow-sm hover:translate-y-[-2px] transition-transform flex flex-col justify-between">
                <div className="flex justify-between items-start">
                  <div>
                    <span className="text-xs font-semibold text-slate-500 block">평균 AI 소집 검의 속도</span>
                    <span className="text-2.5xl font-display font-extrabold text-slate-800 tracking-tight mt-1 inline-block">
                      {metrics.avgDurationMs > 0 ? metrics.avgDurationMs : "—"} <span className="text-xs font-semibold text-slate-400">{metrics.avgDurationMs > 0 ? "ms" : "(측정 미지원)"}</span>
                    </span>
                  </div>
                  <div className="p-2 bg-amber-50 rounded-lg text-amber-600">
                    <RefreshCw className="w-5 h-5" />
                  </div>
                </div>
                <div className="mt-3 text-xs text-slate-400 font-mono">
                  AI 엔진 & RAG 매치 시간 (백엔드 측정 시 표기)
                </div>
              </div>

            </div>

            {/* Main Interactive Charts Row */}
            <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
              
              {/* Line chart: Real-time traffic throughput graph flow */}
              <div id="graph-panel-traffic" className="bg-white border border-slate-200 rounded-xl p-5 shadow-sm lg:col-span-8">
                <div className="flex justify-between items-center mb-6">
                  <div>
                    <h3 className="text-xs font-bold uppercase tracking-wider text-indigo-600 font-display">실시간 트래픽 데이터 흐름</h3>
                    <p className="text-[11px] text-slate-400">준법감시망 10초 주기 실시간 처리 스캔 트폴로지 흐름 그래프</p>
                  </div>
                  <span className="text-[10px] bg-slate-100 border text-slate-600 px-2 py-0.5 rounded font-mono font-bold">RECHARTS STREAMS</span>
                </div>

                <div className="h-72 w-full">
                  {metrics.timelineGraph && metrics.timelineGraph.length > 0 ? (
                    <ResponsiveContainer width="100%" height="100%">
                      <AreaChart data={metrics.timelineGraph}>
                        <defs>
                          <linearGradient id="colorTps" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="5%" stopColor="#6366f1" stopOpacity={0.2}/>
                            <stop offset="95%" stopColor="#6366f1" stopOpacity={0}/>
                          </linearGradient>
                        </defs>
                        <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                        <XAxis dataKey="time" stroke="#94a3b8" fontSize={11} />
                        <YAxis stroke="#94a3b8" fontSize={11} />
                        <Tooltip />
                        <Area type="monotone" dataKey="value" stroke="#6366f1" strokeWidth={2} fillOpacity={1} fill="url(#colorTps)" name="초당 유입 준법검토" />
                      </AreaChart>
                    </ResponsiveContainer>
                  ) : (
                    <div className="h-full w-full flex flex-col items-center justify-center text-center border border-dashed border-slate-200 rounded-lg bg-slate-50/50">
                      <svg className="w-10 h-10 text-slate-300 mb-3" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" d="M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 0 1 3 19.875v-6.75ZM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 0 1-1.125-1.125V8.625ZM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 0 1-1.125-1.125V4.125Z" />
                      </svg>
                      <p className="text-sm font-semibold text-slate-500">아직 처리 데이터 없음</p>
                      <p className="text-[11px] text-slate-400 mt-1">실시간 심의가 발생하면 분당 처리량이 여기에 표시됩니다.</p>
                    </div>
                  )}
                </div>
              </div>

              {/* Term frequencies (단골 금지어 위배 단어 통계) */}
              <div id="graph-panel-words" className="bg-white border border-slate-200 rounded-xl p-5 shadow-sm lg:col-span-4 flex flex-col justify-between">
                <div>
                  <h3 className="text-xs font-bold uppercase tracking-wider text-rose-600 font-display mb-1">
                    위배 유도 단어 검출 빈도 (Top 7)
                  </h3>
                  <p className="text-[11px] text-slate-400 mb-4">현재 감사 보관함 기준 가장 많이 지적/교정된 누적 패턴 수치</p>
                </div>

                <div className="space-y-3">
                  {metrics.termFrequencies.slice(0, 5).map((term, i) => {
                    const maxCount = metrics.termFrequencies[0]?.count || 1;
                    const percentWidth = Math.max(10, Math.min(100, (term.count / maxCount) * 100));
                    
                    return (
                      <div key={i} className="space-y-1">
                        <div className="flex justify-between items-center text-xs">
                          <span className="font-semibold text-slate-700">{term.word}</span>
                          <span className="font-mono text-slate-500 font-bold">{term.count}회 검출</span>
                        </div>
                        <div className="w-full bg-slate-100 h-2 rounded-full overflow-hidden">
                          <div 
                            className="bg-rose-500 h-full rounded-full transition-all duration-500"
                            style={{ width: `${percentWidth}%` }}
                          ></div>
                        </div>
                      </div>
                    );
                  })}
                </div>

                <div className="mt-5 pt-3 border-t border-slate-100 bg-slate-50/50 p-2 text-center rounded-lg text-[10px] text-slate-400 leading-normal">
                  "원금 보장" 및 "확정 수익" 표현은 자본시장법 및 대고객 지침에 의거하여 최고 가중치의 벌금이 임명됩니다.
                </div>
              </div>

            </div>

            {/* Distribution Charts Grid Bar & Pie details */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              
              {/* Risk Levels distribution Pie chart */}
              <div id="graph-panel-risk" className="bg-white border border-slate-200 rounded-xl p-5 shadow-sm">
                <div className="flex justify-between items-center mb-4">
                  <div>
                    <h3 className="text-xs font-bold uppercase tracking-wider text-slate-800 font-display">감사물 유해성 위험등급 비중 분포</h3>
                    <p className="text-[11px] text-slate-400">보관 기록 중 치명, 고위험, 규정 조건부, 안전 분류 상태</p>
                  </div>
                </div>

                <div className="h-60 w-full flex items-center justify-center">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={riskChartData}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                      <XAxis dataKey="name" stroke="#94a3b8" fontSize={11} />
                      <YAxis stroke="#94a3b8" fontSize={11} />
                      <Tooltip />
                      <Bar dataKey="value" name="해당 등급 개수">
                        {riskChartData.map((entry, index) => (
                          <Cell key={`cell-${index}`} fill={entry.color} />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </div>

              {/* Advertising Channels distribution */}
              <div id="graph-panel-channel" className="bg-white border border-slate-200 rounded-xl p-5 shadow-sm">
                <div className="flex justify-between items-center mb-4">
                  <div>
                    <h3 className="text-xs font-bold uppercase tracking-wider text-slate-800 font-display">광고 채널 매칭 현황</h3>
                    <p className="text-[11px] text-slate-400">위험 검수가 집중 수행되는 특정 매체 채널 통계</p>
                  </div>
                </div>

                <div className="h-60 w-full">
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie
                        data={channelChartData}
                        cx="50%"
                        cy="50%"
                        labelLine={true}
                        label={({ name, percent }) => `${name} (${(percent * 100).toFixed(0)}%)`}
                        outerRadius={80}
                        fill="#4f46e5"
                        dataKey="value"
                      >
                        {channelChartData.map((entry, index) => (
                          <Cell key={`cell-${index}`} fill={["#4f46e5", "#06b6d4", "#f59e0b", "#ec4899", "#10b981"][index % 5]} />
                        ))}
                      </Pie>
                      <Tooltip />
                    </PieChart>
                  </ResponsiveContainer>
                </div>
              </div>

            </div>

          </div>
        )}

        {/* -------------------------------------------------------------
            TAB 3: Compliance Historical Audit Vault & Certification Generator
            ------------------------------------------------------------- */}
        {activeTab === "history" && (
          <div className="space-y-6">
            
            {/* Database controls on top */}
            <div className="bg-white border border-slate-200 rounded-xl p-4.5 shadow-sm flex flex-col md:flex-row justify-between items-center gap-4">
              
              <div className="flex items-center gap-3">
                <div className="p-2.5 bg-slate-900 text-white rounded-lg">
                  <Database className="w-5 h-5 text-emerald-400" />
                </div>
                <div>
                  <h3 className="text-sm font-bold text-slate-800">금융 준법 감사 기록 보관소</h3>
                  <p className="text-xs text-slate-500">
                    심의가 완료된 모든 광고문 및 전자 거래 텍스트는 영구 저장되어 법원 증거 또는 금감원 제출용으로 활용될 수 있습니다.
                  </p>
                </div>
              </div>

              <div className="flex items-center gap-2">
                <button
                  id="btn-download-csv"
                  onClick={handleDownloadCsv}
                  className="bg-emerald-50 text-emerald-700 hover:bg-emerald-100 border border-emerald-200 font-bold text-xs px-3.5 py-1.5 rounded-lg flex items-center gap-1.5 transition-all cursor-pointer"
                >
                  <FileSpreadsheet className="w-4 h-4" />
                  CSV 엑셀로 전체 다운로드
                </button>

                <button
                  id="btn-database-reset"
                  onClick={handleResetLogs}
                  className="bg-rose-50 text-rose-700 hover:bg-rose-100 border border-rose-200 font-semibold text-xs px-3 py-1.5 rounded-lg flex items-center gap-1.5 transition-all cursor-pointer"
                  title="감사 데이터를 원본 시드 상태로 강제 복원합니다"
                >
                  <RefreshCw className="w-4 h-4" />
                  데이터베이스 초기화
                </button>
              </div>

            </div>

            {/* Live Search and Filter Suite */}
            <div className="bg-slate-900 border border-slate-800 text-white rounded-xl p-4 shadow-sm">
              <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
                
                {/* Text query input */}
                <div className="md:col-span-2 relative">
                  <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
                  <input
                    id="search-history-query"
                    type="text"
                    placeholder="프로젝트 번호, 프로젝트 이름, 위배 표현 검색..."
                    value={logSearchQuery}
                    onChange={(e) => setLogSearchQuery(e.target.value)}
                    className="w-full text-xs pl-9 pr-3 py-2 bg-slate-800 border border-slate-700 focus:outline-none focus:border-indigo-500 rounded-lg text-slate-100 placeholder:text-slate-500"
                  />
                </div>

                {/* Channel Dropdown Filter */}
                <div>
                  <select
                    id="filter-history-channel"
                    value={logChannelFilter}
                    onChange={(e) => setLogChannelFilter(e.target.value)}
                    className="w-full text-xs px-3 py-2 bg-slate-800 border border-slate-700 focus:outline-none focus:border-indigo-500 rounded-lg text-slate-200 font-semibold cursor-pointer"
                  >
                    <option value="ALL">전체 광고 채널</option>
                    <option value={ChannelType.BANNER}>온라인 배너</option>
                    <option value={ChannelType.APP_PUSH}>앱푸시 알림</option>
                    <option value={ChannelType.SNS}>SNS 카드뉴스</option>
                    <option value={ChannelType.EMAIL}>고객 이메일</option>
                    <option value={ChannelType.LANDING}>랜딩 서식 설명</option>
                  </select>
                </div>

                {/* Risk Level Filter */}
                <div>
                  <select
                    id="filter-history-risk"
                    value={logRiskFilter}
                    onChange={(e) => setLogRiskFilter(e.target.value)}
                    className="w-full text-xs px-3 py-2 bg-slate-800 border border-slate-700 focus:outline-none focus:border-indigo-500 rounded-lg text-slate-200 font-semibold cursor-pointer"
                  >
                    <option value="ALL">전체 위험 범위</option>
                    <option value={RiskLevel.CRITICAL}>CRITICAL (치명)</option>
                    <option value={RiskLevel.HIGH}>HIGH (고위험)</option>
                    <option value={RiskLevel.MEDIUM}>MEDIUM (주의)</option>
                    <option value={RiskLevel.LOW}>LOW (안전)</option>
                  </select>
                </div>

              </div>

              {/* Status helper text row */}
              <div className="flex justify-between items-center text-[11px] text-slate-400 mt-3 pt-2.5 border-t border-slate-800">
                <span>일력 매칭 결과: <strong className="font-semibold text-emerald-400 font-mono">{filteredLogs.length}건</strong> 추출됨</span>
                <span>감사본부 보안 정책 제7조에 의거하여 상기 데이터는 상시 오프라인 백업이 보장됩니다.</span>
              </div>
            </div>

            {/* Audit log logs layout table */}
            <div className="bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden">
              <div className="overflow-x-auto">
                <table className="w-full text-left border-collapse">
                  <thead>
                    <tr className="bg-slate-50 text-[11px] uppercase tracking-wider text-slate-500 font-bold border-b border-slate-200 font-display">
                      <th className="py-3 px-4">고유 일련번호</th>
                      <th className="py-3 px-4">광고 프로젝트 정보</th>
                      <th className="py-3 px-4">채널</th>
                      <th className="py-3 px-4">가속 위험도</th>
                      <th className="py-3 px-4">결재 상태</th>
                      <th className="py-3 px-4">심의담당 계정</th>
                      <th className="py-3 px-4">검토일시 (UTC)</th>
                      <th className="py-3 px-4 text-center">동적 작업</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100 text-xs">
                    
                    {isLogsLoading ? (
                      <tr>
                        <td colSpan={8} className="py-8 text-center text-slate-400">
                          <RefreshCw className="w-6 h-6 animate-spin mx-auto mb-2 text-indigo-400" />
                          마스터 데이터 저장소 동기화 중...
                        </td>
                      </tr>
                    ) : filteredLogs.length === 0 ? (
                      <tr>
                        <td colSpan={8} className="py-12 text-center text-slate-500">
                          검색 필터에 부합하는 감사 보고 기록이 부재합니다. 다른 조건으로 탐색해 보십시오.
                        </td>
                      </tr>
                    ) : (
                      filteredLogs.map((item) => {
                        // Badge decorations
                        let riskBadge = "bg-green-50 text-emerald-700 border-green-100";
                        if (item.riskLevel === RiskLevel.CRITICAL) riskBadge = "bg-rose-100 text-red-800 font-bold border-rose-200 animate-pulse";
                        else if (item.riskLevel === RiskLevel.HIGH) riskBadge = "bg-rose-50 text-rose-700 font-semibold border-rose-100";
                        else if (item.riskLevel === RiskLevel.MEDIUM) riskBadge = "bg-amber-50 text-amber-700 border-amber-100";

                        let statusBadge = "bg-slate-50 text-slate-600";
                        if (item.status === ComplianceStatus.APPROVED) statusBadge = "bg-teal-50 text-emerald-700 font-bold border border-teal-200";
                        else if (item.status === ComplianceStatus.REJECTED) statusBadge = "bg-rose-50 text-rose-700 font-bold border border-rose-200";
                        else if (item.status === ComplianceStatus.AMENDED) statusBadge = "bg-yellow-50 text-yellow-800 font-semibold border border-yellow-200";

                        return (
                          <tr
                            id={`history-row-${item.id}`}
                            key={item.id}
                            onClick={() => setSelectedHistoryItem(item)}
                            className={`hover:bg-slate-50/80 cursor-pointer transition-colors ${
                              selectedHistoryItem?.id === item.id ? "bg-indigo-50/40 font-medium" : ""
                            }`}
                          >
                            <td className="py-3.5 px-4 font-mono font-bold text-slate-700">
                              {item.id}
                            </td>
                            <td className="py-3.5 px-4 max-w-xs md:max-w-md truncate">
                              <div className="flex items-center gap-1.5 min-w-0">
                                {item.fileName && (
                                  <span className="shrink-0 text-[10px] font-bold bg-[#f1f5f9] border border-[#e2e8f0] text-[#475569] px-1.5 py-0.5 rounded flex items-center gap-0.5 font-sans" title={`${item.fileName} 파일 포함`}>
                                    <Paperclip className="w-2.5 h-2.5" /> 첨부
                                  </span>
                                )}
                                <p className="font-bold text-slate-800 truncate">{item.projectName}</p>
                              </div>
                              <p className="text-[10px] text-slate-400 truncate mt-0.5">{item.inputContent}</p>
                            </td>
                            <td className="py-3.5 px-4 font-medium text-slate-600">
                              <span className="bg-slate-100 px-2 py-0.5 rounded font-mono text-[10px]">
                                {item.channel}
                              </span>
                            </td>
                            <td className="py-3.5 px-4">
                              <span className={`text-[10px] px-2 py-0.5 rounded-full border ${riskBadge}`}>
                                {item.riskLevel}
                              </span>
                            </td>
                            <td className="py-3.5 px-4">
                              <span className={`text-[10px] px-2 py-0.5 rounded ${statusBadge}`}>
                                {item.status}
                              </span>
                            </td>
                            <td className="py-3.5 px-4 text-slate-500 font-mono text-[11px]">
                              {item.userEmail}
                            </td>
                            <td className="py-3.5 px-4 text-slate-400 font-mono text-[10.5px]">
                              {new Date(item.createdAt).toLocaleString()}
                            </td>
                            <td className="py-3.5 px-4 text-center">
                              <div className="flex items-center justify-center gap-1.5">
                                <button
                                  id={`btn-delete-row-${item.id}`}
                                  onClick={(e) => handleDeleteLog(item.id, e)}
                                  className="p-1 px-1.5 border border-slate-200 bg-white hover:bg-rose-50 hover:border-rose-200 hover:text-red-600 text-slate-400 rounded-md transition-all cursor-pointer"
                                  title="감사물 영구 삭제 (Admin 전용)"
                                >
                                  <Trash2 className="w-3.5 h-3.5" />
                                </button>
                              </div>
                            </td>
                          </tr>
                        );
                      })
                    )}

                  </tbody>
                </table>
              </div>
            </div>

            {/* Split layout: Extended review detailed inspector content */}
            {selectedHistoryItem && (
              <div id="inspector-panel-expanded" className="bg-white border border-slate-200 shadow-md rounded-xl p-5 md:p-6 grid grid-cols-1 lg:grid-cols-12 gap-6 animate-fade-in">
                
                <div className="lg:col-span-8 space-y-4">
                  <div className="flex justify-between items-start pb-2 border-b">
                    <div>
                      <span className="text-[10px] text-slate-400 block font-mono font-bold uppercase">COMMITTED LOG AUDIT INSPECTOR</span>
                      <h3 className="text-base font-bold text-slate-800 mt-0.5">
                        {selectedHistoryItem.projectName}
                      </h3>
                    </div>
                    <button
                      id="btn-inspect-certificate"
                      onClick={() => setShowCertModal(true)}
                      className="bg-slate-900 hover:bg-slate-850 text-white font-bold text-xs px-2.5 py-1.5 rounded-lg flex items-center gap-1 shadow-sm transition-all cursor-pointer"
                    >
                      <Download className="w-3.5 h-3.5 text-emerald-400" />
                      디지털 검증 인증서 출력
                    </button>
                  </div>

                  {/* High quality parsed HTML Markup element visualization */}
                  <div className="space-y-1.5">
                    <span className="text-xs font-semibold text-slate-500 block">검사 원물 및 위험 표현 마스킹</span>
                    <div className="bg-slate-50 border border-slate-200 p-4 rounded-xl text-xs font-mono leading-relaxed text-slate-800">
                      <p dangerouslySetInnerHTML={{ __html: selectedHistoryItem.checkedContent || '' }}></p>
                    </div>
                  </div>

                  {/* Attachment metadata visualization block inside selectedHistoryItem inspector */}
                  {selectedHistoryItem.fileName && selectedHistoryItem.fileData && (
                    <div className="space-y-1.5">
                      <span className="text-xs font-semibold text-slate-500 block">검토 첨부 자료 ({selectedHistoryItem.fileName})</span>
                      <div className="bg-slate-50 border border-slate-200 p-3.5 rounded-xl flex flex-col sm:flex-row items-center gap-3">
                        {selectedHistoryItem.fileMimeType?.startsWith("image/") ? (
                          <img
                            src={selectedHistoryItem.fileData.includes(";base64,") ? selectedHistoryItem.fileData : `data:${selectedHistoryItem.fileMimeType};base64,${selectedHistoryItem.fileData}`}
                            alt="Review Attachment"
                            className="max-w-[200px] max-h-[140px] object-contain rounded-lg border border-slate-200 shadow-sm bg-white p-1"
                            referrerPolicy="no-referrer"
                          />
                        ) : (
                          <div className="w-16 h-16 bg-slate-100 border border-slate-200 text-slate-500 flex items-center justify-center rounded-lg shadow-sm shrink-0">
                            <FileText className="w-8 h-8" />
                          </div>
                        )}
                        <div className="min-w-0 text-left">
                          <p className="text-xs font-bold text-slate-800 truncate">{selectedHistoryItem.fileName}</p>
                          <p className="text-[10px] text-slate-500 font-mono font-semibold uppercase">{selectedHistoryItem.fileMimeType || "document"}</p>
                          <div className="mt-1.5">
                            <a
                              href={selectedHistoryItem.fileData.includes(";base64,") ? selectedHistoryItem.fileData : `data:${selectedHistoryItem.fileMimeType};base64,${selectedHistoryItem.fileData}`}
                              download={selectedHistoryItem.fileName}
                              className="text-[10.5px] font-bold text-indigo-600 hover:text-indigo-800 flex items-center gap-1 bg-white border border-slate-200 px-2.5 py-1 rounded-lg shadow-2xs hover:shadow-xs hover:border-indigo-250 transition-all select-none w-fit"
                            >
                              <Download className="w-3 h-3 text-indigo-500" /> 다운로드 받기
                            </a>
                          </div>
                        </div>
                      </div>
                    </div>
                  )}

                  {/* Summary reasoning */}
                  <div>
                    <span className="text-xs font-semibold text-slate-500 block mb-1">검사 결과 및 실무 조치 내역</span>
                    <p className="text-xs text-slate-700 bg-teal-50/30 p-3 rounded-lg border border-teal-100 leading-normal">
                      🛡️ <strong>종합 판결 사유:</strong> {selectedHistoryItem.findingsSum || "특별한 법령 및 내부 저촉 준수 하자가 검출되지 않아 자동 패스 승인되었습니다."}
                    </p>
                  </div>

                  {/* Auto detected tags */}
                  {selectedHistoryItem.detectedViolations.length > 0 && (
                    <div>
                      <span className="text-xs font-semibold text-slate-500 block mb-1">매칭된 금지 패턴 태그</span>
                      <div className="flex flex-wrap gap-1.5">
                        {selectedHistoryItem.detectedViolations.map((v, i) => (
                          <span key={i} className="text-xs font-semibold bg-rose-50 text-rose-700 border border-rose-200 px-2.5 py-1 rounded">
                            {v}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}

                </div>

                <div className="lg:col-span-4 bg-slate-50 p-4.5 rounded-xl border border-slate-200 flex flex-col justify-between">
                  <div>
                    <h4 className="text-xs font-bold uppercase tracking-wider text-slate-600 font-display mb-3">
                      개별 심의 단계 이력 요약
                    </h4>
                    
                    <div className="space-y-2.5">
                      {selectedHistoryItem.stages.slice(2, 6).map((st) => (
                        <div key={st.id} className="flex justify-between items-center bg-white p-2 border rounded text-xs">
                          <div>
                            <span className="text-[10px] text-slate-400 block font-mono font-bold">STAGE {st.id}</span>
                            <span className="font-semibold text-slate-700">{st.title}</span>
                          </div>
                          <span className={`text-[9px] font-bold px-1 rounded ${
                            st.status === "SUCCESS" ? "bg-emerald-50 text-emerald-700" :
                            st.status === "FAILED" ? "bg-rose-50 text-rose-700" : "bg-amber-50 text-amber-700"
                          }`}>
                            {st.status === "SUCCESS" ? "통과" : st.status === "FAILED" ? "저촉" : st.status === "PARTIAL" ? "검토 필요" : st.status}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>

                  <div className="pt-4 border-t mt-4">
                    <p className="text-[11px] text-slate-400 text-center leading-normal">
                      본 결과는 내부 보안 준법감시원회 6인 의사에 따른 자동화 RAG 증명본이며 수정본은 발송 후 교차 심사 대상이 됩니다.
                    </p>
                  </div>

                </div>

              </div>
            )}

            {/* Modal: Official digital certificate download simulation popup */}
            {showCertModal && selectedHistoryItem && (
              <div id="modal-digital-certification" className="fixed inset-0 z-50 overflow-y-auto bg-slate-900/60 backdrop-blur-sm flex items-center justify-center p-4">
                <div className="bg-white border-2 border-slate-800 shadow-2xl rounded-2xl max-w-2xl w-full p-6 md:p-8 relative cert-card">

                  {/* Decorative Border Line */}
                  <div className="absolute inset-2 border border-slate-200 rounded-xl pointer-events-none"></div>

                  <button
                    id="btn-close-cert-modal"
                    onClick={() => setShowCertModal(false)}
                    className="absolute top-4 right-4 bg-slate-100 hover:bg-slate-200 text-slate-600 rounded-full p-1.5 transition-all text-xs z-10 cursor-pointer"
                  >
                    ✕
                  </button>

                  {/* Certification Header */}
                  <div className="text-center space-y-2.5 mb-6 relative">
                    <div className="w-12 h-12 bg-slate-900 text-white rounded-full flex items-center justify-center mx-auto shadow-inner">
                      <ShieldAlert className="w-6 h-6 text-emerald-400 stroke-[2]" />
                    </div>
                    <span className="text-[10px] uppercase font-bold tracking-widest text-[#0e7490] block font-mono">JB FINANCIAL GROUP ADVISORY SERVICES</span>
                    <h2 className="text-xl md:text-2xl font-bold tracking-tight text-slate-800">준법 심의 검출 보고 증명서</h2>
                    <p className="text-xs text-slate-500 font-medium">율리 Official Certification Seal</p>
                  </div>

                  {/* Body Content */}
                  <div className="bg-slate-50 border border-slate-200 rounded-xl p-5 space-y-4 text-xs font-mono relative leading-relaxed">
                    
                    <div className="grid grid-cols-2 gap-3 text-[11px] border-b pb-3 border-slate-200">
                      <div>
                        <span className="text-slate-400 block font-sans">감사 일련 번호</span>
                        <strong className="text-slate-800">{selectedHistoryItem.id}</strong>
                      </div>
                      <div>
                        <span className="text-slate-400 block font-sans">채널 플랫폼</span>
                        <strong className="text-slate-800">{selectedHistoryItem.channel}</strong>
                      </div>
                      <div>
                        <span className="text-slate-400 block font-sans">심의 의결 담당</span>
                        <strong className="text-slate-800 font-sans">{selectedHistoryItem.userEmail}</strong>
                      </div>
                      <div>
                        <span className="text-slate-400 block font-sans">발급 시각 (UTC)</span>
                        <strong className="text-slate-800">{new Date(selectedHistoryItem.createdAt).toISOString()}</strong>
                      </div>
                    </div>

                    <div className="space-y-1">
                      <span className="text-slate-400 block font-sans font-semibold">심의 완료 광고 원고:</span>
                      <div className="bg-white border p-3 rounded font-sans leading-relaxed text-slate-700 text-[11px]">
                        {selectedHistoryItem.inputContent}
                      </div>
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                      <div>
                        <span className="text-slate-400 block font-sans font-semibold">감사 위험 가속성 지합 (Verdicts)</span>
                        <span className={`text-[11px] font-bold px-2.5 py-1 rounded inline-block mt-1 ${
                          selectedHistoryItem.riskLevel === RiskLevel.CRITICAL
                            ? "bg-rose-100 text-rose-800"
                            : "bg-emerald-100 text-emerald-800"
                        }`}>
                          LEVEL: {selectedHistoryItem.riskLevel} / {selectedHistoryItem.status}
                        </span>
                      </div>
                      <div>
                        <span className="text-slate-400 block font-sans font-semibold">감사 일련 식별자</span>
                        <span className="text-[10px] text-slate-400 select-all block mt-1 break-all">
                          감사 ID: {selectedHistoryItem.__report?.audit_log_id || selectedHistoryItem.id}
                        </span>
                      </div>
                    </div>

                    <div className="border-t pt-3 space-y-1.5 font-sans leading-relaxed text-slate-600 text-[11px]">
                      <p>🛡️ <strong>자문위원회 최종 조율 수렴:</strong> {selectedHistoryItem.findingsSum}</p>
                    </div>

                  </div>

                  {/* Footstamp */}
                  <div className="mt-6 flex flex-col md:flex-row justify-between items-center gap-4 text-xs font-medium text-slate-400 pt-4 border-t">
                    <span className="font-mono text-[9px] text-[#0891b2] font-semibold tracking-wider">▲ APPROVED BY JB AUDIT COUNCIL</span>
                    <button
                      id="btn-print-certificate"
                      onClick={handlePrintCertificate}
                      className="bg-indigo-600 hover:bg-indigo-700 text-white font-bold text-xs px-4 py-2 rounded-lg cursor-pointer flex items-center gap-1 transition-all shadow-md"
                    >
                      <Download className="w-4 h-4 text-indigo-200" />
                      공식 양식 인쇄 (Print)
                    </button>
                  </div>

                </div>
              </div>
            )}

          </div>
        )}

        {/* -------------------------------------------------------------
            TAB 4: System Architecture Document (시스템 아키텍처 및 보안 상세)
            ------------------------------------------------------------- */}
        {activeTab === "architecture" && (
          <div className="bg-white border border-slate-200 rounded-xl p-6 shadow-sm space-y-8 animate-fade-in">
            
            <div className="pb-4 border-b">
              <span className="text-[10px] uppercase font-bold text-rose-600 block tracking-widest font-mono">OFFICIAL ARCHITECTURE SPECIFICATION</span>
              <h2 className="text-xl md:text-2xl font-bold text-slate-800 mt-0.5">
                율리 전단 시스템 아키텍처 가이드
              </h2>
              <p className="text-xs text-slate-500">
                개개발 가이드라인, 보안 정책 준수, 실시간 시각화 아키텍처 및 백엔드 API 명세 표준본
              </p>
            </div>

            {/* CSS shaped vector schematic visualizing the processing pipeline */}
            <div id="vector-pipeline-schematic" className="bg-slate-900 text-white p-6 rounded-2xl border border-slate-800 space-y-4">
              <div className="flex items-center gap-2 mb-2">
                <Server className="w-5 h-5 text-indigo-400" />
                <h3 className="text-xs font-bold uppercase tracking-widest text-indigo-300 font-display">
                  1. 실시간 준법 심의 데이터 라이프사이클 흐름 (System Pipeline Dataflow)
                </h3>
              </div>

              {/* Graphical schematic container */}
              <div className="grid grid-cols-1 md:grid-cols-5 gap-4 text-center text-xs mt-3">
                <div className="bg-slate-850 p-3 rounded-xl border border-slate-800 relative">
                  <span className="text-[9px] font-bold text-slate-500 block font-mono">STEP 01</span>
                  <strong className="text-slate-200 text-[11px] block mt-1">대고객 광고 원고</strong>
                  <span className="text-[9px] text-indigo-400 block mt-2">React UI Input Submissions</span>
                </div>
                
                <div className="md:col-span-1 flex items-center justify-center text-slate-600 font-bold font-mono py-1">
                  ──────▶
                </div>

                <div className="bg-slate-850 p-3 rounded-xl border border-rose-900 relative">
                  <span className="text-[9px] font-bold text-[#fecdd3] block font-mono">STEP 02</span>
                  <strong className="text-rose-300 text-[11px] block mt-1">AI 6인 자문 보드</strong>
                  <span className="text-[9px] text-rose-400 block mt-2">OpenAI GPT (gpt-5.x) / Python Engine · Legal RAG</span>
                </div>

                <div className="md:col-span-1 flex items-center justify-center text-slate-600 font-bold font-mono py-1">
                  ──────▶
                </div>

                <div className="bg-slate-850 p-3 rounded-xl border border-emerald-900 relative">
                  <span className="text-[9px] font-bold text-[#a7f3d0] block font-mono">STEP 03</span>
                  <strong className="text-emerald-300 text-[11px] block mt-1">위반 하이라이팅</strong>
                  <span className="text-[9px] text-emerald-400 block mt-2">SHA256 Hashing / DB Vault Logs</span>
                </div>
              </div>

              <p className="text-[11px] text-slate-400 leading-normal pt-2">
                * **보안 격리:** 외부 통신 시 OpenAI API key 및 고객 개인 식별 정보(PII)는 절대로 브라우저 클라이언트에 노출하지 않으며, 전량 Back-end Proxy Router(`/api/review`) 및 암호화 설정 저장소(secure_settings.json.enc) 내에서 가공 마스킹 처리 후 전달됩니다.
              </p>
            </div>

            {/* Back-end API routing blueprints */}
            <div className="space-y-4">
              <h3 className="text-sm font-bold text-slate-800">
                2. 안정적인 백엔드 API 명세서 (Backend APIs Directory)
              </h3>
              
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                
                {/* Router 1 */}
                <div className="border border-slate-200 p-4 rounded-xl space-y-2">
                  <div className="flex items-center gap-2">
                    <span className="px-2 py-0.5 bg-emerald-100 text-emerald-800 font-mono font-extrabold text-[10px] rounded">POST</span>
                    <code className="text-xs font-semibold text-slate-700 font-mono">/api/review</code>
                  </div>
                  <p className="text-xs text-slate-500 leading-relaxed">
                    실시간 광고문 텍스트 준법 심의 분석 요청. OpenAI GPT 엔진(Python FastAPI worker) 및 자문 RAG 정보망에 병렬 쿼리하여 ComplianceReport(findings·board·verifier·evidence)를 산출합니다.
                  </p>
                </div>

                {/* Router 2 */}
                <div className="border border-slate-200 p-4 rounded-xl space-y-2">
                  <div className="flex items-center gap-2">
                    <span className="px-2 py-0.5 bg-sky-100 text-sky-800 font-mono font-extrabold text-[10px] rounded">GET</span>
                    <code className="text-xs font-semibold text-slate-700 font-mono">/api/history · /api/audit/logs</code>
                  </div>
                  <p className="text-xs text-slate-500 leading-relaxed">
                    준법 마스터 DB의 누적 이력을 조회합니다. 전체 검색 쿼리, 일련번호 역순 정렬, 채널별 필터 연산을 지원합니다.
                  </p>
                </div>

                {/* Router 3 — 수정 광고 원고 생성 */}
                <div className="border border-slate-200 p-4 rounded-xl space-y-2">
                  <div className="flex items-center gap-2">
                    <span className="px-2 py-0.5 bg-emerald-100 text-emerald-800 font-mono font-extrabold text-[10px] rounded">POST</span>
                    <code className="text-xs font-semibold text-slate-700 font-mono">/api/review/rewrite</code>
                  </div>
                  <p className="text-xs text-slate-500 leading-relaxed">
                    심의 완료된 광고문의 위반 표현을 규정에 맞는 컴플라이언트 대체 문구로 재작성합니다. 원문 룰스캔으로 findings를 복원한 뒤 생성 에이전트가 수정 원고를 산출합니다.
                  </p>
                </div>

                {/* Router 4 — 자기학습 피드백 */}
                <div className="border border-slate-200 p-4 rounded-xl space-y-2">
                  <div className="flex items-center gap-2">
                    <span className="px-2 py-0.5 bg-amber-100 text-amber-800 font-mono font-extrabold text-[10px] rounded">POST</span>
                    <code className="text-xs font-semibold text-slate-700 font-mono">/api/review/feedback</code>
                  </div>
                  <p className="text-xs text-slate-500 leading-relaxed">
                    심의 결과에 대한 좋아요/나빠요 사용자 피드백을 자기학습 루프에 '사람 검증' 신호로 주입합니다. 정확(good)은 success 패턴, 오탐(bad)은 failure 패턴으로 캡처되어 다음 심의 품질을 개선합니다.
                  </p>
                </div>

                {/* Router 5 — 이력 삭제 */}
                <div className="border border-slate-200 p-4 rounded-xl space-y-2">
                  <div className="flex items-center gap-2">
                    <span className="px-2 py-0.5 bg-rose-100 text-rose-800 font-mono font-extrabold text-[10px] rounded">DELETE</span>
                    <code className="text-xs font-semibold text-slate-700 font-mono">/api/history/:id</code>
                  </div>
                  <p className="text-xs text-slate-500 leading-relaxed">
                    특정 감사 번호의 영구 소멸 제거. 권한이 높은 <strong>ADMIN</strong> 계정 세션만 접근 통제(ACL) 규칙에 의해 가결 처리됩니다.
                  </p>
                </div>

              </div>
            </div>

            {/* Security Compliance policies */}
            <div className="space-y-4">
              <h3 className="text-sm font-bold text-slate-800 flex items-center gap-1.5">
                <Lock className="w-4 h-4 text-rose-600" />
                3. 보안 준수 및 기술 표준 요구사항 (Security Policies & Design Details)
              </h3>

              <div className="bg-slate-50 border border-slate-200 rounded-xl p-5 space-y-3.5 text-xs text-slate-600 leading-relaxed">
                <div>
                  <h4 className="font-bold text-slate-800">■ 금소법 제 19조(설명의무) 및 광고 수칙 완수</h4>
                  <p className="mt-1">
                    소비자의 인지 약점을 악용할 수 있는 3대 사칭 허위 문구("원금 보장", "확정 수익", "무조건 승인")가 감지될 경우 해당 광고물의 위험 등급은 즉시 <strong>CRITICAL</strong>로 배정되고 배포가 제한됩니다.
                  </p>
                </div>

                <div>
                  <h4 className="font-bold text-slate-800">■ 실시간 대화형 시각화 렌더링 규격</h4>
                  <p className="mt-1">
                    수집된 시각화 정보는 라이브 4초 주기로 dynamic polling(/api/analytics/realtime) 처리되어 흐름을 Recharts 실시간 TPS 면적 그래프로 제공합니다. 모든 수치는 실제 감사 이력(/api/history)에서 파생됩니다.
                  </p>
                </div>

                <div>
                  <h4 className="font-bold text-slate-800">■ 대고객 개인정보 유출 방지 및 마스킹 가이드</h4>
                  <p className="mt-1">
                    이메일 주소, 신분증, 계좌 비밀번호 등 민감 PII가 텍스트에 포함될 경우 AI Agent는 PII 자동 마스킹 처리를 속행하며, 이를 보안 감사 로그에 적합하게 격리 표기합니다.
                  </p>
                </div>
              </div>
            </div>

          </div>
        )}

        {/* -------------------------------------------------------------
            Operational console tabs (Admin / Audit / Knowledge / Workflow / Batch)
            Reused from the parent React UI, rewired to the real Python backend.
            ------------------------------------------------------------- */}
        {(activeTab === "admin" ||
          activeTab === "audit" ||
          activeTab === "knowledge" ||
          activeTab === "workflow" ||
          activeTab === "batch") && (
          <div className="animate-fade-in">
            <OperationsPanel
              tab={activeTab}
              health={health}
              activeReport={activeReport}
              metadata={metadata}
              onSelectReport={(report) => {
                setActiveReport(report);
                setActiveScreeningResult(
                  reportToAuditItem(report, { userEmail: session?.email })
                );
                setActiveTab("screen");
              }}
              onReportsProduced={(reports) => {
                const items = reportsToAuditItems(reports);
                setAuditLogs((prev) => [...items, ...prev]);
                if (reports[0]) setActiveReport(reports[0]);
              }}
              onRefreshHealth={fetchHealth}
            />
          </div>
        )}

      </main>

      {/* -------------------------------------------------------------
          Footer Area
          ------------------------------------------------------------- */}
      <footer className="bg-slate-900 text-slate-400 py-6 px-6 border-t border-slate-800 mt-12">
        <div className="max-w-7xl mx-auto flex flex-col md:flex-row justify-between items-center gap-4 text-xs">
          <div>
            <p className="font-semibold text-slate-300">© 2026 JB Financial Group. 율리.</p>
            <p className="text-slate-500 mt-1">본 시스템은 준법 검토 보조 도구이며 법률 자문을 대체하지 않습니다. 모든 고위험 판정은 준법 담당자의 최종 검토를 거칩니다.</p>
          </div>
          <div className="flex gap-4">
            <span className="text-slate-500 hover:text-slate-400">전북은행 본부</span>
            <span>|</span>
            <span className="text-slate-500 hover:text-slate-400">광주은행 준법실</span>
            <span>|</span>
            <span className="text-slate-500 hover:text-slate-400">감사본부장 임종백</span>
          </div>
        </div>
      </footer>

    </div>
  );
}
