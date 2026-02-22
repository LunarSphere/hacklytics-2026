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
DATABRICKS_TOKEN = os.getenv("databricks_sql_pa")      # personal access token

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
        print(f"  [DEBUG:compute_fraud_scores] DATABRICKS_TOKEN is empty/None!")
        return (
            "[error] Databricks credentials not configured. "
            "Set databricks_sql_pa in .env."
        )

    try:
        print(f"  [tool:compute_fraud_scores] Querying Databricks for ticker={ticker.upper()}")
        print(f"  [DEBUG:compute_fraud_scores] Token present: {bool(DATABRICKS_TOKEN)}, length: {len(DATABRICKS_TOKEN)}")
        print(f"  [DEBUG:compute_fraud_scores] Token prefix: {DATABRICKS_TOKEN[:8]}...")

        connection = sql.connect(
            server_hostname="dbc-8d2119a9-8a9f.cloud.databricks.com",
            http_path="/sql/1.0/warehouses/caf31424be59761a",
            access_token=DATABRICKS_TOKEN,
        )
        print(f"  [DEBUG:compute_fraud_scores] Connection established successfully")
        cursor = connection.cursor()

        query = (
            "SELECT Ticker, m_score, z_score, accruals_ratio, composite_fraud_risk_score "
            "FROM workspace.default.stocks "
            "WHERE UPPER(Ticker) = UPPER(%(ticker)s) "
            "LIMIT 1"
        )
        params = {"ticker": ticker.upper()}
        print(f"  [DEBUG:compute_fraud_scores] Executing query with params: {params}")

        cursor.execute(query, params)

        row = cursor.fetchone()
        print(f"  [DEBUG:compute_fraud_scores] Query returned row: {row}")
        print(f"  [DEBUG:compute_fraud_scores] Row type: {type(row)}")

        if row:
            print(f"  [DEBUG:compute_fraud_scores] Row length: {len(row)}")
            for i, val in enumerate(row):
                print(f"  [DEBUG:compute_fraud_scores]   col[{i}] = {val!r} (type={type(val).__name__})")

        cursor.close()
        connection.close()

        if not row:
            print(f"  [DEBUG:compute_fraud_scores] No row found for ticker '{ticker.upper()}'")
            return f"No fraud-score data found in the database for ticker '{ticker}'."

        result = (
            f"Fraud / Risk Metrics for {row[0]}:\n"
            f"  Beneish M-Score:              {row[1]}\n"
            f"  Altman Z-Score:               {row[2]}\n"
            f"  Accruals Ratio:               {row[3]}\n"
            f"  Composite Fraud Risk Score:   {row[4]}"
        )
        print(f"  [DEBUG:compute_fraud_scores] Returning result:\n{result}")
        return result

    except Exception as exc:
        print(f"  [DEBUG:compute_fraud_scores] EXCEPTION: {type(exc).__name__}: {exc}")
        import traceback
        traceback.print_exc()
        return f"[error] Databricks query failed for '{ticker}': {exc}"


# Add more quant tools here …


# ── Stock Health Agent Tools ─────────────────────────────────────────────────

# TODO: Replace this URL with your actual FastAPI endpoint.
STOCK_HEALTH_API_URL = "http://127.0.0.1:7171/health-score"

@tool
def fetch_stock_health(ticker: str) -> str:
    """Fetch stock-health metrics from the FastAPI service for a given ticker.

    Args:
        ticker: Stock ticker symbol (e.g. 'AAPL').

    Returns:
        A formatted string with the retrieved health metrics, or an error message.
    """
    try:
        print(f"  [tool:fetch_stock_health] Calling FastAPI for ticker={ticker.upper()}")
        response = requests.get(
            f"{STOCK_HEALTH_API_URL}/{ticker.upper()}",
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()

        # Extract known health metrics from the API response.
        sharpe      = data.get("sharpe", "N/A")
        sortino     = data.get("sortino", "N/A")
        alpha       = data.get("alpha", "N/A")
        beta        = data.get("beta", "N/A")
        var_95      = data.get("var_95", "N/A")
        cvar_95     = data.get("cvar_95", "N/A")
        max_dd      = data.get("max_drawdown", "N/A")
        volatility  = data.get("volatility", "N/A")
        composite   = data.get("composite_stock_health_score", "N/A")

        return (
            f"Stock Health Metrics for {ticker.upper()}:\n"
            f"  Sharpe Ratio:                   {sharpe}\n"
            f"  Sortino Ratio:                  {sortino}\n"
            f"  Alpha:                          {alpha}\n"
            f"  Beta:                           {beta}\n"
            f"  Value at Risk (95%):            {var_95}\n"
            f"  Conditional VaR (95%):          {cvar_95}\n"
            f"  Max Drawdown:                   {max_dd}\n"
            f"  Volatility:                     {volatility}\n"
            f"  Composite Stock Health Score:   {composite}"
        )

    except requests.exceptions.ConnectionError:
        return (
            f"[error] Could not connect to stock-health API at {STOCK_HEALTH_API_URL}. "
            f"Is the FastAPI server running?"
        )
    except Exception as exc:
        return f"[error] Stock-health API call failed for '{ticker}': {exc}"


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

research_tools      = [yahoo_news]
quant_tools         = [compute_fraud_scores]
stock_health_tools  = [fetch_stock_health]

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
        "NEVER fabricate, estimate, or invent any data. "
        "If the tool returned an error or no headlines, say exactly: "
        "'No headlines could be retrieved for [TICKER].' and stop. "
        "Do NOT make up headlines, sentiment tallies, or themes."
    ),
    tools=research_tools,
)

