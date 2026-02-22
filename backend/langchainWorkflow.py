"""
Multi-Agent Orchestration System using LangChain + LangGraph + Google Gemini.

Architecture:
  Orchestrator (main chatbot)
    ├── Research Agent   — news lookup, general web research
    └── Quant Agent      — quantitative metrics, fraud scores

Each sub-agent can be extended with custom tools below.
"""

import os
import json
import requests
import operator
from typing import Annotated, TypedDict, Sequence, Literal
from dotenv import load_dotenv

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.graph import StateGraph, END, START
from langgraph.prebuilt import ToolNode

# ── Helpers ──────────────────────────────────────────────────────────────────

def extract_text(content) -> str:
    """Extract plain text from Gemini message content.
    
    Gemini can return content as a plain string OR as a list of structured
    blocks like [{'type': 'text', 'text': '...', 'extras': {...}}].
    This normalises both forms to a simple string.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and "text" in block:
                parts.append(block["text"])
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(parts)
    return str(content) if content else ""

# ── Environment ──────────────────────────────────────────────────────────────
load_dotenv()
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
YAHOO_API_KEY = os.getenv("YAHOO_API_KEY")

if not GOOGLE_API_KEY:
    raise EnvironmentError("GOOGLE_API_KEY not found. Set it in the .env file.")

# ── LLM factory ──────────────────────────────────────────────────────────────

def get_llm(temperature: float = 0.0):
    """Return a Gemini chat model instance."""
    return ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        temperature=temperature,
        google_api_key=GOOGLE_API_KEY,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# TOOLS  –  Add your custom tools in the appropriate section below.
# Each tool is a plain function decorated with @tool.
# ═══════════════════════════════════════════════════════════════════════════════

# ── Research Agent Tools ─────────────────────────────────────────────────────

@tool
def yahoo_news(ticker: str) -> list[str]:
    """
    A function that retrieves Yahoo News headlines about a specific company, indicated by its stock ticker, ready for sentiment analysis.

    Args:
        ticker (str): A stock ticker associated with the company that you are looking for Yahoo News headlines for.

    Returns:
        list: A list of news headlines from Yahoo News involving the company associated with the provided stock ticker, ready for sentiment analysis.
    """

    url = f"https://yahoo-finance15.p.rapidapi.com/api/v1/markets/news?ticker={ticker}&type=ALL"

    querystring = {
        "ticker": ticker
    }
    
    headers = {
        "X-RapidAPI-Key": YAHOO_API_KEY,
        "X-RapidAPI-Host": "yahoo-finance15.p.rapidapi.com"
    }

    response = requests.get(url, headers=headers, params=querystring)
    data = response.json()

    articles = []
    headlines = []

    for content in data.get("body", {}):
        articles.append({
            "guid": content.get("guid"),
            "link": content.get("link"),
            "pubDate": content.get("pubDate"),
            "source": content.get("source"),
            "title": content.get("title"),
        })

        headlines.append(content.get("title"))

    return headlines




# ── Quant Agent Tools ────────────────────────────────────────────────────────

@tool
def compute_fraud_scores(ticker: str) -> str:
    """Compute Beneish M-Score, Altman Z-Score, and accruals ratio for a
    company to assess manipulation / financial-distress risk."""
    # TODO: Wire up to quant_metrics.py calculations
    return f"[placeholder] Fraud scores for '{ticker}' not computed yet. Implement the quant tool."


# Add more quant tools here …


# ═══════════════════════════════════════════════════════════════════════════════
# AGENT  STATE
# ═══════════════════════════════════════════════════════════════════════════════

MAX_DELEGATIONS = 10  # Safety cap to prevent infinite delegation loops (raised for multi-ticker)
MAX_TOOL_ITERATIONS = 8  # Safety cap for sub-agent tool-calling loops per invocation

class AgentState(TypedDict):
    """Shared state flowing through the graph."""
    messages: Annotated[Sequence[BaseMessage], operator.add]
    delegation_count: Annotated[int, lambda a, b: a + b]  # tracks number of delegations
    tool_iterations: Annotated[int, lambda a, b: a + b]   # tracks tool calls within a sub-agent


# ═══════════════════════════════════════════════════════════════════════════════
# SUB-AGENT  BUILDERS
# ═══════════════════════════════════════════════════════════════════════════════

def _build_sub_agent(
    name: str,
    system_prompt: str,
    tools: list,
) -> StateGraph:
    """Build a sub-agent graph (LLM node + tool-calling loop).

    The returned *compiled* graph can be invoked as a node inside the
    orchestrator graph.
    """
    llm = get_llm().bind_tools(tools)
    tool_node = ToolNode(tools)

    def agent_node(state: AgentState):
        # Prepend the system prompt so the sub-agent stays in character.
        iterations = state.get("tool_iterations", 0)
        print(f"  [sub-agent:{name}] Gemini call (tool iteration {iterations}/{MAX_TOOL_ITERATIONS})")
        messages = [SystemMessage(content=system_prompt)] + list(state["messages"])
        response = llm.invoke(messages)
        return {"messages": [response]}

    def should_continue(state: AgentState) -> Literal["tools", "done"]:
        last = state["messages"][-1]
        # Safety cap: stop tool-calling if we've hit the iteration limit.
        iterations = state.get("tool_iterations", 0)
        if iterations >= MAX_TOOL_ITERATIONS:
            print(f"  [sub-agent:{name}] Tool iteration cap reached ({MAX_TOOL_ITERATIONS}). Stopping tool loop.")
            return "done"
        if hasattr(last, "tool_calls") and last.tool_calls:
            print(f"  [sub-agent:{name}] Tool call requested -> running tools")
            return "tools"
        return "done"

    def tool_node_with_counter(state: AgentState):
        """Wrap the tool node to increment the iteration counter."""
        result = tool_node.invoke(state)
        result["tool_iterations"] = 1
        return result

    graph = StateGraph(AgentState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tool_node_with_counter)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", should_continue, {"tools": "tools", "done": END})
    graph.add_edge("tools", "agent")

    return graph.compile()


# ── Instantiate sub-agents ───────────────────────────────────────────────────

research_tools = [yahoo_news]
quant_tools    = [compute_fraud_scores]

sentiment_research_agent = _build_sub_agent(
    name="SentimentResearchAgent",
    system_prompt=(
        "You are a sentiment analysis agent. Your ONLY source of information "
        "is the tools provided to you. You must ALWAYS call your tools — never "
        "answer from your own knowledge and never ask clarifying questions.\n\n"
        "The user may provide one or MULTIPLE company names or tickers. You must "
        "call the tool ONCE PER TICKER. If the user provides company names, infer "
        "the ticker yourself (e.g. Nvidia → NVDA, Apple → AAPL, Tesla → TSLA).\n\n"
        "After receiving ALL tool results, provide a DETAILED analysis PER COMPANY:\n"
        "For each company:\n"
        "  a) List every headline returned by the tool for that company.\n"
        "  b) For each headline, classify its sentiment as Positive, Negative, or "
        "     Neutral and briefly explain why (1 sentence).\n"
        "  c) Tally the counts: how many Positive, Negative, Neutral.\n"
        "  d) Identify the dominant themes across the headlines.\n"
        "  e) Give an overall sentiment verdict (Strongly Positive, Positive, Mixed, "
        "     Negative, Strongly Negative) with a short justification.\n\n"
        "ABSOLUTE RULES:\n"
        "- Your response must contain ZERO information not returned by the tools.\n"
        "- Do NOT add background, context, history, or general knowledge.\n"
        "- Do NOT describe what a company does or its market position.\n"
        "- If a tool returns no data for a ticker, state exactly: "
        "  'No headlines were returned for [TICKER].'\n"
        "- Every claim must trace directly to a specific headline from the tool output."
    ),
    tools=research_tools,
)

quant_agent = _build_sub_agent(
    name="QuantAgent",
    system_prompt=(
        "You are a quantitative finance analyst specialising in fraud "
        "detection metrics. Use the tools available to compute and interpret "
        "Beneish M-Score, Altman Z-Score, accruals ratios, and other "
        "quantitative indicators.\n\n"
        "The user may provide one or MULTIPLE tickers. You must call the tool "
        "ONCE PER TICKER.\n\n"
        "ABSOLUTE RULES:\n"
        "- Your response must contain ZERO information not returned by the tools.\n"
        "- Do NOT add background, context, history, or general knowledge.\n"
        "- If a tool returns no data or a placeholder, report that exactly as-is.\n"
        "- Every number, score, or claim must come directly from the tool output."
    ),
    tools=quant_tools,
)


# ═══════════════════════════════════════════════════════════════════════════════
# ORCHESTRATOR  GRAPH
# ═══════════════════════════════════════════════════════════════════════════════

ORCHESTRATOR_SYSTEM_PROMPT = """\
You are the Orchestrator — a financial-analysis system that produces formal reports.

