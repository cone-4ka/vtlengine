"""Reproductions of three faults with component parameters and join clauses.

1. substr of a string literal with a position taken from a component raised AttributeError
   ('DataComponent' object has no attribute 'value').
2. substr / instr with a parameter computed from the operand itself (substr(tp, length(tp), 1))
   built a frame with repeated column names and raised "The truth value of a Series is ambiguous";
   an integer literal next to such a parameter was turned into a string.
4. instr of a string literal with a Component parameter (instr("…", c, n)) raised the same AttributeError: a scalar
   operand with Component parameters is now broadcast to the Component's rows.
3. In a calc clause of a join, a Component named like a Data Set of the script (the operand d15 with
   its Measure d15) was read as the Data Set, and the assignment failed with 'NoneType' object has
   no attribute 'name'.

Run: PYTHONPATH=src python3 synthetic/repro_component_params.py
"""
import pandas as pd

import vtlengine


def structure(name, ids):
    return {"name": name, "DataStructure": [
        *({"name": i, "type": "String", "role": "Identifier", "nullable": False} for i in ids),
        {"name": "obs_value", "type": "Number", "role": "Measure", "nullable": True}]}


DATA = {"X": pd.DataFrame({"geo": ["a", "a", "b"], "tp": ["2020-01", "2020-05", "2020-11"], "obs_value": [1.0, 2.0, 3.0]}),
        "Q": pd.DataFrame({"geo": ["a", "a"], "tp": ["2020-Q1", "2020-Q2"], "obs_value": [1.0, 2.0]}),
        "Y": pd.DataFrame({"geo": ["a", "b", "a"], "tp": ["2015", "2015", "2016"], "obs_value": [4.0, 5.0, 6.0]})}
STRUCTURES = {"datasets": [structure(name, ["geo", "tp"]) for name in DATA]}
CASES = [
    ('R <- X[calc q := instr("2020-012020-05", tp, 1)];', [[1, 8, 0]]),
    ('R <- X[calc q := substr("111222333444", cast(substr(tp, 6, 2), integer), 1)];', [["1", "2", "4"]]),
    ("R <- Q[calc q := substr(tp, length(tp), 1)];", [["1", "2"]]),
    ('R <- Q[calc q := instr(tp, "Q", length(tp) - 3, 1)];', [[6, 6]]),
    ('d15 := Y[sub tp = "2015"][rename obs_value to d15]; R <- inner_join(Y as A, d15 as B calc q := obs_value * d15);',
     [[16.0, 25.0, 24.0]]),
]
for script, (expected,) in CASES:
    got = vtlengine.run(script=script, data_structures=STRUCTURES, datapoints=DATA)["R"].data
    values = list(got.sort_values(["geo", "tp"])["q"])
    assert sorted(values) == sorted(expected), (script, values)
    print("ok", script)