quant_agent = _build_sub_agent(
    name="QuantAgent",
    system_prompt=(
        "Quant fraud-detection agent. ALWAYS call your tools — never answer from memory.\n"
        "Call the tool ONCE PER TICKER.\n\n"
        "After receiving tool results, you MUST present EVERY SINGLE METRIC returned.\n"
        "Do NOT skip, summarise away, or omit any metric. If a metric was returned by the\n"
        "tool, it MUST appear in your response with full interpretation.\n\n"
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
        "Do NOT omit any metric that the tool returned. "
        "NEVER fabricate, estimate, or invent metric values. "
        "If the tool returned an error message, reproduce the error verbatim and state: "
        "'Fraud risk metrics could not be retrieved for [TICKER].' "
        "If a specific metric is missing or null, state: '[Metric Name]: Data not available.' "
        "Do NOT guess or fill in values that were not in the tool response."
    ),
    tools=quant_tools,
)

stock_health_agent = _build_sub_agent(
    name="StockHealthAgent",
    system_prompt=(
        "Stock-health analysis agent. ALWAYS call your tools — never answer from memory.\n"
        "Call the tool ONCE PER TICKER.\n\n"
        "After receiving tool results, provide a THOROUGH interpretation of each metric:\n\n"
        "For EACH metric returned by the tool:\n"
        "  1. State the exact numeric value retrieved\n"
        "  2. State the standard threshold / benchmark range\n"
        "  3. Classify the result (e.g. 'strong', 'healthy', 'moderate', 'weak', 'critical')\n"
        "  4. Explain in 1-2 sentences what this means for the company\n\n"
        "Standard thresholds:\n"
        "- Sharpe Ratio: > 1.0 = good, > 2.0 = very good, > 3.0 = excellent, < 0 = poor\n"
        "- Sortino Ratio: > 1.0 = good, > 2.0 = very good, < 0 = poor (penalises downside only)\n"
        "- Alpha: > 0 = outperforming benchmark, < 0 = underperforming benchmark\n"
        "- Beta: 1.0 = market-level risk, < 1 = lower volatility than market, > 1 = higher volatility\n"
        "- Value at Risk (95%): more negative = larger potential daily loss at 95% confidence\n"
        "- Conditional VaR (95%): expected loss beyond the VaR threshold (tail risk); more negative = worse\n"
        "- Max Drawdown: closer to 0% = resilient, > -20% = moderate, > -40% = severe decline\n"
        "- Volatility: < 15% = low, 15-25% = moderate, > 25% = high\n"
        "- Composite Stock Health Score: 0-100 scale (0-25 poor, 25-50 below average, 50-75 above average, 75-100 strong)\n\n"
        "After all metrics, write a 2-3 sentence overall stock-health assessment paragraph.\n\n"
        "RULES: Use ONLY tool data. No background/context/general knowledge. "
        "NEVER fabricate, estimate, or invent metric values. "
        "If the tool returned an error message, reproduce the error verbatim and state: "
        "'Stock health metrics could not be retrieved for [TICKER].' "
        "If a specific metric is missing or 'N/A', state: '[Metric Name]: Data not available.' "
        "Do NOT guess or fill in values that were not in the tool response."
    ),
    tools=stock_health_tools,
)


# ═══════════════════════════════════════════════════════════════════════════════
# ORCHESTRATOR  GRAPH
# ═══════════════════════════════════════════════════════════════════════════════

ORCHESTRATOR_SYSTEM_PROMPT = """\
You are a financial-analysis orchestrator. Your ONLY job is to delegate work to sub-agents.
You MUST delegate to ALL THREE agents — no exceptions.

Sub-agents available: sentiment_research, quant, stock_health.
To delegate, reply with ONLY the text: DELEGATE:sentiment_research or DELEGATE:quant or DELEGATE:stock_health
Delegate in this order: sentiment_research first, then quant, then stock_health. One at a time.
Do NOT write a report — a separate synthesizer handles that after all agents finish.
Do NOT skip any agent. All three MUST be called.
"""


