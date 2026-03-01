from __future__ import annotations

import asyncio
import logging
from rich.console import Console
from datetime import datetime

from agents import Agent, WebSearchTool, Runner
from agents.tracing import gen_trace_id, trace, custom_span
from agents.model_settings import ModelSettings

from database import Program
from utils.datatypes import (
    ReportData,
    IdeaData,
    is_litellm_model,
    WebSearchPlan,
    WebSearchItem,
    ReflectionPlan,
    reasoning_models,
)
from utils.format import format_metrics_safe

logger = logging.getLogger(__name__)

console = Console()

INSPIRATION_TEMPLATE = """### Inspiration {inspiration_number}
- Research Idea : {idea}
- Performance: {performance}
"""

PLANNER_INSTRUCTIONS = """You are a research strategist planning searches for genuinely novel algorithm ideas.

The problem is job scheduling makespan minimisation - at its core a critical-path problem on a disjunctive
graph. The existing algorithm already has strong local search (tabu, iterated greedy, N5 moves, VND) and
good construction heuristics (NEH, adaptive dispatching rules, UCB1 bandit). Searching for "better tabu" or
"improved NEH" will not produce anything useful.

The goal is to find ideas that are structurally different: new ways of thinking about what the search is doing,
or techniques from other fields whose underlying mathematics could transfer here.

When planning searches, ask yourself: what other problems share the same mathematical structure as
critical-path minimisation on a constrained graph? What fields have developed powerful techniques for
escaping local optima on combinatorial landscapes? What does the scheduling literature NOT cite?
Consider fields like compiler optimisation, network design, molecular simulation, cache algorithms,
epidemiological modelling, auction theory, coding theory, and others - the connection does not need to be
obvious, it just needs to be real.

You will be told whether progress is early or mature:
- Early: favour ideas where the transfer is concrete and the implementation is bounded in complexity.
- Mature: favour the most structurally radical ideas even if implementation is harder.

Produce 7-10 search queries. For each, explain:
(a) what field or technique you are targeting,
(b) why you believe it has not been applied to this problem,
(c) what the specific transfer mechanism might be.
At least half the queries must search outside scheduling and combinatorial optimisation literature entirely.
Include year ranges (2019-2026) to surface recent work.
"""

REFLECTION_INSTRUCTIONS = """
You are a critical reviewer assessing a proposed algorithm idea for job scheduling makespan minimisation.
Be concise and direct. Your job is to catch problems before implementation, not to praise.

Ask yourself four things:

Is this genuinely new? The algorithm already has NEH, N5 tabu, iterated greedy, VND, adaptive dispatching,
UCB1 bandit, machine reassignment moves, and learned job/machine biases. If the idea is a variant or
combination of these, it is not new - flag it and ask for something structurally different.

Is the cross-domain transfer real or superficial? A "physics-inspired" idea that is actually just simulated
annealing with a different cooling schedule, or a "biology-inspired" idea that is just ACO with renamed
variables, is not a cross-domain transfer. The mechanism from the source domain must be doing genuine
work that the scheduling literature has not exploited.

Is the complexity reasonable? TIG has no time limit - the solver runs until it returns a solution.
What matters is that new data structures do not grow unboundedly (e.g. O(n^2) in total_ops without a
size cap), and that the algorithm terminates. Flag anything that looks like an infinite loop or
exponential blowup.

Is the implementation path clear? Could a developer implement this in Rust using only std, anyhow, rand,
serde_json, tig_challenges, without needing additional research? If pseudocode is missing or hand-wavy,
ask for specific data structures and loop logic.

If the idea passes all four, say so briefly and ask nothing. If any fails, generate 1-3 specific follow-up
search queries that would resolve the gap - include the technique name, domain, and year range.
"""

