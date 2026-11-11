"""Прогон синтетических программ на vtlengine с метаморфными проверками.

Для каждой цепочки gen.cases(): программа вложенным выражением — основа; варианты, которые обязаны дать тот же ответ:
  split — та же цепочка шагами через промежуточные наборы;
  perm  — строки входа переставлены;
  index — у таблицы pandas входа не 0..n-1, а перемешанный индекс (ловушка «молча теряет строки», 07.11);
  udo   — цепочка внутри define operator;
  name:<имя> — главная мера входа названа иначе (int_var, bool_var… — имена, которые движок даёт своим мерам).
Сравнение — по множеству строк: идентификаторы по имени, меры по порядку, числа до 9 значащих.
Падение основы исключением не из vtlengine (IndexError, KeyError…) — сбой движка; SemanticError — программа неверна.

Ход — results.jsonl (дозапись, повтор пропускает сделанное), лог — run.log. SHARD=k/n — доля цепочек.
Запуск: PYTHONPATH=<src vtlengine> python3 run.py [SHARD=k/n, FUZZ_OUT=…, FUZZ_SET=branch]"""
import json, math, os, random, signal, sys, time, traceback
import pandas as pd
import vtlengine
import gen

H = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(H, os.environ.get("FUZZ_OUT", "results.jsonl"))
STEP_SEC = 20

ROWS = [  # крайние значения: пропуск, ноль, отрицательное, ничьи, разная длина рядов
    ("a", "2019", 1.0, 2.0), ("a", "2020", 4.0, 0.0), ("a", "2021", None, 3.0), ("a", "2022", 4.0, 1.0),
    ("b", "2019", 3.0, 3.0), ("b", "2020", 9.0, -1.0), ("b", "2021", -2.0, 2.0),
    ("c", "2020", 3.0, 5.0), ("c", "2021", 0.0, 4.0), ("d", "2021", 2.5, None),
]


class Timeout(Exception):
    pass


def _alarm(*_):
    raise Timeout()


def structure(m):
    return {"datasets": [{"name": "D", "DataStructure": [
        {"name": "geo", "type": "String", "role": "Identifier", "nullable": False},
        {"name": "tp", "type": "String", "role": "Identifier", "nullable": False},
        {"name": m, "type": "Number", "role": "Measure", "nullable": True},
        {"name": "w", "type": "Number", "role": "Measure", "nullable": True}]}]}


def frame(m, order=None, index=None):
    rows = ROWS if order is None else [ROWS[i] for i in order]
    df = pd.DataFrame(rows, columns=["geo", "tp", m, "w"])
    if index is not None:
        df.index = index
    return df


def run(script, m="obs_value", df=None):
    signal.alarm(STEP_SEC)
    try:
        got = vtlengine.run(script=script, data_structures=structure(m), datapoints={"D": frame(m) if df is None else df})
    finally:
        signal.alarm(0)
    return got["R"]


def canon(ds):
    ids = sorted(c.name for c in ds.components.values() if c.role.value == "Identifier")
    ms = [c.name for c in ds.components.values() if c.role.value != "Identifier"]
    rows = []
    for r in ds.data[ids + ms].itertuples(index=False):
        rows.append(tuple(_v(v) for v in r))
    return {"ids": ids, "n_ms": len(ms), "rows": sorted(rows, key=repr)}


def _v(v):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return float(f"{float(v):.9g}")
    if pd.isna(v):
        return None
    return str(v)


def outcome(fn):
    try:
        return {"ok": True, "res": canon(fn())}
    except Timeout:
        return {"ok": False, "kind": "timeout", "err": "timeout"}
    except Exception as e:
        mod = type(e).__module__ or ""
        kind = "refused" if mod.startswith("vtlengine") else "crash"
        tb = traceback.extract_tb(e.__traceback__)
        where = next((f"{os.path.basename(f.filename)}:{f.lineno} {f.name}" for f in reversed(tb) if "vtlengine" in f.filename), "")
        return {"ok": False, "kind": kind, "err": f"{type(e).__name__}: {str(e)[:300]}", "where": where}


