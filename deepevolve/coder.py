from __future__ import annotations

import logging
import re
from rich.console import Console

from agents import Agent, Runner
from agents.tracing import gen_trace_id, trace
from agents.model_settings import ModelSettings
from black import format_str, Mode

from database import Program
from utils.code import apply_diff, parse_evolve_blocks, extract_diffs
from utils.datatypes import IdeaData, reasoning_models, is_litellm_model
from utils.format import format_metrics_safe

logger = logging.getLogger(__name__)

console = Console()

# Rust file section header as written by algorithm_code.py (old format)
_RUST_FILE_HEADER = re.compile(r'^# === .+\.rs ===$', re.MULTILINE)
# RUST_FILES dict assignment pattern used in neuralnet algorithm_code.py
_RUST_FILES_ASSIGN = re.compile(r'(RUST_FILES\[".+?"\]\s*=\s*r""")(.*?)(""")', re.DOTALL)
# RUST_CODE single-variable pattern used in JSS deepevolve_interface.py
# Matches `RUST_CODE = """` but NOT `RUST_CODE_ORIGINAL = """` (negative lookahead on _[A-Z])
_RUST_CODE_ASSIGN = re.compile(r'((?:^|\n)RUST_CODE(?![_A-Z])\s*=\s*""")(.*?)(""")', re.DOTALL)


def _fix_rust_section(section: str) -> str:
    """Apply Rust comment fixes to a single section of Rust/CUDA code."""
    # Pass 1: fix DEEPEVOLVE block markers written with ### instead of //
    section = re.sub(
        r'^(\s*)###\s*(>>>|<<<)(\s*DEEPEVOLVE.*)$',
        lambda m: m.group(1) + '//' + m.group(2) + m.group(3),
        section,
        flags=re.MULTILINE,
    )

    # Pass 2: remove stray DEEPEVOLVE markers that appear OUTSIDE r"""...""" strings
    # (i.e. at Python scope) - these cause SyntaxError
    section = re.sub(
        r'^(\s*)//\s*(>>>|<<<)\s*DEEPEVOLVE.*$\n?',
        '',
        section,
        flags=re.MULTILINE,
    )

    # Pass 3: restore mangled attributes: `// [foo]` -> `#[foo]`
    section = re.sub(
        r'^(\s*)//\s*(\[.*)$',
        lambda m: m.group(1) + '#' + m.group(2),
        section,
        flags=re.MULTILINE,
    )

    # Pass 4: convert remaining stray Python-style `# text` -> `// text`
    # Negative lookahead protects #[ and #! (attribute macros)
    section = re.sub(
        r'^(\s*)#(?!\[|!)(.*)$',
        lambda m: m.group(1) + '//' + m.group(2),
        section,
        flags=re.MULTILINE,
    )
    return section


