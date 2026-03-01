# ─── Evolved Rust source ─────────────────────────────────────────────────────
#
# This is the ONLY file DeepEvolve modifies.
# It contains the Rust implementation as a single Python string.
#
# HOW TO MAKE CHANGES:
#   Use SEARCH/REPLACE diffs targeting Rust code INSIDE the triple-quoted string.
#   The SEARCH block must match the existing Rust code exactly (indentation included).
#   Do NOT modify anything outside the triple-quoted string.
#   Do NOT add a second RUST_CODE = assignment.
#
# Example diff:
#   <<<<<<< SEARCH
#       let score = (best_end as f64) * weight;
#   =======
#   // >>> DEEPEVOLVE-BLOCK-START: slack-weighted priority
#       let slack = (deadline as f64 - best_end as f64).max(0.0);
#       let score = (best_end as f64) * weight / (1.0 + 0.1 * slack);
#   // <<< DEEPEVOLVE-BLOCK-END
#   >>>>>>> REPLACE

RUST_CODE = """__RUST_CODE__"""
