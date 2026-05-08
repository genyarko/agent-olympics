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
  { agent: "orchestrator", type: "status", content: "done" }
];
