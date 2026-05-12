"use client";

import { useEffect, useRef, useState } from "react";
import {
  Search,
  BarChart3,
  ShieldAlert,
  FileText,
  Settings,
  Upload,
  Link as LinkIcon,
  FileCode,
  AlertCircle,
  CheckCircle2,
  Play,
  Zap,
  Printer,
} from "lucide-react";
import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";
import { MOCK_EVENTS } from "./mock-data";

function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

type AgentEvent = {
  agent: string;
  type: string;
  content: string;
};

type Brief = {
  recommendation: string;
  confidence_score: number;
  confidence_explanation: string;
  one_paragraph_summary: string;
  key_strengths: { point: string; source_citation: string }[];
  key_risks: { point: string; severity: string; source_citation: string }[];
  follow_up_questions: string[];
  dissenting_views: string[];
};

type VerificationReport = {
  integrity_score: number;
  total_claims_checked: number;
  verified_count?: number;
  plausible_count?: number;
  flagged_count?: number;
  hallucination_count?: number;
  note?: string;
  claims: {
    claim: string;
    type: string;
    score: number;
    integrity_score?: number;
    status: string;
    consistency?: string;
    reasoning?: string;
    best_source_snippet: string;
  }[];
};

function claimStatusClasses(status: string): string {
  switch (status) {
    case "VERIFIED":
      return "bg-teal-100 text-teal-700";
    case "PLAUSIBLE":
      return "bg-amber-100 text-amber-700";
    case "HALLUCINATION":
      return "bg-rose-200 text-rose-800";
    default: // FLAGGED / UNVERIFIED / anything else
      return "bg-rose-100 text-rose-700";
  }
}

const AGENTS = [
  {
    id: "orchestrator",
    name: "Orchestrator",
    icon: Settings,
    color: "text-purple-500",
    bg: "bg-purple-50",
  },
  {
    id: "researcher",
    name: "Researcher",
    icon: Search,
    color: "text-blue-500",
    bg: "bg-blue-50",
  },
  {
    id: "analyst",
    name: "Analyst",
    icon: BarChart3,
    color: "text-emerald-500",
    bg: "bg-emerald-50",
  },
  {
    id: "red_team",
    name: "Red Team",
    icon: ShieldAlert,
    color: "text-rose-500",
    bg: "bg-rose-50",
  },
  {
    id: "synthesizer",
    name: "Synthesizer",
    icon: FileText,
    color: "text-amber-500",
    bg: "bg-amber-50",
  },
  {
    id: "verifier",
    name: "Verifier",
    icon: CheckCircle2,
    color: "text-teal-500",
    bg: "bg-teal-50",
  },
];

