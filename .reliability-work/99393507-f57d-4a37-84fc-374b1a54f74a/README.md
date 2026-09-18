# Broken counter fixture

`increment` currently returns `n - 1`. Tests expect `n + 0` wait — they expect `n+1` semantics via `increment(1)==2`.