Your job is to understand the user's request and delegate work to the
appropriate specialist sub-agent. You have two sub-agents:

1. **sentiment research** – for news headlines and sentiment analysis about companies.
2. **quant**              – for quantitative fraud-detection scores and financial metrics.

The user will provide one or MORE stock tickers and/or company names.
You MUST delegate to every relevant sub-agent to gather data for ALL
requested companies. NEVER answer from your own knowledge — always delegate.

You may delegate MULTIPLE times. For example, delegate to
sentiment_research first (it will handle all tickers at once), then to
quant after you receive the first result.

To delegate, reply with EXACTLY one delegation token on its own line:
  DELEGATE:sentiment_research
  DELEGATE:quant

When you have received all the sub-agent results you need, write your final
response as a FORMAL REPORT (without any DELEGATE token).

FORMAL REPORT FORMAT:
- Title: "Financial Analysis Report" (list all companies/tickers covered).
- Date: Include today's date.
- If multiple companies: organise the report with a top-level section per
  company, each containing the relevant sub-sections.
- Numbered sub-headings per company:
    1. News Sentiment Analysis
    2. Quantitative Risk Metrics
  Omit sub-sections for which no sub-agent data exists.
- After all per-company sections, include:
    - Comparative Summary (if multiple companies): side-by-side comparison.
    - Conclusion & Outlook: clear, actionable bottom-line assessment.
