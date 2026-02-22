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
from databricks import sql

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
DATABRICKS_TOKEN = os.getenv("DATABRICKS_TOKEN")      # personal access token

if not GOOGLE_API_KEY:
    raise EnvironmentError("GOOGLE_API_KEY not found. Set it in the .env file.")

# ── LLM factory ──────────────────────────────────────────────────────────────

def get_llm(temperature: float = 0.0):
    """Return a Gemini chat model instance."""
    return ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        temperature=temperature,
        google_api_key=GOOGLE_API_KEY,
        timeout=120,            # HTTP request timeout in seconds
        max_retries=2,
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

    return headlines[:10]  # Cap at 10 headlines to keep context concise


# ── Quant Agent Tools ────────────────────────────────────────────────────────

@tool
def compute_fraud_scores(ticker: str) -> str:
    """Query Databricks for Beneish M-Score, Altman Z-Score, accruals ratio,
    and composite fraud risk score for a company given its stock ticker.

    Args:
        ticker: Stock ticker symbol (e.g. 'AAPL').

    Returns:
        A formatted string with the retrieved metrics, or an error message.
    """
    if not DATABRICKS_TOKEN:
        return (
            "[error] Databricks credentials not configured. "
            "Set DATABRICKS_TOKEN in .env."
        )

    try:
        print(f"  [tool:compute_fraud_scores] Querying Databricks for ticker={ticker.upper()}")

        connection = sql.connect(
            server_hostname="dbc-8d2119a9-8a9f.cloud.databricks.com",
            http_path="/sql/1.0/warehouses/caf31424be59761a",
            access_token=DATABRICKS_TOKEN,
        )
        cursor = connection.cursor()

        cursor.execute(
            "SELECT Ticker, m_score, z_score, accruals_ratio, composite_fraud_risk_score "
            "FROM workspace.default.stocks "
            "WHERE UPPER(Ticker) = UPPER(%(ticker)s) "
            "LIMIT 1",
            {"ticker": ticker.upper()},
        )

        row = cursor.fetchone()

        cursor.close()
        connection.close()

        if not row:
            return f"No fraud-score data found in the database for ticker '{ticker}'."

        return (
            f"Fraud / Risk Metrics for {row[0]}:\n"
            f"  Beneish M-Score:              {row[1]}\n"
            f"  Altman Z-Score:               {row[2]}\n"
            f"  Accruals Ratio:               {row[3]}\n"
            f"  Composite Fraud Risk Score:   {row[4]}"
        )

    except Exception as exc:
        return f"[error] Databricks query failed for '{ticker}': {exc}"


# Add more quant tools here …


# ═══════════════════════════════════════════════════════════════════════════════
# AGENT  STATE
# ═══════════════════════════════════════════════════════════════════════════════

MAX_DELEGATIONS = 10  # Safety cap to prevent infinite delegation loops (raised for multi-ticker)
MAX_TOOL_ITERATIONS = 3  # Safety cap for sub-agent tool-calling loops per invocation

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
        "Sentiment analysis agent. ALWAYS call your tools — never answer from memory.\n"
        "Call the tool ONCE PER TICKER. Infer tickers from company names.\n\n"
        "Per company, return ALL of the following:\n"
        "- Headline count: total number of headlines retrieved\n"
        "- Sentiment tally: X Positive, Y Negative, Z Neutral\n"
        "- Key themes: list every distinct theme you can identify from the headlines\n"
        "- Notable headlines: list up to 5 of the most significant headlines, each\n"
        "  with its sentiment label (Positive/Negative/Neutral) and a one-sentence\n"
        "  explanation of why it matters\n"
        "- Overall sentiment verdict: Strongly Positive / Positive / Mixed / Negative / Strongly Negative\n"
        "- Brief narrative summary: 2-3 sentences explaining the overall sentiment landscape\n\n"
        "RULES: Use ONLY tool data. No background/context/general knowledge. "
        "If no data: 'No headlines returned for [TICKER].'"
    ),
    tools=research_tools,
)

quant_agent = _build_sub_agent(
    name="QuantAgent",
    system_prompt=(
        "Quant fraud-detection agent. ALWAYS call your tools — never answer from memory.\n"
        "Call the tool ONCE PER TICKER.\n\n"
        "After receiving tool results, provide a THOROUGH interpretation of each metric:\n\n"
        "For EACH metric returned by the tool:\n"
        "  1. State the exact numeric value retrieved\n"
        "  2. State the standard threshold / benchmark range\n"
        "  3. Classify the result (e.g. 'safe', 'grey zone', 'distress', 'flagged')\n"
        "  4. Explain in 1-2 sentences what this means for the company\n\n"
        "Standard thresholds:\n"
        "- Beneish M-Score: > -1.78 = likely earnings manipulation, < -1.78 = unlikely\n"
        "- Altman Z-Score: > 2.99 = safe zone, 1.81-2.99 = grey zone, < 1.81 = distress zone\n"
        "- Accruals Ratio: large positive = aggressive accounting, near zero/negative = conservative\n"
        "- Composite Fraud Risk Score: 0-100 scale (0-25 low, 25-50 moderate, 50-75 elevated, 75-100 high)\n\n"
        "After all metrics, write a 2-3 sentence overall risk assessment paragraph.\n\n"
        "RULES: Use ONLY tool data. No background/context/general knowledge. "
        "If no data or placeholder, report exactly as-is."
    ),
    tools=quant_tools,
)


