"""Scripted infrastructure fixture. Its dialogue is NOT emergent social behavior."""

import asyncio
import json

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from .storage import uid


class MockResident(BaseChatModel):
    latency: float = 0.03

    @property
    def _llm_type(self):
        return "synthetic-resident-fixture"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        if messages and str(messages[0].content).startswith("Write a private fallible"):
            response = AIMessage(
                content="Synthetic summary fixture: prior experiences remain "
                "in original request records. This is a technical note."
            )
            return ChatResult(generations=[ChatGeneration(message=response)])
        world = next(m for m in reversed(messages) if m.id == "current-world")
        state = json.loads(world.content.split("\n", 1)[1])
        index = sum(isinstance(m, AIMessage) for m in messages)
        other = next(p["id"] for p in state["people"] if p["id"] != state["id"])
        if index == 0:
            name, args = (
                "board_post",
                dict(
                    title="Synthetic investigation fixture",
                    text="I will inspect the example retry documentation.",
                ),
            )
        elif index == 1:
            name, args = "read_source", dict(source_id="github:example/widget/docs/retries.md")
        elif index == 2:
            result = json.loads(
                next(m.content for m in reversed(messages) if isinstance(m, ToolMessage))
            )
            name, args = (
                "remember",
                dict(
                    text="The synthetic guide distinguishes ambiguous writes from reads.",
                    memory_kind="belief",
                    sources=[result["reference"]],
                    people=[other],
                ),
            )
        elif index == 3:
            name, args = (
                "send_direct_message",
                dict(
                    recipient_id=other,
                    text=(
                        "Synthetic fixture: the retry guide says a timeout "
                        "does not prove no effect."
                    ),
                ),
            )
        elif index == 4:
            name, args = "sleep", dict(seconds=60, minimum_tickets=2)
        else:
            dm = next(
                (
                    m
                    for m in reversed(messages)
                    if isinstance(m, HumanMessage) and (m.id or "").startswith("dm:")
                ),
                None,
            )
            last = next((m for m in reversed(messages) if isinstance(m, AIMessage)), None)
            if dm and last and last.tool_calls and last.tool_calls[0]["name"] == "sleep":
                name, args = (
                    "remember",
                    dict(
                        text="I received the other fixture's private observation about retries.",
                        sources=[dm.id[3:]],
                        people=[other],
                    ),
                )
            else:
                name, args = "sleep", dict(seconds=3600, minimum_tickets=2)
        response = AIMessage(
            content="Synthetic fixture decision.",
            id=uid(),
            tool_calls=[dict(name=name, args=args, id=uid(), type="tool_call")],
            usage_metadata=dict(input_tokens=100, output_tokens=30, total_tokens=130),
        )
        return ChatResult(generations=[ChatGeneration(message=response)])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        await asyncio.sleep(self.latency)
        return self._generate(messages, stop, run_manager, **kwargs)