- Use markdown formatting throughout.

ABSOLUTE DATA-INTEGRITY RULES (NEVER VIOLATE THESE):
- The report must contain ONLY information explicitly present in the
  sub-agent responses. Treat sub-agent responses as your sole database.
- Do NOT add ANY background information, company descriptions, market
  context, historical facts, or general knowledge.
- Do NOT describe what a company does, its industry position, or its
  products unless a sub-agent headline explicitly states it.
- Do NOT infer, extrapolate, speculate, or editorialize beyond the data.
- Do NOT fabricate or assume sources. Only reference sources that
  sub-agents explicitly named.
- Every sentence in the report must be directly traceable to specific
  sub-agent output. If you cannot point to the exact sub-agent data that
  supports a sentence, DELETE that sentence.
- If a sub-agent returned no useful data, state exactly:
  "No data was returned by the [agent name] for [TICKER]."
"""


def orchestrator_node(state: AgentState):
    """Main orchestrator LLM call."""
    count = state.get("delegation_count", 0)
    print(f"[orchestrator] Gemini call (delegations so far: {count}/{MAX_DELEGATIONS})")
    llm = get_llm()
    messages = [SystemMessage(content=ORCHESTRATOR_SYSTEM_PROMPT)] + list(state["messages"])
    response = llm.invoke(messages)
    return {"messages": [response]}


def _run_sub_agent(agent, state: AgentState) -> dict:
    """Run a compiled sub-agent graph and return its final AI message."""
    result = agent.invoke({"messages": list(state["messages"]), "tool_iterations": 0})
    # Grab only the last AI message produced by the sub-agent.
    sub_messages = result["messages"]
    final_ai = [m for m in sub_messages if isinstance(m, AIMessage)]
    if final_ai:
        content = extract_text(final_ai[-1].content)
        reply = AIMessage(content=content, name="sub_agent")
    else:
        reply = AIMessage(content="Sub-agent produced no response.", name="sub_agent")
    return {"messages": [reply]}


def sentiment_research_node(state: AgentState):
    count = state.get("delegation_count", 0) + 1
    print(f"[orchestrator] Delegating to sentiment_research (delegation {count}/{MAX_DELEGATIONS})")
    result = _run_sub_agent(sentiment_research_agent, state)
    result["delegation_count"] = 1  # increment delegation counter
    return result

def quant_node(state: AgentState):
    count = state.get("delegation_count", 0) + 1
    print(f"[orchestrator] Delegating to quant (delegation {count}/{MAX_DELEGATIONS})")
    result = _run_sub_agent(quant_agent, state)
    result["delegation_count"] = 1  # increment delegation counter
    return result


def route_after_orchestrator(state: AgentState) -> Literal["sentiment_research", "quant", "synthesize", END]:
    """Inspect the orchestrator's last message for a DELEGATE: token.
    
    Always check for delegation FIRST (even if sub-agent replies exist),
    so the orchestrator can delegate to multiple agents sequentially.
    Falls back to synthesize if sub-agent data exists, or END if not.
    """
    last = state["messages"][-1]
    text = extract_text(last.content)
    
    # Safety cap: if we've delegated too many times, force synthesis or end.
    count = state.get("delegation_count", 0)
    if count >= MAX_DELEGATIONS:
        print(f"[router] Delegation cap reached ({MAX_DELEGATIONS}). Forcing synthesis/end.")
        if any(getattr(m, "name", None) == "sub_agent" for m in state["messages"]):
            return "synthesize"
        return END
    
    # Check for a DELEGATE: token in the orchestrator's latest message.
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == "DELEGATE:sentiment_research":
            print(f"[router] Found DELEGATE:sentiment_research token")
            return "sentiment_research"
        if stripped == "DELEGATE:quant":
            print(f"[router] Found DELEGATE:quant token")
            return "quant"
    
    # No delegation token — if sub-agent data exists, synthesize; otherwise end.
    if any(getattr(m, "name", None) == "sub_agent" for m in state["messages"]):
        # The orchestrator chose NOT to delegate again — its message IS the
        # final synthesis (it already has all sub-agent data in context).
        return END
    return END


def synthesize_node(state: AgentState):
    """Fallback synthesis when the delegation cap is hit."""
    print(f"[synthesizer] Gemini call — generating final report from sub-agent data")
    llm = get_llm()
    messages = (
        [SystemMessage(content=(
            "You have reached the maximum number of delegations. Write a FORMAL "
            "REPORT using ONLY the data the sub-agents returned.\n\n"
            "FORMAL REPORT FORMAT:\n"
            "- Title: 'Financial Analysis Report' (list all companies/tickers).\n"
            "- Date: Include today's date.\n"
            "- If multiple companies: organise per company with sub-sections.\n"
            "- Sub-headings: 1. News Sentiment Analysis, 2. Quantitative Risk "
            "  Metrics. Omit sections with no data.\n"
            "- Comparative Summary (if multiple companies).\n"
            "- Conclusion & Outlook.\n"
            "- Use markdown formatting.\n\n"
            "ABSOLUTE DATA-INTEGRITY RULES (NEVER VIOLATE):\n"
            "- The report must contain ONLY information from sub-agent responses.\n"
            "- Do NOT add background, company descriptions, market context, "
            "  historical facts, or general knowledge.\n"
            "- Do NOT infer, extrapolate, speculate, or editorialize.\n"
            "- Every sentence must trace to specific sub-agent output.\n"
            "- If no data was returned, state that explicitly.\n"
            "- Do NOT delegate again."
        ))]
        + list(state["messages"])
    )
    response = llm.invoke(messages)
    return {"messages": [response]}


# ── Wire the orchestrator graph ──────────────────────────────────────────────

orchestrator_graph = StateGraph(AgentState)

orchestrator_graph.add_node("orchestrator", orchestrator_node)
orchestrator_graph.add_node("sentiment_research",     sentiment_research_node)
orchestrator_graph.add_node("quant",        quant_node)
orchestrator_graph.add_node("synthesize",   synthesize_node)

orchestrator_graph.add_edge(START, "orchestrator")
orchestrator_graph.add_conditional_edges(
    "orchestrator",
    route_after_orchestrator,
    {
        "sentiment_research":   "sentiment_research",
        "quant":      "quant",
        "synthesize": "synthesize",
        END:          END,
    },
)
# After each sub-agent finishes, go back to the orchestrator so it can
# synthesize or delegate further.
orchestrator_graph.add_edge("sentiment_research",   "orchestrator")
orchestrator_graph.add_edge("quant",      "orchestrator")
orchestrator_graph.add_edge("synthesize", END)

# ── Compile ──────────────────────────────────────────────────────────────────

app = orchestrator_graph.compile()


# ═══════════════════════════════════════════════════════════════════════════════
# CONVENIENCE  HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def chat(user_input: str, history: list[BaseMessage] | None = None) -> str:
    """Send a message and return the assistant's final text reply.

    Args:
        user_input: The user's message.
        history:    Optional prior messages for multi-turn conversations.

    Returns:
        The assistant's response string.
    """
    messages = list(history) if history else []
    messages.append(HumanMessage(content=user_input))

    result = app.invoke({"messages": messages, "delegation_count": 0, "tool_iterations": 0})
    # Return the last AI message content.
    for msg in reversed(result["messages"]):
        if isinstance(msg, AIMessage) and not getattr(msg, "name", None):
            return extract_text(msg.content)
    return extract_text(result["messages"][-1].content)


def stream_chat(user_input: str, history: list[BaseMessage] | None = None):
    """Generator that yields intermediate events for observability.

    Yields dicts with keys: ``node``, ``content``.
    """
    messages = list(history) if history else []
    messages.append(HumanMessage(content=user_input))

    for event in app.stream({"messages": messages, "delegation_count": 0, "tool_iterations": 0}):
        for node_name, node_output in event.items():
            last = node_output["messages"][-1]
            yield {"node": node_name, "content": extract_text(last.content)}


# ═══════════════════════════════════════════════════════════════════════════════
# CLI  (quick test)
# ═══════════════════════════════════════════════════════════════════════════════

def generate_report(stock_inputs: list[str]) -> str:
    """Generate a formal financial analysis report for one or more stocks.

    Args:
        stock_inputs: A list of stock tickers (e.g. ['NVDA']) or company
                      names (e.g. ['Nvidia', 'Apple']) or a mix of both.

    Returns:
        The formal report as a markdown string.
    """
    stocks_str = ", ".join(stock_inputs)
    prompt = (
        f"Generate a comprehensive financial analysis report for the following "
        f"companies/tickers: {stocks_str}. "
        f"For each one, gather news sentiment data and any available "
        f"quantitative risk metrics."
    )
    return chat(prompt)


def parse_stock_input(raw: str) -> list[str]:
    """Parse user input into a list of tickers/names.
    
    Accepts comma-separated, space-separated, or a single value.
    Examples:
        'NVDA'           -> ['NVDA']
        'NVDA, AAPL'     -> ['NVDA', 'AAPL']
        'Nvidia Apple'   -> ['Nvidia', 'Apple']
        'NVDA,AAPL,TSLA' -> ['NVDA', 'AAPL', 'TSLA']
    """
    if "," in raw:
        return [s.strip() for s in raw.split(",") if s.strip()]
    parts = raw.split()
    return [p.strip() for p in parts if p.strip()]


if __name__ == "__main__":
    print("╔══════════════════════════════════════════════╗")
    print("║   Financial Analysis Report Generator        ║")
    print("╚══════════════════════════════════════════════╝")
    print()
    print("Enter one or more stock tickers / company names.")
    print("Separate multiple entries with commas or spaces.")
    print("Examples: NVDA  |  NVDA, AAPL  |  Nvidia Apple Tesla\n")

    raw_input = input("Stock(s): ").strip()
    if not raw_input:
        print("No input provided. Exiting.")
        exit()

    stocks = parse_stock_input(raw_input)
    print(f"\nAnalysing: {', '.join(stocks)}")
    print("Please wait — gathering data from sub-agents...\n")
    print("=" * 60)

    report = generate_report(stocks)
    print(report)

    print("\n" + "=" * 60)
    print("Report complete.")