def _sanitise_rust_comments(code: str) -> str:
    """
    Fix LLM mistakes that cause Rust/CUDA compile errors.

    Handles two formats:
    1. Old format: sections separated by `# === foo.rs ===` headers
    2. New format: RUST_FILES["foo.rs"] = r\"\"\"...\"\"\" assignments in algorithm_code.py

    Also strips stray DEEPEVOLVE markers placed at Python scope (outside r\"\"\"...\"\"\").
    """
    # First strip any DEEPEVOLVE markers sitting at Python scope (between assignments)
    # These are lines like `// >>> DEEPEVOLVE-BLOCK-START: ...` outside any string
    # Strategy: process RUST_FILES assignments, fix content inside strings,
    # then strip any // >>> or // <<< DEEPEVOLVE lines remaining at Python scope.

    # Handle RUST_CODE = """...""" format (JSS deepevolve_interface.py)
    if _RUST_CODE_ASSIGN.search(code):
        def fix_rust_code_content(m: re.Match) -> str:
            prefix  = m.group(1)   # (newline+)RUST_CODE = """
            content = m.group(2)   # the Rust code inside
            suffix  = m.group(3)   # """
            fixed = _fix_rust_section(content)
            if fixed != content:
                logger.warning("sanitise_rust_comments: fixed Rust comment/marker syntax in RUST_CODE string")
            return prefix + fixed + suffix

        cleaned = _RUST_CODE_ASSIGN.sub(fix_rust_code_content, code)

        # Strip any stray DEEPEVOLVE lines remaining at Python scope
        cleaned = re.sub(
            r'^[ \t]*//\s*(>>>|<<<)\s*DEEPEVOLVE[^\n]*\n?',
            '',
            cleaned,
            flags=re.MULTILINE,
        )
        if cleaned != code:
            logger.warning("sanitise_rust_comments: cleaned stray DEEPEVOLVE markers at Python scope in RUST_CODE file")
        return cleaned

    # Handle RUST_FILES["..."] = r"""...""" format
    if _RUST_FILES_ASSIGN.search(code):
        def fix_rust_files_content(m: re.Match) -> str:
            prefix = m.group(1)   # RUST_FILES["..."] = r"""
            content = m.group(2)  # the Rust/CUDA code inside
            suffix = m.group(3)   # """
            fixed = _fix_rust_section(content)
            if fixed != content:
                logger.warning("sanitise_rust_comments: fixed comment/marker syntax in RUST_FILES string")
            return prefix + fixed + suffix

        code = _RUST_FILES_ASSIGN.sub(fix_rust_files_content, code)

        # Strip any remaining stray // >>> DEEPEVOLVE lines at Python scope
        cleaned = re.sub(
            r'^[ \t]*//\s*(>>>|<<<)\s*DEEPEVOLVE[^\n]*\n?',
            '',
            code,
            flags=re.MULTILINE,
        )
        if cleaned != code:
            logger.warning("sanitise_rust_comments: removed stray DEEPEVOLVE markers at Python scope")
        return cleaned

    # Handle old # === foo.rs === header format
    sections = _RUST_FILE_HEADER.split(code)
    headers = _RUST_FILE_HEADER.findall(code)

    if not headers:
        return code

    result_parts = [sections[0]]  # Python preamble, untouched
    for header, section in zip(headers, sections[1:]):
        original = section
        section = _fix_rust_section(section)
        if section != original:
            logger.warning("sanitise_rust_comments: fixed comment/marker syntax errors in Rust section")
        result_parts.append(header)
        result_parts.append(section)

    return "".join(result_parts)


CODER_INSTRUCTIONS = """You are a researcher with strong software engineering skills, improving algorithmic Rust code.

Your task:
You will receive a research idea and the current rust_code.py file. This file contains one Python variable:
    RUST_CODE = \"\"\"
    ... full Rust source code ...
    \"\"\"

You must return the COMPLETE updated rust_code.py file with your improvement applied to the Rust code inside the string. Return nothing else - just the complete file wrapped in a Python code block.

OUTPUT FORMAT - return the entire file like this:
```python
RUST_CODE = \"\"\"
... full improved Rust source ...
\"\"\"
```

Guidelines:
1. Make ONE focused change that implements the research idea. Identify which phase it targets
   (construction, local search, perturbation, rule selection) and change only that.

2. REPLACE existing code, do not accumulate. If the idea is a better local search, replace the
   existing one - do not add a second one after it. Remove dead code and unreachable branches.
   NEVER remove or alter existing hyperparameter structs, fields, or parsing logic - the algorithm
   is evaluated with specific hyperparameters and removing them will break evaluation.

3. Verify new code is actually reached: if you add a function, confirm it is called. Walk the
   execution path mentally to confirm the change fires on a normal instance.

4. Ensure all modified code is correct: function signatures, parameter types, call sites.

RUST SYNTAX RULES (violating these causes immediate compile failure):
   - All comments use `//` not `#`. Writing `# some text` is a hard syntax error in Rust.
   - `#[inline]`, `#[allow(...)]`, `#[derive(...)]` are Rust attributes - leave them exactly as-is.
   - `use super::types::*;` and `use super::infra::*;` are already present - do NOT add them again.
   - Allowed crates only: anyhow, rand, serde_json, tig_challenges.
"""

