"""LangGraph assembly."""
from langgraph.graph import END, START, StateGraph

from .nodes.assembler import assembler_node
from .nodes.consolidator import consolidator_node
from .nodes.extractor import dispatch_extractors, extractor_node
from .nodes.loader import loader_node
from .nodes.review import checks_node, critic_node, route_after_critic
from .nodes.writer import dispatch_writers, writer_node
from .state import State


def build_graph():
    g = StateGraph(State)
    g.add_node("loader", loader_node)
    g.add_node("extractor", extractor_node)
    g.add_node("consolidator", consolidator_node)
    g.add_node("writer", writer_node)
    g.add_node("checks", checks_node)
    g.add_node("critic", critic_node)
    g.add_node("assembler", assembler_node)
    g.add_edge(START, "loader")
    g.add_conditional_edges("loader", dispatch_extractors, ["extractor"])
    g.add_edge("extractor", "consolidator")
    g.add_conditional_edges("consolidator", dispatch_writers, ["writer", "checks"])
    g.add_edge("writer", "checks")
    g.add_edge("checks", "critic")
    g.add_conditional_edges("critic", route_after_critic, ["consolidator", "writer", "assembler"])
    g.add_edge("assembler", END)
    return g.compile()
