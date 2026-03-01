# Evolution Ideas & Instructions

This file is read by run.py before every evolution run and injected into the
AI models as part of their briefing. Edit this before launching a run.

The file has two sections:
  1. FIXED CONTEXT  - problem facts, constraints, Rust rules (do not change often)
  2. YOUR IDEAS     - your specific thoughts for THIS run (change every run)

---

## SECTION 1: FIXED CONTEXT (update when facts change)

### The Challenge

Schedule 50 jobs on 30 machines to minimise makespan (total completion time).
- Each job has ~30 operations in sequence
- Each operation can run on multiple eligible machines with different processing times
- Must respect precedence (sequential operations per job) and no machine overlaps
- Quality metric: `1.0 - make_span / greedy_makespan` (higher is better, fixed-point 6dp)
- The algorithm calls `save_solution()` during execution - the LAST saved solution is evaluated

### 5 Track Types

| Track           | avg_flex | flow_structure | Description                        |
|-----------------|----------|----------------|------------------------------------|
| flow_shop       | 1.0      | sequential     | Classic flow shop, strict routing  |
| hybrid_flow_shop| 3.0      | sequential     | Parallel machines at each stage    |
| job_shop        | 1.0      | 40% random     | Job shop with random precedence    |
| fjsp_medium     | 3.0      | 40% random     | Flexible job shop, moderate flex   |
| fjsp_high       | 10.0     | fully random   | Extreme flexibility, chaotic       |

---

### Critical Rust Rules (NEVER violate)

1. Only these crates are available: `anyhow`, `rand`, `serde_json`, `tig_challenges`
   No external ML or graph crates (linfa, petgraph, ndarray etc.) - they will not compile.

2. ASCII only in Rust source - no Unicode characters anywhere in comments or strings.

3. No duplicate function names in the same file.

4. All Rust comments use `//` not `#`. Writing `# comment` is a hard syntax error in Rust.
   `#[inline]`, `#[derive(...)]` etc. are attributes - leave them exactly as-is.

5. Any new loop that could run long MUST have a bounded iteration count - TIG has no
   wall-clock time limit but unbounded loops will stall the solver permanently.

---

### Evolution Principles

- ONE focused change per iteration - do not rewrite everything
- Build on successes - if something improved a track, understand WHY and refine
- Quality through intelligence, not computation - smarter decisions, not more iterations
- Never increase iteration counts or add exponential complexity
- Valid schedules are non-negotiable - always call save_solution with a feasible result

---

## SECTION 2: YOUR IDEAS FOR THIS RUN

Edit this section before every run. The more specific you are, the better the AI performs.

### Target algorithm
- Algorithm: [FILL IN algorithm name and type, e.g. `my_algo` (modular) or `dispatching_rules` (single-file)]
- File being evolved: [FILL IN e.g. `fjsp_high.rs` or `infra.rs` or full algorithm]
- Tracks being tested: [FILL IN e.g. fjsp_high only, or all 5]

### Algorithm summary
[FILL IN a brief description of what the algorithm currently does:
- What construction method it uses
- What local search / improvement phases it has
- Any hyperparameters it accepts
- Any track-specific branching]

### What is limiting performance
[FILL IN what you think is holding back quality:
1. ...
2. ...
3. ...]

### Specific ideas to try
[FILL IN concrete algorithmic ideas for THIS run:
1. ...
2. ...
3. ...]

### What success looks like
[FILL IN your target, e.g. "Beat baseline on at least 2 of the 5 tracks" or "Improve fjsp_high by >1%"]