export default function Home() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [agentEvents, setAgentEvents] = useState<Record<string, AgentEvent[]>>(
    {},
  );
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [brief, setBrief] = useState<Brief | null>(null);
  const [verificationReport, setVerificationReport] =
    useState<VerificationReport | null>(null);
  const [activeTab, setActiveTab] = useState<string>("agents");
  const eventSourceRef = useRef<EventSource | null>(null);
  const scrollRefs = useRef<Record<string, HTMLDivElement | null>>({});

  const [uploadedFiles, setUploadedFiles] = useState<
    { name: string; id: string }[]
  >([]);
  const [uploadedUrls, setUploadedUrls] = useState<string[]>([]);
  const [urlInput, setUrlInput] = useState("");
  const [backendStatus, setBackendStatus] = useState<
    "connecting" | "online" | "offline"
  >("connecting");
  const fileInputRef = useRef<HTMLInputElement>(null);
  const imageInputRef = useRef<HTMLInputElement>(null);

  const [isDemoMode, setIsDemoMode] = useState(false);
  const [showHelp, setShowHelp] = useState(false);
  const [uploadingType, setUploadingType] = useState<"document" | "image" | null>(null);

  const removeFile = (id: string) => {
    setUploadedFiles((prev) => prev.filter((f) => f.id !== id));
  };

  const removeUrl = (url: string) => {
    setUploadedUrls((prev) => prev.filter((u) => u !== url));
  };

  useEffect(() => {
    const isDemo =
      typeof window !== "undefined" &&
      window.location.search.includes("demo=true");
    if (isDemo) setIsDemoMode(true);
  }, []);

  useEffect(() => {
    const checkBackend = async () => {
      // If we are already in demo mode, don't keep polling the backend
      if (isDemoMode) {
        setBackendStatus("online");
        return;
      }
      try {
        const res = await fetch("/api/", { cache: "no-store" });
        if (res.ok) setBackendStatus("online");
        else setBackendStatus("offline");
      } catch {
        setBackendStatus("offline");
      }
    };
    checkBackend();

    // Only poll if we aren't in demo mode
    const interval = setInterval(() => {
      if (!isDemoMode) checkBackend();
    }, 15000);

    return () => clearInterval(interval);
  }, [isDemoMode]);

  const ensureSession = async () => {
    if (sessionId) return sessionId;
    if (isDemoMode) {
      const sid = "demo-" + Math.random().toString(36).substring(2, 9);
      setSessionId(sid);
      return sid;
    }
    const sessionRes = await fetch("/api/sessions", { method: "POST" });
    if (!sessionRes.ok) throw new Error("Failed to create session");
    const { session_id } = await sessionRes.json();
    setSessionId(session_id);
    return session_id;
  };

  const handleFileUpload = async (
    e: React.ChangeEvent<HTMLInputElement>,
    type: "document" | "image",
  ) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setUploadingType(type);
    const fileId = Math.random().toString(36).substring(7);

    if (isDemoMode) {
      await new Promise((r) => setTimeout(r, 800)); // Simulate delay for demo
      setUploadedFiles((prev) => [...prev, { name: file.name, id: fileId }]);
      if (e.target) e.target.value = "";
      setUploadingType(null);
      return;
    }

    try {
      const sid = await ensureSession();
      const formData = new FormData();
      formData.append("file", file);

      const res = await fetch(`/api/sessions/${sid}/inputs/${type}`, {
        method: "POST",
        body: formData,
      });

      if (res.ok) {
        setUploadedFiles((prev) => [...prev, { name: file.name, id: fileId }]);
      }
    } catch (err) {
      console.error(err);
      alert("Failed to upload file");
    } finally {
      if (e.target) e.target.value = "";
      setUploadingType(null);
    }
  };

  const handleUrlAdd = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!urlInput.trim()) return;

    if (isDemoMode) {
      setUploadedUrls((prev) => [...prev, urlInput.trim()]);
      setUrlInput("");
      return;
    }

    try {
      const sid = await ensureSession();
      const res = await fetch(`/api/sessions/${sid}/inputs/url`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: urlInput.trim() }),
      });

      if (res.ok) {
        setUploadedUrls((prev) => [...prev, urlInput.trim()]);
        setUrlInput("");
      }
    } catch (err) {
      console.error(err);
      alert("Failed to add URL");
    }
  };

  const closeStream = () => {
    eventSourceRef.current?.close();
    eventSourceRef.current = null;
  };

  const startAnalysis = async () => {
    if (isAnalyzing) return;

    closeStream();
    setAgentEvents({});
    setBrief(null);
    setVerificationReport(null);
    setIsAnalyzing(true);

    if (isDemoMode) {
      // Run mock analysis
      for (const event of MOCK_EVENTS) {
        await new Promise((r) => setTimeout(r, 800 + Math.random() * 1200));

        setAgentEvents((prev) => ({
          ...prev,
          [event.agent]: [...(prev[event.agent] || []), event],
        }));

        if (event.type === "brief") {
          setBrief(JSON.parse(event.content));
        }
        if (event.type === "verification_report") {
          setVerificationReport(JSON.parse(event.content));
        }
        if (
          event.agent === "orchestrator" &&
          event.type === "status" &&
          event.content === "done"
        ) {
          setIsAnalyzing(false);
        }
      }
      return;
    }

    let currentSessionId = sessionId;
    if (!currentSessionId) {
      try {
        const sessionRes = await fetch("/api/sessions", { method: "POST" });
        if (!sessionRes.ok) {
          setIsAnalyzing(false);
          return;
        }
        const { session_id } = await sessionRes.json();
        currentSessionId = session_id;
        setSessionId(session_id);
      } catch (err) {
        console.error("Backend error, suggesting demo mode:", err);
        setIsAnalyzing(false);
        return;
      }
    }

    const es = new EventSource(`/api/sessions/${currentSessionId}/stream`);
    eventSourceRef.current = es;

    es.onmessage = (event) => {
      const data: AgentEvent = JSON.parse(event.data);

      setAgentEvents((prev) => ({
        ...prev,
        [data.agent]: [...(prev[data.agent] || []), data],
      }));

      if (data.type === "brief") {
        setBrief(JSON.parse(data.content));
      }
      if (data.type === "verification_report") {
        setVerificationReport(JSON.parse(data.content));
      }
      if (
        data.agent === "orchestrator" &&
        data.type === "status" &&
        data.content === "done"
      ) {
        closeStream();
        setIsAnalyzing(false);
      }
      if (data.type === "error") {
        closeStream();
        setIsAnalyzing(false);
      }
    };

    es.onerror = () => {
      closeStream();
      setIsAnalyzing(false);
    };

    await fetch(`/api/sessions/${currentSessionId}/analyze`, {
      method: "POST",
    });
  };

  const handleFollowUp = async (question: string) => {
    if (!sessionId) return;

    if (isDemoMode) {
      setBrief(null);
      setVerificationReport(null);
      startAnalysis();
      return;
    }

    try {
      const res = await fetch(`/api/sessions/${sessionId}/inputs/text`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: `Follow-up investigation: ${question}` }),
      });

      if (res.ok) {
        setBrief(null);
        setVerificationReport(null);
        startAnalysis();
      }
    } catch (err) {
      console.error(err);
      alert("Failed to add follow-up question");
    }
  };

  const loadDemo = async () => {
    if (backendStatus !== "online") {
      setIsDemoMode(true);
      setSessionId("demo-session");
      setUploadedFiles([
        { name: "TargetCo_Pitch_Deck.pdf", id: "demo-1" },
        { name: "Whiteboard_Notes.jpg", id: "demo-2" },
      ]);
      setUploadedUrls(["https://techcrunch.com/targetco-funding"]);
      alert(
        "Backend offline. Switching to Demo Mode. 'TargetCo' scenario loaded.",
      );
      return;
    }

    try {
      const sessionRes = await fetch("/api/sessions", { method: "POST" });
      const { session_id } = await sessionRes.json();
      setSessionId(session_id);
      await fetch(`/api/sessions/${session_id}/demo`, { method: "POST" });

      setUploadedFiles([
        { name: "TargetCo_Pitch_Deck.pdf", id: "demo-1" },
        { name: "Whiteboard_Notes.jpg", id: "demo-2" },
      ]);
      setUploadedUrls(["https://techcrunch.com/targetco-funding"]);

      alert("Demo scenario 'TargetCo' loaded. Click 'Run Analysis' to start.");
    } catch (err) {
      console.error(
        "Failed to load demo scenario from backend, falling back to local demo:",
        err,
      );
      setIsDemoMode(true);
      setSessionId("demo-session");
      setUploadedFiles([
        { name: "TargetCo_Pitch_Deck.pdf", id: "demo-1" },
        { name: "Whiteboard_Notes.jpg", id: "demo-2" },
      ]);
      setUploadedUrls(["https://techcrunch.com/targetco-funding"]);
      alert(
        "Backend error. Switching to Demo Mode. 'TargetCo' scenario loaded.",
      );
    }
  };

  useEffect(() => {
    return () => closeStream();
  }, []);

  // Auto-scroll agent panels
  useEffect(() => {
    Object.keys(agentEvents).forEach((agentId) => {
      const ref = scrollRefs.current[agentId];
      if (ref) {
        ref.scrollTop = ref.scrollHeight;
      }
    });
  }, [agentEvents]);

  return (
    <div className="flex flex-col h-screen bg-slate-50 text-slate-900 font-sans overflow-hidden print:h-auto print:overflow-visible print:block">
      {/* Top Bar */}
      <header className="h-16 bg-white border-b border-slate-200 flex items-center justify-between px-8 shrink-0 z-20 print:hidden">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 bg-blue-600 rounded-lg flex items-center justify-center">
            <Zap className="text-white w-5 h-5" />
          </div>
          <div>
            <h1 className="text-xl font-bold tracking-tight">Boardroom</h1>
            <p className="text-[10px] font-bold text-slate-400 uppercase tracking-widest -mt-1">
              {uploadedFiles.length > 0
                ? "Analysis in Progress: TargetCo"
                : "M&A Due Diligence Copilot (v1.0.3)"}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-4">
          {sessionId && (
            <button
              onClick={() => window.location.reload()}
              className="text-slate-400 hover:text-slate-600 transition-colors p-2"
              title="Reset Session"
            >
              <AlertCircle className="w-5 h-5 rotate-45" />
            </button>
          )}
          {!sessionId && (
            <button
              onClick={loadDemo}
              className="text-slate-600 text-sm font-medium hover:text-slate-900 px-3 py-1.5 rounded-md transition-colors bg-slate-50 border border-slate-200"
            >
              Load Demo Scenario
            </button>
          )}
          <button
            onClick={startAnalysis}
            disabled={isAnalyzing}
            className={cn(
              "flex items-center gap-2 px-5 py-2 rounded-full text-sm font-semibold transition-all shadow-sm",
              isAnalyzing
                ? "bg-slate-100 text-slate-400 cursor-not-allowed"
                : "bg-blue-600 text-white hover:bg-blue-500 active:scale-95",
            )}
          >
            {isAnalyzing ? (
              <>
                <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                Analyzing...
              </>
            ) : (
              <>
                <Play className="w-4 h-4 fill-current" />
                Run Analysis
              </>
            )}
          </button>
        </div>
      </header>

      <div className="flex flex-1 overflow-hidden print:overflow-visible print:block">
        {/* Left Sidebar - Inputs */}
        <aside className="w-72 bg-white border-r border-slate-200 flex flex-col shrink-0 print:hidden">
          <div className="p-4 border-b border-slate-100 flex items-center justify-between">
            <h2 className="text-xs font-bold text-slate-400 uppercase tracking-wider">
              Workspace Inputs
            </h2>
            <button
              onClick={() => setShowHelp(!showHelp)}
              className="p-1 hover:bg-slate-100 rounded-full transition-colors"
              title="What to upload?"
            >
              <AlertCircle
                className={cn(
                  "w-4 h-4 transition-colors",
                  showHelp ? "text-blue-500" : "text-slate-400",
                )}
              />
            </button>
          </div>
          <div className="flex-1 overflow-y-auto p-4 space-y-6">
            {showHelp && (
              <div className="p-3 bg-blue-50 border border-blue-100 rounded-lg animate-in fade-in slide-in-from-top-2">
                <h4 className="text-[10px] font-bold text-blue-600 uppercase mb-1">
                  Upload Guide
                </h4>
                <p className="text-[10px] text-blue-800 leading-relaxed">
                  <strong>PDF/Doc:</strong> Business decks, reports, or
                  contracts. We extract text and describe charts.
                  <br />
                  <br />
                  <strong>Image:</strong> Upload whiteboard photos or sketches.
                  Gemini Vision interprets handwritten deal structures and
                  SWOTs.
                  <br />
                  <br />
                  <strong>URL:</strong> Paste news or filings. Our Researcher
                  will cross-reference them.
                </p>
              </div>
            )}
            <section>
              <h3 className="text-sm font-semibold text-slate-700 mb-3 flex items-center gap-2">
                <FileCode className="w-4 h-4 text-slate-400" />
                Documents
              </h3>
              <div className="space-y-2">
                <input
                  type="file"
                  ref={fileInputRef}
                  className="hidden"
                  accept=".pdf,.txt,.md,.docx"
                  onChange={(e) => handleFileUpload(e, "document")}
                />
                <input
                  type="file"
                  ref={imageInputRef}
                  className="hidden"
                  accept="image/*"
                  onChange={(e) => handleFileUpload(e, "image")}
                />

                <div className="grid grid-cols-2 gap-2">
                  <div
                    onClick={() => !uploadingType && fileInputRef.current?.click()}
                    className={cn(
                      "p-3 border border-dashed border-slate-200 rounded-lg bg-slate-50 flex flex-col items-center justify-center gap-2 transition-colors text-center group",
                      uploadingType === "document" ? "opacity-70 cursor-wait" : "cursor-pointer hover:bg-slate-100"
                    )}
                  >
                    {uploadingType === "document" ? (
                      <div className="w-5 h-5 border-2 border-blue-500/30 border-t-blue-500 rounded-full animate-spin" />
                    ) : (
                      <Upload className="w-5 h-5 text-slate-400 group-hover:text-blue-500 transition-colors" />
                    )}
                    <span className="text-[10px] font-medium text-slate-500">
                      {uploadingType === "document" ? "Uploading..." : "Upload Doc"}
                    </span>
                  </div>
                  <div
                    onClick={() => !uploadingType && imageInputRef.current?.click()}
                    className={cn(
                      "p-3 border border-dashed border-slate-200 rounded-lg bg-slate-50 flex flex-col items-center justify-center gap-2 transition-colors text-center group",
                      uploadingType === "image" ? "opacity-70 cursor-wait" : "cursor-pointer hover:bg-slate-100"
                    )}
                  >
                    {uploadingType === "image" ? (
                      <div className="w-5 h-5 border-2 border-blue-500/30 border-t-blue-500 rounded-full animate-spin" />
                    ) : (
                      <Upload className="w-5 h-5 text-slate-400 group-hover:text-blue-500 transition-colors" />
                    )}
                    <span className="text-[10px] font-medium text-slate-500">
                      {uploadingType === "image" ? "Uploading..." : "Upload Image"}
                    </span>
                  </div>
                </div>
                {uploadedFiles.map((file, i) => (
                  <div
                    key={file.id}
                    className="p-2 bg-blue-50 border border-blue-100 rounded-md flex items-center gap-2 group relative"
                  >
                    <CheckCircle2 className="w-4 h-4 text-blue-500 shrink-0" />
                    <span
                      className="text-xs font-medium text-blue-700 truncate pr-4"
                      title={file.name}
                    >
                      {file.name}
                    </span>
                    <button
                      onClick={() => removeFile(file.id)}
                      className="absolute right-1 top-1.5 p-0.5 text-blue-300 hover:text-rose-500 transition-colors opacity-0 group-hover:opacity-100"
                    >
                      <AlertCircle className="w-3 h-3 rotate-45" />
                    </button>
                  </div>
                ))}
              </div>
            </section>
            <section>
              <h3 className="text-sm font-semibold text-slate-700 mb-3 flex items-center gap-2">
                <LinkIcon className="w-4 h-4 text-slate-400" />
                Sources
              </h3>
              <div className="space-y-2">
                <form onSubmit={handleUrlAdd} className="relative">
                  <input
                    type="url"
                    value={urlInput}
                    onChange={(e) => setUrlInput(e.target.value)}
                    placeholder="Paste URL..."
                    className="w-full text-xs p-2 pr-8 border border-slate-200 rounded-md bg-slate-50 focus:outline-none focus:ring-1 focus:ring-blue-500"
                  />
                  <button
                    type="submit"
                    disabled={!urlInput}
                    className="absolute right-2 top-2.5"
                  >
                    <LinkIcon
                      className={cn(
                        "w-3 h-3 transition-colors",
                        urlInput ? "text-blue-500" : "text-slate-400",
                      )}
                    />
                  </button>
                </form>
                {uploadedUrls.map((url, i) => {
                  let hostname = url;
                  try {
                    hostname = new URL(url).hostname;
                  } catch {}
                  return (
                    <div
                      key={i}
                      className="p-2 bg-slate-100 rounded-md flex items-center gap-2 group relative"
                    >
                      <div className="w-4 h-4 rounded bg-white flex items-center justify-center shadow-xs shrink-0">
                        <span className="text-[8px] font-bold">
                          {hostname.substring(0, 2).toUpperCase()}
                        </span>
                      </div>
                      <span
                        className="text-xs text-slate-600 truncate pr-4"
                        title={url}
                      >
                        {hostname}
                      </span>
                      <button
                        onClick={() => removeUrl(url)}
                        className="absolute right-1 top-1.5 p-0.5 text-slate-300 hover:text-rose-500 transition-colors opacity-0 group-hover:opacity-100"
                      >
                        <AlertCircle className="w-3 h-3 rotate-45" />
                      </button>
                    </div>
                  );
                })}
              </div>
            </section>{" "}
          </div>

          <div className="p-4 border-t border-slate-100 bg-slate-50/50">
            <div className="flex items-center gap-2 mb-1">
              <div
                className={cn(
                  "w-2 h-2 rounded-full animate-pulse",
                  backendStatus === "online"
                    ? "bg-emerald-500"
                    : backendStatus === "connecting"
                      ? "bg-amber-400"
                      : "bg-rose-500",
                )}
              />
              <span className="text-[10px] font-bold text-slate-400 uppercase tracking-tight">
                System Status
              </span>
            </div>
            <p className="text-xs text-slate-500 font-medium">
              {backendStatus === "online"
                ? sessionId
                  ? `Session Active: ${sessionId.slice(0, 8)}`
                  : "Ready for new session"
                : backendStatus === "connecting"
                  ? "Checking connection..."
                  : "Backend Offline - Try Demo Mode"}
            </p>
          </div>
        </aside>

        {/* Main Content Area */}
        <main className="flex-1 flex flex-col overflow-hidden relative print:overflow-visible print:block">
          {/* Tabs / Agent View */}
          <div className="flex-1 overflow-hidden p-6 print:hidden">
            <div className="grid grid-cols-6 h-full gap-6">
              {/* Orchestrator Column - Vertical */}
              <div className="col-span-2 flex flex-col h-full">
                <AgentPanel
                  agent={AGENTS[0]}
                  events={agentEvents[AGENTS[0].id] || []}
                  allConflicts={Object.values(agentEvents)
                    .flat()
                    .filter((e) => e.content.includes("⚡ Conflict"))}
                  isAnalyzing={
                    isAnalyzing &&
                    (agentEvents[AGENTS[0].id]?.at(-1)?.type !== "status" ||
                      agentEvents[AGENTS[0].id]?.at(-1)?.content !== "done")
                  }
                  scrollRef={(el) => (scrollRefs.current[AGENTS[0].id] = el)}
                />
              </div>

              {/* Working Agents Grid */}
              <div className="col-span-4 grid grid-cols-2 gap-6 overflow-y-auto pr-2 pb-2 auto-rows-[minmax(300px,1fr)] min-h-0">
                {AGENTS.slice(1).map((agent) => (
                  <AgentPanel
                    key={agent.id}
                    agent={agent}
                    events={agentEvents[agent.id] || []}
                    allConflicts={Object.values(agentEvents)
                      .flat()
                      .filter((e) => e.content.includes("⚡ Conflict"))}
                    isAnalyzing={
                      isAnalyzing &&
                      (agentEvents[agent.id]?.at(-1)?.type !== "status" ||
                        agentEvents[agent.id]?.at(-1)?.content !== "done")
                    }
                    scrollRef={(el) => (scrollRefs.current[agent.id] = el)}
                  />
                ))}
              </div>
            </div>
          </div>

          {/* Floating Final Brief Reveal */}
          {brief && (
            <div className="absolute inset-x-6 bottom-6 top-16 bg-white shadow-2xl rounded-2xl border border-slate-200 z-30 flex flex-col animate-in slide-in-from-bottom-10 fade-in duration-700 print:relative print:inset-0 print:shadow-none print:border-none print:z-0 print:block print:h-auto">
              <div className="p-6 border-b border-slate-100 flex items-center justify-between bg-slate-50/50 rounded-t-2xl print:hidden">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 bg-amber-100 rounded-full flex items-center justify-center">
                    <FileText className="text-amber-600 w-6 h-6" />
                  </div>
                  <div>
                    <h2 className="text-xl font-bold text-slate-900">
                      Executive Briefing
                    </h2>
                    <p className="text-xs text-slate-500 font-medium tracking-wide uppercase">
                      Final Synthesized Recommendation
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => window.print()}
                    className="flex items-center gap-2 px-3 py-1.5 text-slate-600 hover:text-slate-900 hover:bg-white rounded-lg transition-all border border-transparent hover:border-slate-200 text-sm font-medium"
                  >
                    <Printer className="w-4 h-4" />
                    Print to PDF
                  </button>
                  <button
                    onClick={() => setBrief(null)}
                    className="text-slate-400 hover:text-slate-600 p-2 hover:bg-white rounded-lg transition-colors"
                  >
                    <AlertCircle className="w-6 h-6 rotate-45" />
                  </button>
                </div>
              </div>

              <div className="flex-1 overflow-y-auto p-12 print:p-0 print:overflow-visible print:block print:h-auto">
                <div className="max-w-3xl mx-auto space-y-12">
                  {/* Print-only Header */}
                  <div className="hidden print:block border-b-2 border-slate-900 pb-4 mb-8">
                    <h1 className="text-4xl font-black uppercase tracking-tighter text-slate-900">
                      Boardroom Briefing
                    </h1>
                    <p className="text-sm font-bold text-slate-500 mt-2">
                      CONFIDENTIAL EXECUTIVE REPORT •{" "}
                      {new Date().toLocaleDateString()}
                    </p>
                  </div>

                  {/* Confidence & Recommendation */}
                  <div className="flex items-start justify-between gap-8 p-8 bg-blue-50 rounded-2xl border border-blue-100 print:bg-white print:border-slate-200">
                    <div className="flex-1">
                      <span className="text-[10px] font-bold text-blue-500 uppercase tracking-widest block mb-2 print:text-slate-500">
                        Verdict
                      </span>
                      <h3 className="text-3xl font-black text-blue-900 mb-4 print:text-slate-900">
                        {brief.recommendation}
                      </h3>
                      <p className="text-blue-800/80 leading-relaxed font-medium print:text-slate-700">
                        {brief.confidence_explanation}
                      </p>
                    </div>
                    <div className="flex flex-col items-center gap-2 shrink-0">
                      <div className="w-24 h-24 rounded-full border-8 border-blue-200 flex items-center justify-center relative print:border-slate-200">
                        <div
                          className="absolute inset-0 rounded-full border-8 border-blue-600 print:border-slate-900"
                          style={{
                            clipPath: `inset(${100 - brief.confidence_score}% 0 0 0)`,
                          }}
                        />
                        <span className="text-2xl font-black text-blue-700 print:text-slate-900">
                          {brief.confidence_score}%
                        </span>
                      </div>
                      <span className="text-[10px] font-bold text-blue-400 uppercase print:text-slate-400">
                        Confidence
                      </span>
                    </div>
                  </div>

                  {/* Summary */}
                  <section>
                    <h4 className="text-sm font-bold text-slate-400 uppercase tracking-widest mb-4">
                      Strategic Summary
                    </h4>
                    <p className="text-xl text-slate-800 leading-relaxed font-serif italic">
                      &quot;{brief.one_paragraph_summary}&quot;
                    </p>
                  </section>

                  {/* Strengths & Risks */}
                  <div className="grid grid-cols-2 gap-12 print:gap-8">
                    <section>
                      <h4 className="text-sm font-bold text-emerald-600 uppercase tracking-widest mb-6 flex items-center gap-2 print:text-slate-900">
                        <CheckCircle2 className="w-4 h-4" /> Key Strengths
                      </h4>
                      <ul className="space-y-4">
                        {brief.key_strengths.map((s, i) => (
                          <li key={i} className="flex gap-3">
                            <div className="w-1.5 h-1.5 rounded-full bg-emerald-500 mt-2 shrink-0 print:bg-slate-900" />
                            <div>
                              <p className="text-sm text-slate-800 font-medium leading-snug">
                                {s.point}
                              </p>
                              <p className="text-[10px] text-slate-400 font-mono mt-1">
                                Ref: {s.source_citation}
                              </p>
                            </div>
                          </li>
                        ))}
                      </ul>
                    </section>
                    <section>
                      <h4 className="text-sm font-bold text-rose-600 uppercase tracking-widest mb-6 flex items-center gap-2 print:text-slate-900">
                        <ShieldAlert className="w-4 h-4" /> Critical Risks
                      </h4>
                      <ul className="space-y-4">
                        {brief.key_risks.map((r, i) => (
                          <li key={i} className="flex gap-3">
                            <div
                              className={cn(
                                "w-1.5 h-1.5 rounded-full mt-2 shrink-0",
                                r.severity === "high"
                                  ? "bg-rose-600"
                                  : "bg-amber-500",
                              )}
                            />
                            <div>
                              <p className="text-sm text-slate-800 font-medium leading-snug">
                                {r.point}
                              </p>
                              <div className="flex items-center gap-2 mt-1">
                                <span
                                  className={cn(
                                    "text-[9px] px-1.5 py-0.5 rounded font-bold uppercase",
                                    r.severity === "high"
                                      ? "bg-rose-100 text-rose-600"
                                      : "bg-amber-100 text-amber-600",
                                  )}
                                >
                                  {r.severity}
                                </span>
                                <p className="text-[10px] text-slate-400 font-mono">
                                  Ref: {r.source_citation}
                                </p>
                              </div>
                            </div>
                          </li>
                        ))}
                      </ul>
                    </section>
                  </div>

                  {/* Dissenting Views */}
                  <section className="p-8 bg-slate-50 rounded-2xl border border-slate-200 print:bg-white">
                    <h4 className="text-sm font-bold text-slate-500 uppercase tracking-widest mb-4">
                      Adversarial Perspective (Red Team)
                    </h4>
                    <div className="space-y-4">
                      {brief.dissenting_views.map((d, i) => (
                        <p
                          key={i}
                          className="text-sm text-slate-600 font-medium leading-relaxed italic border-l-2 border-slate-300 pl-4"
                        >
                          {d}
                        </p>
                      ))}
                    </div>
                  </section>

                  {/* Verification Report */}
                  {verificationReport && (
                    <section className="p-8 bg-teal-50/50 rounded-2xl border border-teal-100 print:bg-white print:border-slate-200">
                      <div className="flex items-center justify-between mb-4">
                        <h4 className="text-sm font-bold text-teal-700 uppercase tracking-widest flex items-center gap-2">
                          <CheckCircle2 className="w-5 h-5" />
                          Verification Report
                        </h4>
                        <div className="flex items-center gap-2">
                          <span className="text-xs font-bold text-teal-600 uppercase tracking-widest">
                            Integrity Score
                          </span>
                          <span
                            className={cn(
                              "px-2 py-1 rounded-md text-sm font-black",
                              verificationReport.integrity_score > 80
                                ? "bg-teal-100 text-teal-700"
                                : verificationReport.integrity_score > 60
                                  ? "bg-amber-100 text-amber-700"
                                  : "bg-rose-100 text-rose-700",
                            )}
                          >
                            {verificationReport.integrity_score}/100
                          </span>
                        </div>
                      </div>

                      <div className="flex flex-wrap gap-2 mb-6 text-[10px] font-bold uppercase tracking-wide">
                        <span className="px-2 py-1 rounded-full bg-slate-100 text-slate-500">
                          {verificationReport.total_claims_checked} claims checked
                        </span>
                        {!!verificationReport.verified_count && (
                          <span className="px-2 py-1 rounded-full bg-teal-100 text-teal-700">
                            {verificationReport.verified_count} verified
                          </span>
                        )}
                        {!!verificationReport.plausible_count && (
                          <span className="px-2 py-1 rounded-full bg-amber-100 text-amber-700">
                            {verificationReport.plausible_count} plausible
                          </span>
                        )}
                        {!!verificationReport.flagged_count && (
                          <span className="px-2 py-1 rounded-full bg-rose-100 text-rose-700">
                            {verificationReport.flagged_count} flagged for review
                          </span>
                        )}
                        {!!verificationReport.hallucination_count && (
                          <span className="px-2 py-1 rounded-full bg-rose-200 text-rose-800">
                            {verificationReport.hallucination_count} possible hallucination
                            {verificationReport.hallucination_count === 1 ? "" : "s"}
                          </span>
                        )}
                      </div>

                      {verificationReport.note && (
                        <p className="text-xs text-slate-500 italic mb-4">
                          {verificationReport.note}
                        </p>
                      )}

                      <div className="space-y-4">
                        {verificationReport.claims.map((claim, i) => (
                          <div
                            key={i}
                            className="bg-white p-4 rounded-xl border border-teal-50 shadow-sm flex flex-col gap-2 print:border-slate-200"
                          >
                            <div className="flex items-start justify-between gap-4">
                              <p className="text-sm text-slate-700 font-medium">
                                {claim.claim}
                                <span className="ml-2 text-[10px] font-bold uppercase text-slate-300">
                                  {claim.type}
                                </span>
                              </p>
                              <span
                                className={cn(
                                  "text-[10px] uppercase font-bold px-2 py-1 rounded-full whitespace-nowrap shrink-0",
                                  claimStatusClasses(claim.status),
                                )}
                              >
                                {claim.status} ({claim.score}%)
                              </span>
                            </div>
                            {claim.reasoning && claim.status !== "VERIFIED" && (
                              <p className="text-xs text-slate-500">
                                {claim.reasoning}
                              </p>
                            )}
                            {claim.status !== "VERIFIED" &&
                              claim.best_source_snippet !== "None" && (
                                <div className="mt-1 text-xs text-slate-500 bg-slate-50 p-2 rounded border border-slate-100">
                                  <span className="font-bold text-slate-400 block mb-1">
                                    Closest Source Match:
                                  </span>
                                  <p className="italic">
                                    "{claim.best_source_snippet}"
                                  </p>
                                </div>
                              )}
                          </div>
                        ))}
                      </div>
                    </section>
                  )}
                  {/* Follow-ups */}
                  <section className="print:hidden">
                    <h4 className="text-sm font-bold text-blue-600 uppercase tracking-widest mb-6">
                      Strategic Next Steps
                    </h4>
                    <div className="grid grid-cols-3 gap-4">
                      {brief.follow_up_questions.map((q, i) => (
                        <div
                          key={i}
                          onClick={() => handleFollowUp(q)}
                          className="p-4 bg-white border border-slate-200 rounded-xl hover:border-blue-400 transition-colors cursor-pointer group"
                        >
                          <p className="text-xs text-slate-700 font-semibold group-hover:text-blue-600 transition-colors">
                            {q}
                          </p>
                          <div className="mt-4 flex items-center gap-1 text-[9px] font-bold text-blue-500 uppercase tracking-tighter">
                            Add to analysis{" "}
                            <Play className="w-2 h-2 fill-current" />
                          </div>
                        </div>
                      ))}
                    </div>
                  </section>
                </div>
              </div>
            </div>
          )}
        </main>
      </div>
    </div>
  );
}