def udo(chain):
    got = gen.compose(chain)
    body = got[0][len("R <- "):-1].replace("D", "s")  # имена наборов в цепочке — только D
    return f"define operator f(s dataset) returns dataset is {body} end operator;\nR <- f(D);"


def check(chain):
    got = gen.compose(chain)
    if got is None:
        return None
    nested, split, st = got
    rec = {"chain": list(chain), "nested": nested}
    base = outcome(lambda: run(nested))
    rec["base"] = {k: v for k, v in base.items() if k != "res"}
    if not base["ok"]:
        return rec
    rec["rows"] = len(base["res"]["rows"])
    want = base["res"]
    variants = {"split": lambda: run(split)}
    order = list(range(len(ROWS)))
    random.Random(len(chain) + hash(tuple(chain)) % 997).shuffle(order)
    variants["perm"] = lambda: run(nested, df=frame("obs_value", order=order))
    idx = list(range(len(ROWS)))[::-1]
    variants["index"] = lambda: run(nested, df=frame("obs_value", index=[i * 7 + 3 for i in idx]))
    if "D" in nested and "define operator" not in nested:
        variants["udo"] = lambda: run(udo(chain))
    if any(k.split(":")[-1] in gen.BRANCH for k in chain):
        gen.HOIST = True
        try:
            hoisted = gen.compose(chain)
        finally:
            gen.HOIST = False
        if hoisted:
            variants["hoist"] = lambda s=hoisted[0]: run(s)
    for name in ("int_var", "bool_var", "v"):
        g2 = gen.compose(chain, m=name)
        if g2 is not None:
            variants[f"name:{name}"] = (lambda s=g2[0], n=name: run(s, m=n, df=frame(n)))
    bad = {}
    for key, fn in variants.items():
        o = outcome(fn)
        if not o["ok"]:
            bad[key] = {k: v for k, v in o.items() if k != "res"}
        elif (o["res"]["rows"] != want["rows"] or o["res"]["ids"] != want["ids"]):
            bad[key] = {"kind": "differs", "got": o["res"]["rows"][:6], "want": want["rows"][:6],
                        "n_got": len(o["res"]["rows"]), "n_want": len(want["rows"])}
    rec["bad"] = bad
    return rec


def main():
    signal.signal(signal.SIGALRM, _alarm)
    k, n = map(int, os.environ.get("SHARD", "0/1").split("/"))
    done = set()
    if os.path.exists(OUT):
        for line in open(OUT):
            try:
                done.add(tuple(json.loads(line)["chain"]))
            except Exception:
                pass
    pool = gen.branch_cases() if os.environ.get("FUZZ_SET") == "branch" else gen.cases()
    todo = [c for i, c in enumerate(pool) if i % n == k and tuple(c) not in done]
    log = open(os.path.join(H, f"run{k}.log"), "a")
    out = open(OUT, "a")
    t0 = time.time()
    for i, chain in enumerate(todo):
        try:
            rec = check(chain)
        except Exception as e:  # сбой самой проверки — записать и идти дальше
            rec = {"chain": list(chain), "harness": f"{type(e).__name__}: {e}"}
        if rec is None:
            rec = {"chain": list(chain), "skip": True}
        out.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
        out.flush()
        if i % 100 == 0:
            print(f"{i}/{len(todo)} {round(time.time() - t0)} с", file=log, flush=True)
    print("EXIT", file=log, flush=True)


if __name__ == "__main__":
    if sys.argv[1:] == ["one"]:
        signal.signal(signal.SIGALRM, _alarm)
        print(json.dumps(check(tuple(sys.argv[2].split(","))), ensure_ascii=False, indent=1, default=str)[:4000])
    else:
        main()