def orchestrator_node(state: AgentState):
    """Main orchestrator LLM call."""
    count = state.get("delegation_count", 0)
    has_sentiment = any(getattr(m, "name", None) == "sentiment_research_result" for m in state["messages"])
    has_quant = any(getattr(m, "name", None) == "quant_result" for m in state["messages"])
    has_stock_health = any(getattr(m, "name", None) == "stock_health_result" for m in state["messages"])

    llm = get_llm()

    if has_sentiment or has_quant or has_stock_health:
        # Strip intermediate messages to reduce context.
        # Keep only: user request + sub-agent results + a guidance note.
        user_msgs = [m for m in state["messages"] if isinstance(m, HumanMessage)]
        sub_agent_msgs = [m for m in state["messages"]
                          if getattr(m, "name", None) in ("sentiment_research_result", "quant_result", "stock_health_result")]

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
        if has_stock_health:
            done.append("stock_health")
        else:
            remaining.append("stock_health")

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

def stock_health_node(state: AgentState):
    count = state.get("delegation_count", 0) + 1
    print(f"[orchestrator] Delegating to stock_health (delegation {count}/{MAX_DELEGATIONS})")
    result = _run_sub_agent(stock_health_agent, state, agent_label="stock_health_result")
    result["delegation_count"] = 1  # increment delegation counter
    return result


def route_after_orchestrator(state: AgentState) -> Literal["sentiment_research", "quant", "stock_health", "synthesize", END]:
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
        has_results = any(getattr(m, "name", None) in ("sentiment_research_result", "quant_result", "stock_health_result") for m in state["messages"])
        if has_results:
            return "synthesize"
        return END
    
    # Check for a DELEGATE: token in the orchestrator's latest message.
    # Also prevent re-delegation to an agent that already returned results.
    already_has_sentiment = any(getattr(m, "name", None) == "sentiment_research_result" for m in state["messages"])
    already_has_quant = any(getattr(m, "name", None) == "quant_result" for m in state["messages"])
    already_has_stock_health = any(getattr(m, "name", None) == "stock_health_result" for m in state["messages"])

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
        if stripped == "DELEGATE:stock_health":
            if already_has_stock_health:
                print(f"[router] Blocked re-delegation to stock_health (already has results)")
                continue
            print(f"[router] Found DELEGATE:stock_health token")
            return "stock_health"
    
    # No delegation token (or all requested agents already ran).
    has_any_results = already_has_sentiment or already_has_quant or already_has_stock_health
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
                      if getattr(m, "name", None) in ("sentiment_research_result", "quant_result", "stock_health_result")]

    # Debug: log what each agent returned so we can diagnose missing data.
    for msg in sub_agent_msgs:
        agent_name = getattr(msg, "name", "unknown")
        content_preview = extract_text(msg.content)[:200]
        has_error = "[error]" in content_preview.lower() or "could not" in content_preview.lower()
        print(f"  [synthesizer] Agent '{agent_name}': {len(extract_text(msg.content))} chars, error={'YES' if has_error else 'no'}")
        if has_error:
            print(f"    Preview: {content_preview}")

    SYNTHESIZER_PROMPT = (
        "You are a senior financial analyst writing a formal markdown report.\n\n"
        "HANDLING MISSING DATA (READ THIS FIRST):\n"
        "Some sub-agents may have returned errors, empty results, or 'N/A' values.\n"
        "This is NORMAL. When this happens:\n"
        "  - Still include the section heading.\n"
        "  - Write ONE sentence: 'Data could not be retrieved. [quote the error or state no data was returned].'\n"
        "  - Then move on to the next section. Do NOT stall, do NOT try to fill in the gaps.\n"
        "  - NEVER fabricate, estimate, or guess any metric values.\n\n"
        "REPORT STRUCTURE (use ONLY the sub-agent data below):\n\n"
        "# Financial Analysis Report\n"
        "State the ticker(s) analysed.\n\n"
        "## Executive Summary\n"
        "3-5 sentences summarising findings. Mention which data sources were available and which were not.\n\n"
        "FOR EACH COMPANY:\n\n"
        "## [Ticker] — News Sentiment Analysis\n"
        "If the sentiment agent returned headlines: report the tally, themes, notable headlines, and verdict.\n"
        "If the sentiment agent returned an error or no data: state that and move on.\n\n"
        "## [Ticker] — Quantitative Fraud Risk Metrics\n"
        "If the quant agent returned metrics: for each metric (M-Score, Z-Score, Accruals Ratio, "
        "Composite Fraud Risk Score) state the value, threshold, classification, and interpretation.\n"
        "If the quant agent returned an error or no data: state that and move on.\n\n"
        "## [Ticker] — Stock Health Analysis\n"
        "If the stock-health agent returned metrics: for each metric (Sharpe, Sortino, Alpha, Beta, "
        "VaR 95%, CVaR 95%, Max Drawdown, Volatility, Composite Health Score) state the value, "
        "threshold, classification, and interpretation.\n"
        "If the stock-health agent returned an error or no data: state that and move on.\n\n"
        "## Conclusion & Integrated Assessment\n"
        "Synthesise available findings. Note which data sources had gaps.\n\n"
        "RULES: Use ONLY sub-agent data. NEVER fabricate values. If data is missing, say so and continue."
    )

    messages = [SystemMessage(content=SYNTHESIZER_PROMPT)] + user_msgs + sub_agent_msgs
    response = llm.invoke(messages)
    full_report = extract_text(response.content)

    # Second (cheap) LLM call: generate a 1-2 paragraph executive summary.
    print(f"[synthesizer] Gemini call — generating short summary")
    summary_response = llm.invoke([
        SystemMessage(content=(
            "Condense the following financial analysis report into a 1-2 paragraph "
            "executive summary. Keep it factual and data-driven. Do not add new "
            "information — only summarise what is in the report."
        )),
        HumanMessage(content=full_report),
    ])
    summary = extract_text(summary_response.content)

    # Pack both into a JSON string so downstream consumers get structured data.
    result_json = json.dumps({"report": full_report, "summary": summary})
    return {"messages": [AIMessage(content=result_json)]}