# ═══════════════════════════════════════════════════════════════════════════════
# ORCHESTRATOR  GRAPH
# ═══════════════════════════════════════════════════════════════════════════════

ORCHESTRATOR_SYSTEM_PROMPT = """\
You are a financial-analysis orchestrator. Your job is to delegate work to sub-agents.

Sub-agents available: sentiment_research, quant.
To delegate, reply with ONLY the text: DELEGATE:sentiment_research or DELEGATE:quant
Delegate to sentiment_research first, then quant. One at a time.
Do NOT write a report — a separate synthesizer handles that after all agents finish.
"""


def orchestrator_node(state: AgentState):
    """Main orchestrator LLM call."""
    count = state.get("delegation_count", 0)
    has_sentiment = any(getattr(m, "name", None) == "sentiment_research_result" for m in state["messages"])
    has_quant = any(getattr(m, "name", None) == "quant_result" for m in state["messages"])

    llm = get_llm()

    if has_sentiment or has_quant:
        # Strip intermediate messages to reduce context.
        # Keep only: user request + sub-agent results + a guidance note.
        user_msgs = [m for m in state["messages"] if isinstance(m, HumanMessage)]
        sub_agent_msgs = [m for m in state["messages"]
                          if getattr(m, "name", None) in ("sentiment_research_result", "quant_result")]

        # Build a guidance note so the orchestrator knows what's done vs. remaining.
        done = []
        remaining = []
        if has_sentiment:
            done.append("sentiment_research")
        else:
            remaining.append("sentiment_research")
        if has_quant:
            done.append("quant")
        else:
            remaining.append("quant")

        if remaining:
            # Skip the LLM call — just emit the delegation token directly.
            next_agent = remaining[0]
            print(f"[orchestrator] Auto-delegating to {next_agent} (done: {done}, remaining: {remaining})")
            delegate_msg = AIMessage(content=f"DELEGATE:{next_agent}")
            return {"messages": [delegate_msg]}
        else:
            # All agents done — emit a short token to signal synthesis.
            # Skip the expensive orchestrator LLM call entirely.
            print(f"[orchestrator] All agents done. Routing to synthesizer.")
            return {"messages": [AIMessage(content="ALL_AGENTS_DONE")]}
    else:
        print(f"[orchestrator] Gemini call (delegations so far: {count}/{MAX_DELEGATIONS})")
        messages = [SystemMessage(content=ORCHESTRATOR_SYSTEM_PROMPT)] + list(state["messages"])

    response = llm.invoke(messages)
    print(f"[orchestrator] Gemini responded. Response length: {len(extract_text(response.content))} chars")
    return {"messages": [response]}


def _run_sub_agent(agent, state: AgentState, agent_label: str = "sub_agent") -> dict:
    """Run a compiled sub-agent graph and return its final AI message."""
    # Pass only the user's original request — strip orchestrator/delegation noise.
    user_msgs = [m for m in state["messages"] if isinstance(m, HumanMessage)]
    result = agent.invoke({"messages": user_msgs, "tool_iterations": 0})
    # Grab only the last AI message produced by the sub-agent.
    sub_messages = result["messages"]
    final_ai = [m for m in sub_messages if isinstance(m, AIMessage)]
    if final_ai:
        content = extract_text(final_ai[-1].content)
        reply = AIMessage(content=content, name=agent_label)
    else:
        reply = AIMessage(content="Sub-agent produced no response.", name=agent_label)
    print(f"  [{agent_label}] Finished. Response length: {len(extract_text(reply.content))} chars")
    return {"messages": [reply]}


def sentiment_research_node(state: AgentState):
    count = state.get("delegation_count", 0) + 1
    print(f"[orchestrator] Delegating to sentiment_research (delegation {count}/{MAX_DELEGATIONS})")
    result = _run_sub_agent(sentiment_research_agent, state, agent_label="sentiment_research_result")
    result["delegation_count"] = 1  # increment delegation counter
    return result

