"use client";

import { useEffect, useRef, useState } from "react";

type AgentEvent = {
  agent: string;
  type: string;
  content: string;
};

export default function Home() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const eventSourceRef = useRef<EventSource | null>(null);

  const closeStream = () => {
    eventSourceRef.current?.close();
    eventSourceRef.current = null;
  };

  const startAnalysis = async () => {
    if (isAnalyzing) return;

    closeStream();
    setEvents([]);
    setIsAnalyzing(true);

    const sessionRes = await fetch("/api/sessions", { method: "POST" });
    if (!sessionRes.ok) {
      setIsAnalyzing(false);
      return;
    }
    const { session_id } = await sessionRes.json();
    setSessionId(session_id);

    const es = new EventSource(`/api/sessions/${session_id}/stream`);
    eventSourceRef.current = es;

    es.onmessage = (event) => {
      const data: AgentEvent = JSON.parse(event.data);
      setEvents((prev) => [...prev, data]);

      if (data.type === "status" && data.content === "done") {
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

    await fetch(`/api/sessions/${session_id}/analyze`, { method: "POST" });
  };

  useEffect(() => {
    return () => {
      closeStream();
    };
  }, []);

  return (
    <main className="flex min-h-screen flex-col items-center p-24 bg-slate-50 font-sans">
      <div className="z-10 w-full max-w-5xl items-center justify-between font-mono text-sm lg:flex">
        <h1 className="text-4xl font-bold mb-8 text-slate-900">Boardroom</h1>
      </div>

      <div className="flex gap-4 mb-8">
        <button
          onClick={startAnalysis}
          disabled={isAnalyzing}
          className="bg-blue-600 text-white px-6 py-2 rounded-lg hover:bg-blue-500 disabled:opacity-50 transition-colors"
        >
          {isAnalyzing ? "Analyzing..." : "Analyze TargetCo"}
        </button>
      </div>

      {sessionId && (
        <div className="w-full max-w-4xl">
          <div className="bg-white rounded-xl shadow-sm border border-slate-200 overflow-hidden">
            <div className="border-b border-slate-200 px-6 py-4 bg-slate-50 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <div
                  className={`w-3 h-3 rounded-full ${
                    isAnalyzing ? "bg-blue-500 animate-pulse" : "bg-slate-300"
                  }`}
                />
                <span className="font-semibold text-slate-700">Analyst Agent</span>
              </div>
              <span className="text-xs text-slate-400 font-mono">Session: {sessionId}</span>
            </div>

            <div className="p-6 h-[500px] overflow-y-auto font-serif text-lg leading-relaxed text-slate-800">
              {events.length === 0 && !isAnalyzing && (
                <p className="text-slate-400 italic">No analysis data yet. Click &quot;Analyze TargetCo&quot; to begin.</p>
              )}
              {events
                .filter((e) => e.agent === "analyst" && e.type === "thought")
                .map((e, i) => (
                  <span key={i} className="animate-in fade-in duration-500">
                    {e.content}
                  </span>
                ))}
              {isAnalyzing && (
                <span className="inline-block w-1.5 h-5 bg-blue-500 ml-1 animate-pulse align-middle" />
              )}
            </div>
          </div>
        </div>
      )}
    </main>
  );
}
