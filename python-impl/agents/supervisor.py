"""
Supervisor编排Agent — 中央协调者
负责接收用户请求，根据意图路由到对应子Agent，汇总结果返回。
采用LangGraph StateGraph实现，支持并行调度和Human-in-the-Loop断点。
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, Literal, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.checkpoint.memory import MemorySaver

from agents.intent_router import IntentRouterAgent
from agents.knowledge_rag import KnowledgeRAGAgent
from agents.ticket_handler import TicketHandlerAgent
from agents.compliance_checker import ComplianceCheckerAgent
from agents.weather_agent import WeatherAgent
from memory.working_memory import WorkingMemory
from memory.short_term import ShortTermMemory
from memory.long_term import LongTermMemory
from tracing.otel_config import trace_agent_call


# ─── 状态定义 ───

class AgentState(TypedDict):
    """Supervisor编排的全局状态"""
    messages: Annotated[list[BaseMessage], add_messages]
    user_id: str
    session_id: str
    intent: str
    sub_results: dict[str, Any]
    compliance_passed: bool
    final_response: str
    current_agent: str
    retry_count: int


# ─── Supervisor节点 ───

SUPERVISOR_SYSTEM_PROMPT = """你是一个智能客服系统的Supervisor（主管编排Agent）。
你的职责是：
1. 分析用户意图，决定分发给哪个子Agent处理
2. 汇总子Agent的处理结果，生成最终回复
3. 确保所有回复都经过合规审查

可用的子Agent：
- knowledge_rag: 知识库检索和回答（用于产品咨询、政策查询等）
- ticket_handler: 工单创建和查询（用于投诉、创建工单等）
- compliance_checker: 合规审查和敏感词检测
- weather: 天气查询（用于查询天气、温度、预报等）
- greeting: 直接回复，不需要检索（用于打招呼、寒暄等）

路由决策规则：
- 用户只是打招呼/问好 → 返回 greeting
- 用户询问产品信息、利率、开户流程、退款政策等 → knowledge_rag
- 用户要投诉、创建工单 → ticket_handler
- 用户涉及资金安全、账号异常等 → compliance_checker
- 用户询问天气、温度、下雨、刮风等 → weather