function playCompleteSound() {
  try {
    const audioCtx = new (
      window.AudioContext || (window as any).webkitAudioContext
    )();
    const oscillator = audioCtx.createOscillator();
    const gainNode = audioCtx.createGain();

    oscillator.type = "sine";
    oscillator.frequency.setValueAtTime(440, audioCtx.currentTime); // A4
    oscillator.frequency.exponentialRampToValueAtTime(
      880,
      audioCtx.currentTime + 0.1,
    ); // A5

    gainNode.gain.setValueAtTime(0.1, audioCtx.currentTime);
    gainNode.gain.exponentialRampToValueAtTime(
      0.01,
      audioCtx.currentTime + 0.3,
    );

    oscillator.connect(gainNode);
    gainNode.connect(audioCtx.destination);

    oscillator.start();
    oscillator.stop(audioCtx.currentTime + 0.3);
  } catch (e) {
    console.warn("Sound play failed", e);
  }
}

function AgentPanel({
  agent,
  events,
  allConflicts,
  isAnalyzing,
  scrollRef,
}: {
  agent: (typeof AGENTS)[0];
  events: AgentEvent[];
  allConflicts: AgentEvent[];
  isAnalyzing: boolean;
  scrollRef: (el: HTMLDivElement | null) => void;
}) {
  const Icon = agent.icon;
  const status =
    events.length === 0 ? "idle" : isAnalyzing ? "working" : "done";

  // Group events
  const toolCalls = events.filter(
    (e) =>
      e.content.startsWith("Searching for:") || e.content.startsWith("Parsed:"),
  );
  const conflicts = events.filter((e) =>
    e.content.includes("⚡ Conflict detected"),
  );
  const relevantConflicts = allConflicts.filter(
    (c) => c.content.includes(agent.name) || c.agent === agent.id,
  );
  const regularEvents = events.filter(
    (e) =>
      !e.content.startsWith("Searching for:") &&
      !e.content.startsWith("Parsed:") &&
      !e.content.includes("⚡ Conflict detected"),
  );

  // Extract findings (lines starting with bullet points or numbers)
  const findings = events
    .filter((e) => e.type === "thought")
    .map((e) => e.content)
    .join("")
    .split("\n")
    .filter((line) => line.trim().match(/^[-*•\d+.]/))
    .map((line) => line.trim().replace(/^[-*•\d+.]\s*/, ""))
    .filter((line) => line.length > 10)
    .slice(-3); // Just show the last 3 findings to keep it clean

  const prevStatusRef = useRef(status);
  useEffect(() => {
    if (prevStatusRef.current === "working" && status === "done") {
      playCompleteSound();
    }
    prevStatusRef.current = status;
  }, [status]);

  return (
    <div
      className={cn(
        "bg-white rounded-2xl shadow-sm border border-slate-200 overflow-hidden flex flex-col h-full transition-all duration-500",
        status === "working" && "ring-2 ring-blue-100 animate-breathe",
        status === "done" && "shadow-md",
      )}
    >
      <div className="px-5 py-3 border-b border-slate-100 flex items-center justify-between bg-slate-50/50">
        <div className="flex items-center gap-3">
          <div className={cn("p-1.5 rounded-lg", agent.bg)}>
            <Icon className={cn("w-4 h-4", agent.color)} />
          </div>
          <span className="font-bold text-slate-700 text-sm tracking-tight">
            {agent.name}
          </span>
        </div>
        <div className="flex items-center gap-2">
          {status === "working" && (
            <div className="flex gap-0.5">
              <div className="w-1 h-1 bg-blue-500 rounded-full animate-bounce [animation-delay:-0.3s]" />
              <div className="w-1 h-1 bg-blue-500 rounded-full animate-bounce [animation-delay:-0.15s]" />
              <div className="w-1 h-1 bg-blue-500 rounded-full animate-bounce" />
            </div>
          )}
          <span
            className={cn(
              "text-[9px] font-black uppercase tracking-widest px-1.5 py-0.5 rounded",
              status === "idle" && "text-slate-400",
              status === "working" && "text-blue-600 bg-blue-50",
              status === "done" && "text-emerald-600 bg-emerald-50",
            )}
          >
            {status}
          </span>
        </div>
      </div>

      <div
        ref={scrollRef}
        className="flex-1 p-5 overflow-y-auto space-y-4 font-mono text-[11px] leading-relaxed text-slate-600 scroll-smooth"
      >
        {events.length === 0 && !isAnalyzing && (
          <div className="flex flex-col items-center justify-center h-full opacity-20 grayscale">
            <Icon className="w-12 h-12 mb-2" />
            <p className="font-sans font-semibold italic">
              Awaiting instructions...
            </p>
          </div>
        )}

        {/* Conflicts - High priority */}
        {relevantConflicts.length > 0 && (
          <div className="space-y-2">
            {relevantConflicts.map((c, i) => (
              <div
                key={i}
                className="p-3 bg-rose-50 border border-rose-100 rounded-lg text-rose-700 animate-in zoom-in-95 duration-300 ring-2 ring-rose-200 ring-offset-2"
              >
                <div className="flex items-center gap-2 mb-1">
                  <ShieldAlert className="w-3 h-3" />
                  <span className="font-bold uppercase tracking-tighter text-[9px]">
                    Conflict Detected
                  </span>
                </div>
                <p className="font-sans font-medium text-xs">
                  {c.content.replace("⚡ Conflict detected: ", "")}
                </p>
              </div>
            ))}
          </div>
        )}

        {/* Tool Calls */}
        {toolCalls.length > 0 && (
          <div className="space-y-1 opacity-80">
            <div className="flex items-center gap-2 text-[9px] font-bold text-slate-400 uppercase tracking-widest mb-1">
              <Settings className="w-3 h-3" /> Tool Invocations
            </div>
            {toolCalls.map((tc, i) => (
              <div
                key={i}
                className="bg-slate-50 border border-slate-100 p-2 rounded flex items-center gap-2 overflow-hidden"
              >
                <div className="w-1.5 h-1.5 rounded-full bg-blue-400 shrink-0" />
                <span className="truncate">{tc.content}</span>
              </div>
            ))}
          </div>
        )}

        {/* Main Event Stream */}
        <div className="space-y-3">
          {regularEvents.map((e, i) => (
            <div
              key={i}
              className={cn(
                "animate-in fade-in slide-in-from-left-2 duration-300",
                e.type === "thought" && "pl-3 border-l-2 border-slate-100",
                e.type === "status" && "text-slate-400 italic",
                e.type === "error" &&
                  "text-rose-500 bg-rose-50 p-2 rounded border border-rose-100",
              )}
            >
              {e.type === "status" ? `> System: Agent ${e.content}` : e.content}
            </div>
          ))}
        </div>

        {status === "working" && (
          <div className="w-1.5 h-4 bg-blue-500 animate-pulse inline-block align-middle ml-1" />
        )}

        {/* Key Findings Section */}
        {status === "done" && findings.length > 0 && (
          <div className="mt-4 pt-4 border-t border-slate-100 animate-in slide-in-from-bottom-2 duration-500">
            <div className="flex items-center gap-2 text-[9px] font-bold text-slate-400 uppercase tracking-widest mb-2">
              <CheckCircle2 className="w-3 h-3 text-emerald-500" /> Key Findings
            </div>
            <ul className="space-y-2">
              {findings.map((f, i) => (
                <li
                  key={i}
                  className="font-sans text-[10px] font-medium text-slate-700 flex gap-2"
                >
                  <span className="text-emerald-500">•</span>
                  {f}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}
