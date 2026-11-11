"""vtlengine 1.9.7: substr внутри ветки if-then-else с длиной-выражением молча берёт не те знаки
(«9 сентября» → «9 сентяб» вместо «сентября»). Запуск: PYTHONPATH=<vtlengine> python3 repro_substr_if.py"""
import pandas as pd, vtlengine
D = pd.DataFrame({"k": ["a", "b"], "rs": ["9 сентября", "16 декабря"]})
S = {"datasets": [{"name": "D", "DataStructure": [{"name": "k", "type": "String", "role": "Identifier", "nullable": False},
                                                  {"name": "rs", "type": "String", "role": "Measure", "nullable": True}]}]}
for prog in ['R <- D[calc sp := substr(rs, 2, 1)][calc m := if sp = " " then substr(rs, 3, length(rs) - 2) else substr(rs, 4, length(rs) - 3)];',
             'R <- D[calc sp := substr(rs, 2, 1)][calc m := if sp = " " then substr(rs, 3, 8) else substr(rs, 4, 7)];',
             'R <- D[calc m := substr(rs, 3, length(rs) - 2)];']:
    print(prog[:90], vtlengine.run(script=prog, data_structures=S, datapoints={"D": D})["R"].data["m"].tolist())