DEBUGGER_INSTRUCTIONS = """You are an expert Rust developer. Your sole job is to fix Rust compiler errors.
The codebase is Rust source code embedded as strings in a Python file.

STEP 1 - READ THE ERRORS IN ORDER. Fix the FIRST error first. Many later errors are cascading
consequences of a single earlier syntax or structural error. Fixing the root cause eliminates them.

STEP 2 - DIAGNOSE before writing any diff. Ask yourself:
  - What is the FIRST error in the list?
  - What line does it point to?
  - What does the surrounding code look like at that line?

NEVER attempt to fix downstream "cannot find function X in scope" errors by adding imports.
Those errors almost always mean a syntax error earlier in the file broke the module structure.
The wildcard imports `use super::types::*;` and `use super::infra::*;` are ALREADY present in every
solver file. Do NOT add them again. Adding duplicate use statements will not fix anything.

CRITICAL - DO NOT TOUCH RUST ATTRIBUTES:
`#[inline]`, `#[allow(...)]`, `#[derive(...)]`, `#![allow(...)]` are Rust attribute macros.
They are NOT Python comments. Do NOT convert them to `// [inline]` or any other form.
Only lines where `#` is followed by plain text (not `[` or `!`) are Python-style comments.
If you accidentally convert `#[inline]` to `// [inline]`, you break the attribute and create
an `unterminated character literal` error. Leave all `#[...]` and `#![...]` lines exactly as-is.

COMMON ROOT CAUSES AND THEIR FIXES:

1. "expected one of `!` or `[`, found `#`"
   Cause: A Python-style `# comment` was written in Rust code. Rust uses `//` for line comments.
   Fix: Replace every `# text` line in the generated code with `// text`.
   This single fix will resolve all the "cannot find function X" errors that follow it, because
   those functions ARE defined - they just become unreachable when the file fails to parse.

2. Borrow checker - cannot borrow as mutable while also borrowed as immutable:
   Cause: holding a live immutable reference into a Vec while also trying to mutate it.
   Fix: Copy the needed value into a local variable first, then mutate.
     // WRONG
     let val = vec[i];
     vec[j].push(val);  // ERROR: vec already borrowed
     // RIGHT
     let val = vec[i];  // usize/u32/bool are Copy - no borrow held
     vec[j].push(val);  // OK now

3. Borrow checker - cannot borrow behind `&` reference:
   Cause: calling a `&mut self` method on something passed as `&T`, or field not declared `mut`.
   Fix: Change parameter to `&mut` or declare variable with `let mut`.

4. Use of moved value:
   Cause: A non-Copy type (Vec, String, struct) used after being moved into a function.
   Fix: Call `.clone()` before the move if you need it again.

5. Mismatched types:
   Fix at the point of mismatch with `as usize`, `as u32`, `.into()`, or correcting the declaration.

6. Unused variable warning treated as error:
   Prefix variable name with `_` or remove it.

You MUST use the exact SEARCH/REPLACE diff format. The SEARCH block must match the existing Rust
code character-for-character, including indentation and line endings.

```
<<<<<<< SEARCH
// exact original Rust code
=======
// DEBUG: <what was wrong and why this fixes it>
// corrected Rust code
>>>>>>> REPLACE
```

Fix only what the first error points to. Do not rewrite surrounding logic. One focused fix.
"""

INSPIRATION_TEMPLATE = """### Inspiration {inspiration_number}
- Research Idea : {idea}
- Performance: {performance}
- Code changes: {code_changes}
"""

# User message template for diff-based evolution
DIFF_CODE_TEMPLATE = """
User query: {query}
Research problem: {problem}

Inspirations:
{inspirations}

Current idea:
{current_idea}

Evolution history:
{idea_evolution}

Pseudocode:
{pseudocode}

Implementation notes:
{implementation_notes}

Current performance:
{current_performance}

Task:
Implement the research idea above as a focused improvement to the Rust algorithm.
Return the COMPLETE updated rust_code.py file (the file containing RUST_CODE = \"\"\"...\"\"\").
Do NOT return diffs, patches, or partial snippets - return the entire file.

Current rust_code.py (and supporting files):
```{language}
{current_program}
"""

REFLECTION_CONTENT = """
1. Replacement vs accumulation
   - Does the change add new code alongside existing code that covers the same solve phase?
     If yes, this is accumulation - flag it. The new code should replace the old, not run in addition.
   - Is there dead code or unreachable branches left behind from a replacement? Remove them.
   - If the idea is genuinely an addition (fills a gap nothing else covers), is that clearly justified
     by a comment naming the specific gap?

2. Code correctness
   - Are there syntax errors, runtime errors, or inconsistencies in variable names or logic?
   - Are new functions defined AND called? Confirm the execution path reaches the new code.
   - No silent error suppression - bare try/except that simply passes or returns 0 is not acceptable.

3. Solution validity
   - Could the new code produce an infeasible schedule (constraint violation, out-of-bounds index,
     incorrect job ordering)? An invalid solution scores 0 and stops the entire test run.
   - Are new data structures bounded in size? No unbounded growth proportional to total_ops^2.
   - TIG has no time limit - the solver runs until it returns. Correctness matters more than speed.

4. Alignment with the idea
   - Does the implementation actually do what the pseudocode described, or did it silently revert
     to a simpler fallback? Check that the novel mechanism is present and active.

Provide a brief summary of findings. If changes are needed, produce them as a new diff."""