SEARCH_INSTRUCTIONS = (
    "You are a research assistant. Given a search term, you search the web for that term and "
    "produce a concise summary of the results. The summary must be 2-3 paragraphs and less than 300 "
    "words. Capture the main points. Write succinctly, no need to have complete sentences or good "
    "grammar. This will be consumed by someone synthesizing a report for a new idea, so its vital you capture the "
    "essence and ignore any fluff. Do not include any additional commentary other than the summary "
    "itself."
)

WRITER_INSTRUCTIONS = """You are an algorithm inventor writing a research report for a developer who will implement your idea in Rust.

The problem is job scheduling makespan minimisation - minimising the length of the longest path through a
disjunctive graph of operations with precedence and machine-exclusion constraints. The existing solver is
already strong: it has NEH, N5 tabu, iterated greedy, VND, critical-path local search, machine reassignment,
adaptive dispatching rules, UCB1 bandit, and learned job/machine biases. The search space is well-explored
by standard metaheuristics. You are looking for something structurally different.

You will receive search results, prior attempts, and a progress score. Use them to find the best single idea
to implement next. Think carefully about what the search results reveal that is NOT in the existing codebase.

Structure your report as follows:

**What the search found**
Briefly summarise 2-4 findings from the search results that are relevant and potentially novel for this
problem. For each, state what field it comes from and what its core mechanism is.

**Ideas**
Propose 4-6 candidate ideas. For each write one paragraph covering: what it does, where the idea originates,
why it has not been used in scheduling before, and whether it terminates and produces a valid schedule.

For each idea, also state explicitly whether it is a REPLACEMENT or an ADDITION:
- REPLACEMENT: it covers the same phase or decision as an existing component, and is theoretically
  superior - name the specific function(s) it would replace and why.
- ADDITION: it addresses a phase or decision type that the codebase has no answer for at all - name
  the gap it fills.
Ideas that are additions need stronger justification. The algorithm should not grow by accumulation.

Score each: Originality (0-10, where 10 = not in scheduling literature), Runtime-safety (0-10, where 10 =
provably O(n) or O(n log n) per instance with a natural exit point), Impact (0-10).
Do not propose ideas with Originality below 6 or Runtime-safety below 5.

**Selected idea**
Pick the idea with the best combined score given the progress stage:
- Early progress: weight Runtime-safety and Originality equally, accept lower Impact.
- Late progress: weight Originality and Impact, accept Runtime-safety of 6+.
Prefer REPLACEMENT ideas over ADDITION ideas at equal scores - a leaner algorithm that does one thing
well beats a bloated one that does five things poorly.

Write a detailed technical description of the selected idea:
- Name the source technique and cite it.
- State clearly: REPLACEMENT (of what, and why it is better) or ADDITION (what gap it fills).
- If a replacement: describe exactly which existing function(s) are removed or bypassed, and confirm
  the new code takes over their full responsibility within the solve budget.
- Describe the exact mapping: what is the state? what is a move? what is the cost signal?
- Write concrete pseudocode showing the main loop, data structures, and key computations.
- State which Rust file(s) change and roughly how many lines are added vs removed.
- Confirm the algorithm terminates and cannot produce an infinite loop or unbounded data structure growth.
- Explain precisely what makes this different from the existing tabu / ILS / construction machinery.

The report should be 400-700 words. Pseudocode must be specific enough to implement directly. High-level
hand-waving ("use reinforcement learning to guide the search") is not acceptable - name the data structure,
the update rule, and the decision it drives.
"""


USER_TEMPLATE = """
## User Query
{query}

## Research Problem
{problem}

## Starting Research Idea
{starting_point}

## Idea Evolution History
{idea_evolution}

## Research Progress
{evolution_progress}

## Previous Inspirations
{inspirations}
"""

PAPER_READER_INSTRUCTIONS = """
You are a paper reader. You will be provided with a title of the idea with the content.

If the content is an online link, your task is to search the paper online and summarize the core ideas of the paper.

If the content is the description of the idea, your task is to read the description and summarize the core ideas of the idea.

You may be provided supplmentary information about the idea, such as the code, the implementation notes, the pseudocode, etc.
"""

