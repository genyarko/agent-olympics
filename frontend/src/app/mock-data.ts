export const MOCK_EVENTS = [
  { agent: "orchestrator", type: "status", content: "starting" },
  { agent: "orchestrator", type: "thought", content: "Parsing inputs and extracting key facts..." },
  { agent: "orchestrator", type: "thought", content: "Extracted facts: TargetCo is a Series C SaaS company specializing in AI-driven supply chain optimization. Current ARR is $50M, growing at 40% YoY..." },
  { agent: "orchestrator", type: "thought", content: "Defining execution plan for specialized agents..." },
  { agent: "orchestrator", type: "thought", content: "Launching Researcher and Analyst agents in parallel." },
  { agent: "researcher", type: "thought", content: "Searching for: TargetCo recent news and funding..." },
  { agent: "researcher", type: "thought", content: "Searching for: TargetCo competitors LogiSmart and SupplyChainAI..." },
  { agent: "analyst", type: "thought", content: "Analyzing business model and unit economics..." },
  { agent: "researcher", type: "thought", content: "Findings: TargetCo recently expanded into the European market. Customer reviews indicate high satisfaction but slow onboarding." },
  { agent: "analyst", type: "thought", content: "Findings: \n- Gross margins are healthy at 78%.\n- CAC Payback period is 14 months, which is slightly above industry average." },
  { agent: "researcher", type: "status", content: "done" },
  { agent: "analyst", type: "thought", content: "Findings: \n- High customer concentration: Top 3 customers represent 45% of total revenue." },
  { agent: "analyst", type: "status", content: "done" },
  { agent: "orchestrator", type: "thought", content: "Research and initial analysis complete. Launching Red Team for adversarial critique." },
  { agent: "red_team", type: "thought", content: "Identifying key risks and challenging assumptions..." },
  { agent: "red_team", type: "thought", content: "Findings: \n- Customer concentration is a major red flag. Loss of one major customer could jeopardize the earn-out targets.\n- The AI optimization market is becoming saturated." },
  { agent: "red_team", type: "status", content: "done" },
  { agent: "orchestrator", type: "thought", content: "Checking for conflicts between Analyst findings and Red Team critique..." },
  { agent: "orchestrator", type: "thought", content: "⚡ Conflict detected: Analyst found strong growth; Red Team flagged high customer concentration risk." },
  { agent: "orchestrator", type: "thought", content: "All analyses complete. Synthesizing final board-ready brief." },
  {
    agent: "synthesizer",
    type: "brief",
    content: JSON.stringify({
      recommendation: "Proceed with conditions",
      confidence_score: 72,
      confidence_explanation: "Strong unit economics and growth are offset by significant customer concentration risk.",
      one_paragraph_summary: "TargetCo represents a strategically sound acquisition for our supply chain portfolio. However, the high reliance on three major customers requires a restructured earn-out and a dedicated retention plan.",
      key_strengths: [
        { point: "78% gross margins indicate strong product-market fit.", source_citation: "Analyst Report" },
        { point: "40% YoY growth in a competitive market.", source_citation: "TargetCo Pitch Deck" }
      ],
      key_risks: [
        { point: "Top 3 customers account for 45% of revenue.", severity: "High", source_citation: "Red Team Critique" },
        { point: "Saturation in the AI optimization space.", severity: "Medium", source_citation: "Market Analysis" }
      ],
      follow_up_questions: [
        "What is the contract duration for the top 3 customers?",
        "Can we accelerate the European market expansion?",
        "How much overlap is there with our existing customer base?"
      ],
      dissenting_views: [
        "Red Team argues that the market saturation makes the 40% growth unsustainable."
      ]
    })
  },
  { agent: "orchestrator", type: "thought", content: "Final brief synthesized. Launching Verifier for integrity and grounding checks." },
  { agent: "verifier", type: "status", content: "starting" },
  { agent: "verifier", type: "thought", content: "Extracting claims for verification..." },
  { agent: "verifier", type: "thought", content: "Extracted 6 claims. Grounding against 14 source passages…" },
  { agent: "verifier", type: "thought", content: "Running semantic grounding on 3 claim(s)…" },
  { agent: "verifier", type: "thought", content: "Checking internal and source consistency…" },
  { agent: "verifier", type: "thought", content: "Verification complete. Integrity Score: 88/100 — 0 claim(s) flagged for human review (0 possible hallucination(s))." },
  {
    agent: "verifier",
    type: "verification_report",
    content: JSON.stringify({
      integrity_score: 88,
      total_claims_checked: 6,
      verified_count: 5,
      plausible_count: 1,
      flagged_count: 0,
      hallucination_count: 0,
      claims: [
        { claim: "TargetCo's ARR is $50M.", type: "QUANTITATIVE", role: "analyst-claim", score: 96, match_confidence: 96, verification_channel: "source-grounding", integrity_score: 92, status: "VERIFIED", consistency: "CONSISTENT", reasoning: "Direct textual match against source.", best_source_snippet: "Current ARR is $50M, growing at 40% YoY.", snippet_label: "Closest Source Match" },
        { claim: "Gross margins are 78%.", type: "QUANTITATIVE", role: "analyst-claim", score: 91, match_confidence: 91, verification_channel: "source-grounding", integrity_score: 90, status: "VERIFIED", consistency: "CONSISTENT", reasoning: "Semantic grounding verdict: FULL.", best_source_snippet: "Gross margins are healthy at 78%.", snippet_label: "Closest Source Match" },
        { claim: "Main competitors are LogiSmart and SupplyChainAI.", type: "FACTUAL", role: "analyst-claim", score: 94, match_confidence: 94, verification_channel: "source-grounding", integrity_score: 91, status: "VERIFIED", consistency: "CONSISTENT", reasoning: "Direct textual match against source.", best_source_snippet: "Main competitors are LogiSmart and SupplyChainAI.", snippet_label: "Closest Source Match" },
        { claim: "Top 3 customers account for 45% of revenue.", type: "QUANTITATIVE", role: "red-team-rebuttal", score: 91, match_confidence: 91, verification_channel: "knowledge-check", knowledge_support: "SUPPORTED", integrity_score: 88, status: "VERIFIED", consistency: "CONSISTENT", reasoning: "Supported by external knowledge: research notes confirm heavy top-customer concentration in this segment.", best_source_snippet: "Top customer accounts for ~28% of ARR.", snippet_label: "Contradicted source phrase" },
        { claim: "Deal structure is $200M cash plus $100M stock with a 3-year earn-out.", type: "FACTUAL", role: "analyst-claim", score: 84, match_confidence: 84, verification_channel: "source-grounding", integrity_score: 80, status: "PLAUSIBLE", consistency: "CONSISTENT", reasoning: "Semantic grounding verdict: PARTIAL.", best_source_snippet: "Deal structure is $200M cash + $100M stock. Earn-out over 3 years based on EBITDA targets.", snippet_label: "Closest Source Match" },
        { claim: "Q1 2025 customer-data exposure event raises diligence risk.", type: "FACTUAL", role: "external-context", score: 92, match_confidence: 92, verification_channel: "knowledge-check", knowledge_support: "SUPPORTED", integrity_score: 89, status: "VERIFIED", consistency: "CONSISTENT", reasoning: "Supported by external reporting; not present in the pitch deck.", best_source_snippet: "TargetCo disclosed a customer data exposure event in Q1 2025.", snippet_label: "Closest Source Match" }
      ]
    })
  },
  { agent: "verifier", type: "status", content: "done" },
  { agent: "orchestrator", type: "status", content: "done" }
];