DEBUGGER_TEMPLATE = """
Resolve the following error in a multi-file Python codebase.

An error occurred during execution:
```
{error_message}
```

Below is the code that caused the error:
```{language}
{modified_code}
````

The modification was made to implement the idea:
```json
{idea}
```

Your responsibilities:

- Identify and fix the cause of the error in the modified code.
- Ensure that all involved files and components integrate correctly and run without errors.
- Ensure the code modification do not break the research idea.
- Ensure the new code within the `DEEPEVOLVE` block is reachable in the workflow. New code should be executed as new idea but not suppressed by error handling or cheated by None values.
- If necessary, update function inputs or implementations to ensure consistency.
- If the code depends on a library that is not available, use the standard library instead.

Please analyze the error and return the corrected code using `diff` format.
"""

class CoderAgent:
    def __init__(self, developer: str, debugger: str, reasoning_effort: str = 'medium'):
        def _route(name: str) -> str:
            return f"litellm/{name}" if is_litellm_model(name) and not name.startswith("litellm/") else name

        def _ms(name: str) -> ModelSettings:
            if name in reasoning_models:
                return ModelSettings(reasoning={'effort': reasoning_effort})
            return ModelSettings()

        self.developer = Agent(
            name="Code development agent",
            instructions=CODER_INSTRUCTIONS,
            model=_route(developer),
            model_settings=_ms(developer),
            output_type=str,
        )

        self.debugger = Agent(
            name="Code debugging agent",
            instructions=DEBUGGER_INSTRUCTIONS,
            model=_route(debugger),
            model_settings=_ms(debugger),
            output_type=str,
        )

        self.query = None
        self.problem_description = None
        self.language = None
        self.trace_id = None
        self.problem_name = 'NA'

    def update_topic(self, query: str, problem_name: str, problem_description: str):
        self.query = query
        self.problem_name = problem_name
        self.problem_description = problem_description

    async def debug(
        self, input_code: str, error_message: str,
    ) -> str:
        trace_id = self.trace_id
        if trace_id is None:
            trace_id = gen_trace_id()
            self.trace_id = trace_id

        with trace(f"DeepEvolve_{self.problem_name}", trace_id=trace_id, disabled=False):
            # Only show rust_code.py to the debugger - strip deepevolve_interface.py
            # so the debugger cannot accidentally modify infrastructure code.
            _imarker = "# === deepevolve_interface.py ==="
            if _imarker in input_code:
                debugger_visible_code = input_code.split(_imarker)[0].rstrip()
            else:
                debugger_visible_code = input_code
            debugger_input = DEBUGGER_TEMPLATE.format(
                # query=self.query,
                error_message=error_message,
                modified_code=debugger_visible_code,
                idea=self.idea.model_dump(),
                language=self.language,
            )
            result = await Runner.run(self.debugger, debugger_input)

            logger.info(f"Debugger error message:\n {error_message}")
            logger.info(f"Debugger changes:\n {result.final_output_as(str)}")

            diff_with_text = result.final_output_as(str)
            # Apply diff to the full input_code so the interface section is preserved
            output_code = apply_diff(input_code, diff_with_text)
            output_code = _sanitise_rust_comments(output_code)
            
            try:
                output_code = format_str(output_code, mode=Mode())
            except Exception as e:
                logger.warning(f"Error when formatting code: {e}")
                pass
            return output_code

    async def run(
        self,
        new_idea: IdeaData,
        program: Program,
        inspirations: list[Program],
        trace_id: str = None,
        max_reflection_times: int = 1,
    ) -> str:
        """Run the full code improvement pipeline with research context."""
        if trace_id is None:
            trace_id = gen_trace_id()
        self.trace_id = trace_id
        self.language = program.language
        self.idea = new_idea
        # format new idea
        idea_evolution = program.evolution_history
        if len(idea_evolution) > 0:
            idea_evolution = (
                " -> ".join(
                    [
                        f"[{i}] {idea.description}"
                        for i, idea in enumerate(idea_evolution)
                    ]
                )
                + " -> "
                + new_idea.description
            )
        else:
            idea_evolution = "Initial idea -> " + new_idea.description

        # format inspirations - cap code block content to limit context window usage
        MAX_INSPIRATION_BLOCK_LINES = 80
        inspiration_str = ""
        for idx in range(len(inspirations)):
            performance_str = format_metrics_safe(inspirations[idx].metrics)
            code_changes = parse_evolve_blocks(inspirations[idx].code)
            code_changes_str = ""
            for start_line, end_line, block_content in code_changes:
                lines = block_content.splitlines()
                if len(lines) > MAX_INSPIRATION_BLOCK_LINES:
                    half = MAX_INSPIRATION_BLOCK_LINES // 2
                    truncated = "\n".join(lines[:half]) + f"\n// ... ({len(lines) - MAX_INSPIRATION_BLOCK_LINES} lines truncated) ...\n" + "\n".join(lines[-half:])
                    block_content = truncated
                code_changes_str += f"Line {start_line} to {end_line}: ```{self.language}\n{block_content}```\n"
            inspiration_str += INSPIRATION_TEMPLATE.format(
                inspiration_number=idx,
                idea=inspirations[idx].idea,
                performance=performance_str,
                code_changes=code_changes_str,
            )
        if inspiration_str == "":
            inspiration_str = "No prior inspirations."

        program_code = program.code
        last_input_list = []
        all_diff_text = []
        all_program_code = []
        
        with trace(f"DeepEvolve_{self.problem_name}", trace_id=trace_id, disabled=False):
            logger.info(f"Starting code development ...")
            for ref_idx in range(max_reflection_times + 1):
                if ref_idx > 0:
                    console.print(
                        f"  [dim]↻ Code reflection {ref_idx}/{max_reflection_times}[/dim]"
                    )
                    
                current_performance = format_metrics_safe(program.metrics)
                # Truncate query for the coder to save context tokens - the researcher
                # has already distilled the key idea into pseudocode and description.
                coder_query = self.query[:800] if self.query and len(self.query) > 800 else self.query
                # Only show rust_code.py to the LLM - strip deepevolve_interface.py
                # so the LLM cannot accidentally modify infrastructure code.
                interface_marker = "# === deepevolve_interface.py ==="
                if interface_marker in program_code:
                    llm_visible_code = program_code.split(interface_marker)[0].rstrip()
                else:
                    llm_visible_code = program_code
                code_prompt = DIFF_CODE_TEMPLATE.format(
                    query=coder_query,
                    problem=self.problem_description,
                    inspirations=inspiration_str,
                    current_idea=new_idea.description,
                    idea_evolution=idea_evolution,
                    pseudocode=new_idea.pseudocode,
                    implementation_notes=new_idea.implementation_notes,
                    language=self.language,
                    current_performance=current_performance,
                    current_program=llm_visible_code,
                )

                if ref_idx > 0:
                    # Reflection turn: do NOT resend the full code prompt (which contains the
                    # entire codebase). The conversation history in last_input_list already
                    # has all context. Only append the reflection question to avoid exceeding
                    # the context window.
                    reflection_prompt = (
                        f"Given the previous rust_code.py you returned, please review it and reflect on: {REFLECTION_CONTENT}"
                        f"\n\nIf changes are needed, return the complete updated rust_code.py file."
                    )
                    code_input = last_input_list + [
                        {"content": reflection_prompt, "role": "user"}
                    ]
                else:
                    code_input = last_input_list + [
                        {"content": code_prompt, "role": "user"}
                    ]

                result = await Runner.run(self.developer, input=code_input)
                last_input_list = result.to_input_list()
                diff_with_text = result.final_output_as(str)

                # The LLM returns the complete rust_code.py file.
                # Extract it from a markdown fence if present, otherwise use raw output.
                # Then splice it into program_code replacing only the rust_code.py section,
                # preserving the static deepevolve_interface.py section unchanged.
                fence_match = re.search(r"```(?:python)?\n(.*?)```", diff_with_text, re.DOTALL)
                candidate = fence_match.group(1).strip() if fence_match else diff_with_text.strip()

                if "RUST_CODE" in candidate and '"""' in candidate:
                    rust_code_marker = "# === rust_code.py ==="
                    interface_marker = "# === deepevolve_interface.py ==="
                    if rust_code_marker in program_code and interface_marker in program_code:
                        parts = program_code.split(rust_code_marker, 1)
                        before = parts[0]
                        after_rc = parts[1]
                        if interface_marker in after_rc:
                            interface_part = interface_marker + after_rc.split(interface_marker, 1)[1]
                            program_code = before + rust_code_marker + "\n" + candidate + "\n\n" + interface_part
                        else:
                            program_code = candidate
                    else:
                        program_code = candidate
                else:
                    logger.warning("LLM output does not contain RUST_CODE assignment - keeping parent code.")

                program_code = _sanitise_rust_comments(program_code)
                
                try:
                    program_code = format_str(program_code, mode=Mode())
                except Exception:
                    pass

                all_diff_text.append(diff_with_text)
                all_program_code.append(program_code)

            logger.info(f"Completed code development with {max_reflection_times} reflection rounds.")
            return all_diff_text, all_program_code