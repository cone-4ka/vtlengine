# Synthetic testing of vtlengine

Generated VTL programs checked without an external oracle and against an independent reference.

- `gen.py` — chains of dataset transformations: all pairs and a sample of triples of filters, calc, aggregations,
  analytics, joins, union, exists_in and dataset operations; `branch_cases` — if branches with parameterized operators.
- `run.py` — metamorphic checks: the same chain as steps, rows permuted, a pandas index other than 0..n-1, inside a
  define operator, the main Measure under another name (int_var, bool_var), branches computed by a separate calc.
  Progress is appended to a jsonl file and resumed.
- `ref.py` — a reference in pure Python (no pandas) after the VTL 2.1 Reference Manual; points the manual leaves open
  are flags, and every combination of them is accepted.
- `refcheck.py` — vtlengine against the reference.
- `repro_substr_if.py` — a reproduction of one fault.

Run: `PYTHONPATH=src python3 synthetic/run.py`, then `PYTHONPATH=src python3 synthetic/refcheck.py`.