重要：只返回意图标签，不需要解释原因。"""


class SupervisorNode:
    """Supervisor决策节点"""

    def __init__(self, llm: ChatOpenAI, working_memory: WorkingMemory):
        self.llm = llm
        self.working_memory = working_memory

    @trace_agent_call("supervisor")
    async def route_decision(self, state: AgentState) -> AgentState:
        """分析用户意图，决定路由"""
        messages = state["messages"]
        session_id = state.get("session_id", "default")

        context = self.working_memory.get_context(session_id)
        
        # 先检查是否是纯问候语（不需要 LLM 判断）
        last_message = messages[-1].content.strip() if messages else ""
        greeting_keywords = ["你好", "您好", "hi", "hello", "嗨", "早上好", "下午好", "晚上好", "hi", "hey", "嗨喽", "嗨嗨"]
        is_greeting = last_message.lower() in [k.lower() for k in greeting_keywords] or last_message in greeting_keywords

        if is_greeting and len(last_message) < 10:
            # 纯问候语，直接返回 greeting
            self.working_memory.update(session_id, {"last_intent": "greeting"})
            return {
                **state,
                "intent": "greeting",
                "current_agent": "supervisor",
            }

        # 关键词预检天气（不依赖 LLM）
        weather_keywords = [
            "天气", "温度", "下雨", "下雪", "刮风", "台风", "多云", "晴天", "阴天",
            "降温", "升温", "气候", "预报", "气温", "多少度",
            "冷", "热", "暖", "凉", "暖和", "炎热", "寒冷", "凉快", "温差",
            "冷不冷", "热不热", "冷不", "热吗", "冷吗",
        ]
        # 景点/地标名（出现这些词很可能是在问天气）
        landmark_keywords = [
            "西湖", "外滩", "故宫", "长城", "兵马俑", "黄山", "鼓浪屿",
            "迪士尼", "洪崖洞", "布达拉宫", "洱海", "张家界",
        ]
        if any(kw in last_message for kw in weather_keywords) or \
           any(lm in last_message for lm in landmark_keywords):
            self.working_memory.update(session_id, {"last_intent": "weather"})
            return {
                **state,
                "intent": "weather",
                "current_agent": "supervisor",
            }

        routing_prompt = [
            SystemMessage(content=SUPERVISOR_SYSTEM_PROMPT + f"\n当前工作记忆上下文: {context}"),
            *messages,
            HumanMessage(content=(
                '请分析用户的最新消息，判断用户是否只是在打招呼或寒暄。'
                '如果是（如你好、hi、hello、早上好等），只返回: greeting'
                '如果不是，返回以下之一: knowledge_rag, ticket_handler, compliance_checker, weather'
            )),
        ]

        response = await self.llm.ainvoke(routing_prompt)
        intent = response.content.strip().lower()

        valid_intents = {"knowledge_rag", "ticket_handler", "compliance_checker", "greeting", "weather"}
        if intent not in valid_intents:
            intent = "knowledge_rag"

        self.working_memory.update(session_id, {"last_intent": intent})

        return {
            **state,
            "intent": intent,
            "current_agent": "supervisor",
        }

    @trace_agent_call("supervisor_greeting")
    async def greeting_response(self, state: AgentState) -> AgentState:
        """处理打招呼类消息，直接返回问候语"""
        import random
        greeting = random.choice(GREETING_RESPONSES)
        return {
            **state,
            "final_response": greeting,
            "sub_results": {
                **state.get("sub_results", {}),
                "greeting": greeting,
            },
        }

    @trace_agent_call("supervisor_synthesize")
    async def synthesize_response(self, state: AgentState) -> AgentState:
        """汇总子Agent结果，生成最终回复"""
        sub_results = state.get("sub_results", {})
        compliance_passed = state.get("compliance_passed", True)

        if not compliance_passed:
            final_response = (
                "抱歉，您的请求涉及敏感内容，已转交人工客服处理。"
                "工单编号已自动生成，请留意后续通知。"
            )
        else:
            result_parts = []
            for agent_name, result in sub_results.items():
                if result:
                    if isinstance(result, dict):
                        result_parts.append(str(result.get("answer", "")))
                    else:
                        result_parts.append(str(result))
            final_response = "\n\n".join(result_parts) if result_parts else "抱歉，暂时无法处理您的请求，请稍后重试。"

        import logging
        logging.basicConfig(level=logging.DEBUG)
        log = logging.getLogger("synthesize")
        log.debug(f"compliance_passed={compliance_passed}, result_parts=%s", result_parts if 'result_parts' in dir() else 'N/A')
        log.debug(f"final_response before cot strip: {repr(final_response[:200])}")

        # 最终安全网：移除所有子Agent回复中可能残留的思考过程
        import re
        final_response = re.sub(r'<think>[\s\S]*?</think>\s*', '', final_response)
        final_response = re.sub(r'```[\s\S]*?```', '', final_response)
        final_response = final_response.strip()

        return {
            **state,
            "final_response": final_response,
            "messages": [AIMessage(content=final_response)],
        }


# ─── 路由函数 ───

GREETING_RESPONSES = [
    "您好！欢迎使用智能客服服务，有什么可以帮您的吗？",
    "您好！很高兴为您服务，请问有什么需要帮助的？",
    "您好！欢迎咨询，请问您想了解哪方面的信息？",
]

def route_to_agent(state: AgentState) -> str:
    """根据意图路由到对应Agent节点"""
    intent = state.get("intent", "knowledge_rag")
    if intent == "greeting":
        return "greeting"
    route_map = {
        "knowledge_rag": "knowledge_rag",
        "ticket_handler": "ticket_handler",
        "compliance_checker": "compliance_check",
        "weather": "weather",
    }
    return route_map.get(intent, "knowledge_rag")


def should_check_compliance(state: AgentState) -> str:
    """所有回复都需经过合规审查"""
    return "compliance_check"


# ─── 构建Graph ───

from langchain_openai import ChatOpenAI
import os

def create_supervisor_graph(
    llm: ChatOpenAI | None = None,
    working_memory: WorkingMemory | None = None,
    short_term_memory: ShortTermMemory | None = None,
    long_term_memory: LongTermMemory | None = None,
    enable_checkpointing: bool = True,
) -> StateGraph:
    """
    构建Supervisor编排的多Agent StateGraph。

    这是整个系统的核心入口，将4个子Agent通过有向图连接起来，
    由Supervisor节点负责路由决策和结果汇总。

    Args:
        llm: 语言模型实例
        working_memory: 工作记忆
        short_term_memory: 短期记忆
        long_term_memory: 长期记忆
        enable_checkpointing: 是否启用检查点（支持断点恢复）
    """
    if llm is None:
        llm = ChatOpenAI(
            model=os.getenv("MODEL_NAME", "MiniMax-M2.7"),
            openai_api_key=os.getenv("OPENAI_API_KEY"),
            openai_api_base=os.getenv("OPENAI_BASE_URL", "https://api.minimaxi.com/v1"),
            temperature=0.7,
            max_tokens=1000
        )
    if working_memory is None:
        working_memory = WorkingMemory()

    supervisor = SupervisorNode(llm, working_memory)

    intent_router = IntentRouterAgent(llm)
    knowledge_agent = KnowledgeRAGAgent(llm, long_term_memory)
    ticket_agent = TicketHandlerAgent(llm)
    compliance_agent = ComplianceCheckerAgent(llm)
    weather_agent = WeatherAgent()

    graph = StateGraph(AgentState)

    graph.add_node("supervisor_route", supervisor.route_decision)
    graph.add_node("knowledge_rag", knowledge_agent.process)
    graph.add_node("ticket_handler", ticket_agent.process)
    graph.add_node("compliance_check", compliance_agent.process)
    graph.add_node("synthesize", supervisor.synthesize_response)

    graph.add_node("greeting", supervisor.greeting_response)
    graph.add_node("weather", weather_agent.process)

    graph.set_entry_point("supervisor_route")

    graph.add_conditional_edges(
        "supervisor_route",
        route_to_agent,
        {
            "knowledge_rag": "knowledge_rag",
            "ticket_handler": "ticket_handler",
            "compliance_check": "compliance_check",
            "greeting": "greeting",
            "weather": "weather",
        },
    )

    graph.add_edge("knowledge_rag", "compliance_check")
    graph.add_edge("ticket_handler", "compliance_check")
    graph.add_edge("weather", "compliance_check")
    graph.add_edge("compliance_check", "synthesize")
    graph.add_edge("greeting", "synthesize")
    graph.add_edge("synthesize", END)

    checkpointer = MemorySaver() if enable_checkpointing else None
    compiled = graph.compile(checkpointer=checkpointer)

    return compiled