def quant_node(state: AgentState):
    count = state.get("delegation_count", 0) + 1
    print(f"[orchestrator] Delegating to quant (delegation {count}/{MAX_DELEGATIONS})")
    result = _run_sub_agent(quant_agent, state, agent_label="quant_result")
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
        has_results = any(getattr(m, "name", None) in ("sentiment_research_result", "quant_result") for m in state["messages"])
        if has_results:
            return "synthesize"
        return END
    
    # Check for a DELEGATE: token in the orchestrator's latest message.
    # Also prevent re-delegation to an agent that already returned results.
    already_has_sentiment = any(getattr(m, "name", None) == "sentiment_research_result" for m in state["messages"])
    already_has_quant = any(getattr(m, "name", None) == "quant_result" for m in state["messages"])

    for line in text.splitlines():
        stripped = line.strip()
        if stripped == "DELEGATE:sentiment_research":
            if already_has_sentiment:
                print(f"[router] Blocked re-delegation to sentiment_research (already has results)")
                continue
            print(f"[router] Found DELEGATE:sentiment_research token")
            return "sentiment_research"
        if stripped == "DELEGATE:quant":
            if already_has_quant:
                print(f"[router] Blocked re-delegation to quant (already has results)")
                continue
            print(f"[router] Found DELEGATE:quant token")
            return "quant"
    
    # No delegation token (or all requested agents already ran).
    has_any_results = already_has_sentiment or already_has_quant
    if has_any_results:
        text_stripped = text.strip()
        # ALL_AGENTS_DONE signal, empty, stale DELEGATE, or too-short response → synthesize.
        if not text_stripped or text_stripped == "ALL_AGENTS_DONE" or text_stripped.startswith("DELEGATE:") or len(text_stripped) < 100:
            print(f"[router] Routing to synthesizer.")
            return "synthesize"
        # Otherwise the orchestrator wrote a real report — we're done.
        print(f"[router] Final report received ({len(text_stripped)} chars). Ending.")
        return END
    return END


def synthesize_node(state: AgentState):
    """Generate the final report from sub-agent data."""
    print(f"[synthesizer] Gemini call — generating final report from sub-agent data")
    llm = get_llm()
    # Only pass user messages + sub-agent results to keep context small.
    user_msgs = [m for m in state["messages"] if isinstance(m, HumanMessage)]
    sub_agent_msgs = [m for m in state["messages"]
                      if getattr(m, "name", None) in ("sentiment_research_result", "quant_result")]
    messages = (
        [SystemMessage(content=(
            "You are a senior financial analyst. Write a COMPREHENSIVE, FORMAL markdown report "
            "using ONLY the sub-agent data provided below. The report must be long, thorough, "
            "and explicitly reference the data retrieved from each agent.\n\n"
            "REQUIRED STRUCTURE:\n\n"
            "# Financial Analysis Report\n"
            "State the ticker(s) analysed.\n\n"
            "## Executive Summary\n"
            "A concise 3-5 sentence overview of all key findings across every section.\n\n"
            "Then, FOR EACH COMPANY analysed, include ALL of the following sections:\n\n"
            "## [Company Ticker] — News Sentiment Analysis\n"
            "### Data Retrieved\n"
            "Explicitly state: number of headlines retrieved, source (Yahoo Finance News).\n"
            "If no headlines were returned, state that clearly and skip to the next section.\n"
            "### Sentiment Breakdown\n"
            "Report the exact sentiment tally (X Positive, Y Negative, Z Neutral).\n"
            "### Key Themes\n"
            "List and briefly discuss each theme identified in the headlines.\n"
            "### Notable Headlines\n"
            "Present the most significant headlines with their sentiment labels and "
            "explain the relevance of each.\n"
            "### Sentiment Verdict\n"
            "State the overall verdict and provide a narrative interpretation.\n\n"
            "## [Company Ticker] — Quantitative Risk Metrics\n"
            "### Data Retrieved\n"
            "Explicitly state: which metrics were retrieved, source (Databricks SQL warehouse).\n"
            "If no data was available, state that clearly and skip to the next section.\n"
            "### Metric-by-Metric Analysis\n"
            "For EACH metric (M-Score, Z-Score, Accruals Ratio, Composite Fraud Risk Score):\n"
            "- State the exact value retrieved from the quant agent\n"
            "- State the standard threshold / benchmark\n"
            "- Classify the result (safe / grey zone / flagged / etc.)\n"
            "- Explain what this means for the company in 1-2 sentences\n"
            "### Overall Risk Assessment\n"
            "Synthesise the quantitative metrics into a paragraph-length risk assessment.\n\n"
            "## Conclusion & Integrated Assessment\n"
            "Synthesise ALL findings from ALL sections (sentiment + quant) into a detailed, "
            "actionable conclusion. Discuss how the sentiment and quantitative data "
            "corroborate or contradict each other. Provide a clear overall assessment.\n\n"
            "RULES:\n"
            "- Use ONLY the sub-agent data below. No outside knowledge, background descriptions, "
            "  or speculation.\n"
            "- Every claim must trace back to specific data from a sub-agent.\n"
            "- If a section has no data, state that explicitly — do not skip the heading.\n"
            "- Do NOT delegate. Write the complete report now."
        ))]
        + user_msgs + sub_agent_msgs
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