REFLECTION_CONTENT = """
Review the proposed idea critically before implementation. Check five things:

1. Is it genuinely new? The codebase already has: NEH insertion, N5 tabu with block identification,
   iterated greedy, VND, adjacent-swap hill-climb, UCB1 bandit, adaptive dispatching rules (9 types),
   critical-path local search, machine reassignment moves, greedy reassign pass, learned job/machine biases,
   Taillard acceleration, and SA-restart. If the idea is a variant of any of these, reject it and ask for
   something structurally different.

2. Is the cross-domain transfer genuine? Does the mechanism from the source field actually do something the
   existing machinery does not? Or is it the same algorithm with different vocabulary?

3. Replace or add? If the idea covers the same solve phase as something already in the codebase (local
   search improvement, construction, perturbation, operator selection), it must explicitly replace the
   existing code - not run alongside it. If the report proposes an addition where a replacement is
   warranted, flag it and ask which existing component gets removed and why.

4. Does it terminate and stay correct? TIG has no time limit - the solver runs until it returns.
   Does the pseudocode have a natural exit point (bounded loops, no unbounded recursion)?
   Could it produce an infeasible schedule (constraint violation)? An invalid solution scores 0
   and stops the entire test run - correctness is more critical than speed.

5. Is it implementable as written? Could a developer write this in Rust using only std, anyhow, rand,
   serde_json, tig_challenges without needing to look anything up? If pseudocode has gaps or assumes
   libraries that are unavailable, flag them.

If all five pass, say so in one sentence and do not suggest any changes.

If checks 1 or 2 fail (not genuinely new, or cross-domain transfer is superficial): DO NOT try to
patch the same idea. Reject it outright and propose 2-3 follow-up search queries that explore a
COMPLETELY DIFFERENT domain or mechanism - not a refinement of the rejected idea. The follow-up
queries must target a domain not yet tried (e.g. if dual-ascent/auction was rejected, search for
something from compiler register allocation, RNA secondary structure, epidemiological spreading,
cache replacement policy, or queueing network decomposition instead).

If checks 3, 4, or 5 fail (wrong scope, termination risk, or implementation gap): write 1-2 specific
follow-up queries to resolve only that gap, keeping the core idea intact.

Be direct and brief. One sentence per check that fails.
"""


def _model_name(name: str) -> str:
    """Prefix Claude/LiteLLM models with 'litellm/' for the Agents SDK router."""
    if is_litellm_model(name) and not name.startswith("litellm/"):
        return f"litellm/{name}"
    return name

def _model_settings(name: str, reasoning_effort: str, tool_choice: str | None = None) -> ModelSettings:
    """Return appropriate ModelSettings - skip reasoning param for LiteLLM models."""
    kwargs = {}
    if tool_choice:
        kwargs["tool_choice"] = tool_choice
    if name in reasoning_models:
        kwargs["reasoning"] = {'effort': reasoning_effort}
    return ModelSettings(**kwargs)