# ── Wire the orchestrator graph ──────────────────────────────────────────────

orchestrator_graph = StateGraph(AgentState)

orchestrator_graph.add_node("orchestrator", orchestrator_node)
orchestrator_graph.add_node("sentiment_research",     sentiment_research_node)
orchestrator_graph.add_node("quant",        quant_node)
orchestrator_graph.add_node("stock_health", stock_health_node)
orchestrator_graph.add_node("synthesize",   synthesize_node)

orchestrator_graph.add_edge(START, "orchestrator")
orchestrator_graph.add_conditional_edges(
    "orchestrator",
    route_after_orchestrator,
    {
        "sentiment_research":   "sentiment_research",
        "quant":      "quant",
        "stock_health": "stock_health",
        "synthesize": "synthesize",
        END:          END,
    },
)
# After each sub-agent finishes, go back to the orchestrator so it can
# synthesize or delegate further.
orchestrator_graph.add_edge("sentiment_research",   "orchestrator")
orchestrator_graph.add_edge("quant",      "orchestrator")
orchestrator_graph.add_edge("stock_health", "orchestrator")
orchestrator_graph.add_edge("synthesize", END)

# ── Compile ──────────────────────────────────────────────────────────────────

app = orchestrator_graph.compile()


# ═══════════════════════════════════════════════════════════════════════════════
# CONVENIENCE  HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def chat(user_input: str, history: list[BaseMessage] | None = None) -> dict:
    """Send a message and return the assistant's final response.

    Args:
        user_input: The user's message.
        history:    Optional prior messages for multi-turn conversations.

    Returns:
        A dict with keys ``report`` (full markdown) and ``summary`` (1-2 paragraphs).
        Falls back to ``{"report": <raw text>, "summary": ""}`` if JSON parsing fails.
    """
    messages = list(history) if history else []
    messages.append(HumanMessage(content=user_input))

    result = app.invoke({"messages": messages, "delegation_count": 0, "tool_iterations": 0})
    # Find the last AI message (the synthesizer's JSON output).
    raw = ""
    for msg in reversed(result["messages"]):
        if isinstance(msg, AIMessage) and not getattr(msg, "name", None):
            raw = extract_text(msg.content)
            break
    if not raw:
        raw = extract_text(result["messages"][-1].content)

    # Parse the JSON envelope.
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {"report": raw, "summary": ""}


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

def generate_report(stock_inputs: list[str]) -> dict:
    """Generate a formal financial analysis report for one or more stocks.

    Args:
        stock_inputs: A list of stock tickers (e.g. ['NVDA']) or company
                      names (e.g. ['Nvidia', 'Apple']) or a mix of both.

    Returns:
        A dict with keys ``report`` (full markdown) and ``summary`` (1-2 paragraphs).
    """
    stocks_str = ", ".join(stock_inputs)
    prompt = (
        f"Generate a comprehensive financial analysis report for the following "
        f"companies/tickers: {stocks_str}. "
        f"For each one, gather news sentiment data, quantitative fraud risk metrics, "
        f"and stock health metrics. All three data sources must be included."
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

    result = generate_report(stocks)

    print("\n📋 SUMMARY")
    print("-" * 60)
    print(result.get("summary", "(no summary available)"))

    print("\n" + "=" * 60)
    print("📄 FULL REPORT")
    print("=" * 60)
    print(result.get("report", "(no report available)"))

    print("\n" + "=" * 60)
    print("Report complete.")