class ResearcherAgent:
    def __init__(
        self,
        planner: str = "o3-mini",
        searcher: str = "gpt-4o",
        writer: str = "o3-mini",
        reasoning_effort: str = 'medium',
    ):
        self.planner_agent = Agent(
            name="Planner Agent",
            instructions=PLANNER_INSTRUCTIONS,
            model=_model_name(planner),
            output_type=WebSearchPlan,
            model_settings=_model_settings(planner, reasoning_effort),
        )
        self.reflection_agent = Agent(
            name="Reflection Agent",
            instructions=REFLECTION_INSTRUCTIONS,
            model=_model_name(planner),
            output_type=ReflectionPlan,
            model_settings=_model_settings(planner, reasoning_effort),
        )
        self.search_agent = Agent(
            name="Search Agent",
            instructions=SEARCH_INSTRUCTIONS,
            tools=[WebSearchTool()],
            model=_model_name(searcher),
            model_settings=_model_settings(searcher, reasoning_effort, tool_choice="required"),
        )
        self.writer_agent = Agent(
            name="Writing Agent",
            instructions=WRITER_INSTRUCTIONS,
            model=_model_name(writer),
            output_type=ReportData,
            model_settings=_model_settings(writer, reasoning_effort),
        )
        self.reader_agent = Agent(
            name="Paper Reader Agent",
            instructions=PAPER_READER_INSTRUCTIONS,
            tools=[WebSearchTool()],
            model=_model_name(searcher),
            output_type=IdeaData,
            model_settings=_model_settings(searcher, reasoning_effort),
        )
        self.search_time_bias = False
        self.problem_name = 'NA'

    def update_topic(
        self, query: str, problem_name: str, problem_description: str, search_time_bias: bool = False
    ):
        self.query = query
        self.problem_name = problem_name
        self.problem_description = problem_description
        self.search_time_bias = search_time_bias

    async def read_paper(self, title: str, content: str, supplementary_info: str = None) -> IdeaData:
        query = f"title: {title} \ncontent: {content}"
        if supplementary_info is not None:
            query += f"\n supplementary_info: {supplementary_info}"
        result = await Runner.run(
            self.reader_agent,
            query,
        )
        return result.final_output_as(IdeaData)

    async def run(
        self,
        program: Program,
        inspirations: list[Program],
        trace_id: str = None,
        max_reflection_times: int = 1,
        max_generations: int = 10,
    ) -> tuple[str, list, list, str]:
        """
        Execute the research process from planning to report generation.

        Args:
            query: The research question to investigate
            idea_evolution: Evolution history of the idea
            evolution_progress: Current evolution progress/research stage
            trace_id: Optional trace identifier for logging

        Returns:
            Tuple containing report, related work, new ideas, and structured framework
        """
        idea_evolution = program.evolution_history
        evolution_progress = (
            len(program.evolution_history) / max_generations * 100
        )
        evolution_progress = f"{evolution_progress:.2f}%"
        if len(idea_evolution) > 0:
            idea_evolution = " -> ".join(
                [f"[{i}] {idea.description}" for i, idea in enumerate(idea_evolution)]
            )
        else:
            idea_evolution = "Initial idea"

        inspiration_str = ""
        for idx in range(len(inspirations)):
            performance_str = format_metrics_safe(inspirations[idx].metrics)
            inspiration_str += INSPIRATION_TEMPLATE.format(
                inspiration_number=idx,
                idea=inspirations[idx].idea,
                performance=performance_str,
            )
        if inspiration_str == "":
            inspiration_str = "No prior inspirations."

        if trace_id is None:
            trace_id = gen_trace_id()
        logger.info(f"Starting deep research with trace_id: {trace_id}")

        user_input = USER_TEMPLATE.format(
            query=self.query,
            problem=self.problem_description,
            starting_point=program.idea.description,
            idea_evolution=idea_evolution,
            evolution_progress=evolution_progress,
            inspirations=inspiration_str,
        )

        # console.print("[bold blue]User Input of the Researcher Agent[/bold blue]")
        # console.print(user_input)
        # console.print()

        last_input = None
        all_search_plans = []
        all_search_results = []
        all_reports = []
        with trace(
            f"DeepEvolve_{self.problem_name}",
            metadata={"query": self.query[:500]},
            trace_id=trace_id,
            disabled=False,
        ):
            logger.info(f"Performing Deep Research ...")
            for ref_idx in range(max_reflection_times + 1):

                if ref_idx == 0 or last_input is None:
                    search_plan = await self._plan_searches(user_input)
                    all_search_plans.append(search_plan)
                else:
                    reflection_result = await self._reflection(user_input, last_input)
                    if reflection_result.is_sufficient:
                        break
                    else:
                        console.print(
                            f"[bold red]Reflection {ref_idx}: current report is not sufficient because {reflection_result.knowledge_gaps}, generating follow-up queries[/bold red]"
                        )
                        search_plan = WebSearchPlan(
                            searches=reflection_result.follow_up_queries
                        )
                        all_search_plans.append(search_plan)

                search_results = await self._perform_searches(search_plan)
                all_search_results.append(search_results)
                report_result, last_input = await self._write_report(
                    user_input, search_results, last_input=last_input
                )
                all_reports.append(report_result)

        logger.info("Research completed successfully")
        return all_search_plans, all_search_results, all_reports

    async def _plan_searches(self, user_input: str) -> WebSearchPlan:
        logger.info(f"Starting search planning for query: {self.query} ...")

        if self.search_time_bias:
            today = datetime.now().strftime("%Y-%m-%d")
            user_input += f"\n*Important: Today's date is {today}. Prioritize recent search results.*\n"

        result = await Runner.run(
            self.planner_agent,
            user_input,
        )

        logger.info(
            f"Completed search planning: {len(result.final_output.searches)} searches identified"
        )
        return result.final_output_as(WebSearchPlan)

    async def _reflection(self, user_input: str, last_input: list) -> WebSearchPlan:
        new_content = f"""
        Given the following user input, please identify any issues or gaps in the research report:
        {user_input}

        Here are the reflection points you should check about the new idea:
        {REFLECTION_CONTENT}

        If you think the new idea is good enough, do not ask any follow-up questions. Otherwise, write one or more follow-up queries that include relevant context for further investigation.
        """

        reflection_input = last_input + [{"role": "user", "content": new_content}]
        
        try:
            reflection_plan = await Runner.run(
            self.reflection_agent,
                reflection_input,
            )
            return reflection_plan.final_output_as(ReflectionPlan)

        except Exception as e:
            console.print(f"[bold red]Error in reflection: {e}[/bold red]")
            console.print(f"[bold red]Reflection input: {reflection_input}[/bold red]")
            raise e
        
    async def _perform_searches(self, search_plan: WebSearchPlan) -> list[str]:
        with custom_span("Search the web"):
            logger.info(
                f"Starting web searches, total: {len(search_plan.searches)} ..."
            )
            num_completed = 0
            tasks = [
                asyncio.create_task(self._search(item, i + 1))
                for i, item in enumerate(search_plan.searches)
            ]
            results = []
            for task in asyncio.as_completed(tasks):
                result = await task
                if result is not None:
                    results.append(result)
                num_completed += 1
            logger.info(
                f"Completed {len(results)}/{len(search_plan.searches)} searches successfully"
            )
            return results

    async def _search(self, item: WebSearchItem, source_id: int) -> str | None:
        input = f"Search term: {item.query}\nReason for searching: {item.reason}"
        try:
            result = await Runner.run(
                self.search_agent,
                input,
            )
            return str(result.final_output)
        except Exception:
            return None

    async def _write_report(
        self, user_input: str, search_results: list[str], last_input: list = None
    ) -> ReportData:
        logger.info("Starting report writing ...")

        summaries_block = "\n\n---\n\n".join(search_results)

        if last_input is not None:
            new_content = f"""
            Please review and reflect on the report and the new idea based on below reflection points:
            {REFLECTION_CONTENT}

            and more search results on these reflection points:
            {summaries_block}
            
            You can revise the current idea, add new ones, or select a different top idea.
            Important: Edit only within the existing report. Keep its full structure and format unchanged.
            Do not add introductory phrases like "In reviewing the report and the proposed idea, several reflections arise..."
            Retain every detail; focus on strengthening the report, not generating a new report or a reflection document.
            """
            user_input = last_input + [{"content": new_content, "role": "user"}]
        else:
            user_input += f"\n\n ## Search results\n{summaries_block}"

        result = await Runner.run(
            self.writer_agent,
            user_input,
        )
        
        logger.info("Completed report writing")
        return result.final_output_as(ReportData), result.to_input_list()