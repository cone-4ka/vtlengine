"""Синтетические программы VTL: все пары (и выборка троек) преобразований набора — фильтры, calc, агрегаты,
аналитика, соединения, union, exists_in, операции над наборами.

Преобразование — функция (выражение набора, структура) → (выражение, структура) или None, если к этой структуре оно
неприменимо. Структура: ids (идентификаторы), ms (меры по порядку), m (главная мера). Выражения мер — E."""
import itertools, random

# Выражения главной меры x (w — вторая мера входа, есть не всегда).
E = {
    "add": "{x} + 1", "mulw": "{x} * w", "divw": "{x} / w", "neg": "-{x}", "abs": "abs({x})",
    "ln": "ln(abs({x}) + 1)", "exp": "exp({x} / 10)", "pow": "power({x}, 2)", "sqrt": "sqrt(abs({x}))",
    "nvl": "nvl({x}, 0)", "if": "if {x} > 2 then 1 else 0", "ifnull": "if isnull({x}) then 0 else {x}",
    "ifsum": "(if {x} > 2 then 1 else 0) + (if w > 2 then 1 else 0)", "ifmul": "2 * (if {x} > 2 then {x} else 0)",
    "case": "case when {x} > 2 then 1 when {x} > 0 then 2 else 3", "castint": "cast(round({x}, 0), integer)",
    "mod": "mod(cast(round(abs({x}), 0), integer), 3)", "between": "if between({x}, 1, 4) then 1 else 0",
}
# Ветки if с параметризованными операторами: (условие, then, else). Сбой 1.9.7: параметр substr в ветке
# выравнивался по меткам и терялся. Проверка — вариант hoist: ветки посчитаны отдельным calc до if (одинаковый ответ).
BRANCH = {
    "brsub": ("{x} > 2", "length(substr(cast({x}, string), 2, 3))", "-1"),
    "brsubv": ("{x} > 2", "length(substr(cast({x}, string), 1, length(cast({x}, string)) - 1))", "length(substr(cast(w, string), 2, length(cast(w, string)) - 1))"),
    "brround": ("{x} > 2", "round({x} / 3, 1)", "trunc({x} / 3, 2)"),
    "brnvl": ("{x} > 2", "nvl(w, 0)", "nvl(w, 1)"),
    "brinstr": ("{x} > 2", "instr(cast({x}, string), \".\")", "instr(cast(w, string), \"0\")"),
    "brreplace": ("{x} > 2", "length(replace(cast({x}, string), \".\", \"\"))", "length(replace(cast(w, string), \"0\", \"xx\"))"),
    "brpow": ("{x} > 0", "power({x}, 2)", "power(w, 3)"),
    "brcase": ("{x} > 2", "case when w > 2 then substr(\"abcdef\", 2, 2) when w > 0 then substr(\"abcdef\", 3, 3) else \"z\"", "substr(\"abcdef\", 4, 1)"),
}
for _k, (_c, _t, _e) in BRANCH.items():
    E[_k] = f"if {_c} then {_t} else {_e}"
NEEDS_W = {"mulw", "divw", "ifsum", "brsubv", "brnvl", "brinstr", "brreplace", "brpow", "brcase"}
HOIST = False   # вариант hoist: ветки BRANCH считаются отдельным calc до if
NAMES = ["v", "int_var", "num_var", "bool_var", "string_var", "obs_value"]   # имена мер, в том числе служебные движка
W = "data points between unbounded preceding and current data point"


def _has(st, *ids):
    return all(i in st["ids"] for i in ids)


def _others(st):
    return [x for x in st["ms"] if x != st["m"]]


def T_calc(key):
    def t(s, st):
        if key in NEEDS_W and "w" not in st["ms"]:
            return None
        if HOIST and key in BRANCH and not ({"t1", "t2"} & set(st["ms"])):
            c, a, b = (x.format(x=st["m"]) for x in BRANCH[key])
            return f"{s}[calc t1 := {a}, t2 := {b}][calc {st['m']} := if {c} then t1 else t2][drop t1, t2]", st
        return f"{s}[calc {st['m']} := {E[key].format(x=st['m'])}]", st
    return t


def T_calc_new(key):
    def t(s, st):
        if key in NEEDS_W and "w" not in st["ms"] or "k" in st["ms"]:
            return None
        return f"{s}[calc k := {E[key].format(x=st['m'])}]", {**st, "ms": [*st["ms"], "k"]}
    return t


def t_filter_m(s, st):
    return f"{s}[filter {st['m']} > 2]", st


def t_filter_null(s, st):
    return f"{s}[filter not isnull({st['m']})]", st


def t_filter_geo(s, st):
    return (f'{s}[filter geo <> "b"]', st) if _has(st, "geo") else None


def t_filter_tp(s, st):
    return (f"{s}[filter cast(tp, integer) >= 2020]", st) if _has(st, "tp") else None


def t_filter_in(s, st):
    return (f"{s}[filter cast(tp, integer) in {{2019, 2021}} and geo in {{\"a\", \"c\"}}]", st) if _has(st, "geo", "tp") else None


def t_keep(s, st):
    return (f"{s}[keep {st['m']}]", {**st, "ms": [st["m"]]}) if _others(st) else None


def t_drop(s, st):
    o = _others(st)
    return (f"{s}[drop {o[-1]}]", {**st, "ms": [x for x in st["ms"] if x != o[-1]]}) if o else None


def T_rename(to):
    def t(s, st):
        if to in st["ms"] or to in st["ids"]:
            return None
        return f"{s}[rename {st['m']} to {to}]", {**st, "m": to, "ms": [to if x == st["m"] else x for x in st["ms"]]}
    return t


def t_sub_tp(s, st):
    return (f'{s}[sub tp = "2020"]', {**st, "ids": [i for i in st["ids"] if i != "tp"]}) if _has(st, "tp") else None


def T_aggr(fn):
    def t(s, st):
        if not _has(st, "geo") or len(st["ids"]) < 2:
            return None
        return f"{s}[aggr {st['m']} := {fn}({st['m']}) group by geo]", {"ids": ["geo"], "ms": [st["m"]], "m": st["m"]}
    return t


def t_aggr_two(s, st):
    if not _has(st, "geo") or len(st["ids"]) < 2:
        return None
    return (f"{s}[aggr {st['m']} := sum({st['m']}), n := count({st['m']}) group by geo]",
            {"ids": ["geo"], "ms": [st["m"], "n"], "m": st["m"]})


def T_group(fn):
    def t(s, st):
        if not _has(st, "geo") or len(st["ids"]) < 2:
            return None
        out = {"ids": ["geo"], "ms": list(st["ms"]), "m": st["m"]}
        if fn == "count":                       # count набора даёт одну меру int_var
            out = {"ids": ["geo"], "ms": ["int_var"], "m": "int_var"}
        return f"{fn}({s} group by geo)", out
    return t


def T_analytic(kind):
    def t(s, st):
        if not _has(st, "geo", "tp") or "p" in st["ms"]:
            return None
        m = st["m"]
        expr = {
            "lag": f"lag({m}, 1 over (partition by geo order by tp))",
            "lead": f"lead({m}, 1 over (partition by geo order by tp))",
            "runsum": f"sum({m} over (partition by geo order by tp {W}))",
            "runcount": f"count({m} over (partition by geo order by tp {W}))",
            "first": f"first_value({m} over (partition by geo order by tp))",
            "last": f"last_value({m} over (partition by geo order by tp))",
            "rank": "rank(over (partition by tp order by {m} desc))".format(m=m),
            "avgpart": f"avg({m} over (partition by geo))",
            "maxpart": f"max({m} over (partition by tp))",
        }[kind]
        return f"{s}[calc p := {expr}]", {**st, "ms": [*st["ms"], "p"]}
    return t


def t_join_self(s, st):
    if "m2" in st["ms"]:
        return None
    m = st["m"]
    return (f"inner_join({s} as L, {s}[keep {m}][rename {m} to m2] as Q calc {m} := {m} / m2 drop m2)", st) \
        if _others(st) == [] or True else None


def t_join_left(s, st):
    if "m2" in st["ms"]:
        return None
    m = st["m"]
    return f"left_join({s} as L, {s}[keep {m}][filter {m} > 2][rename {m} to m2] as Q calc {m} := nvl(m2, 0) drop m2)", st


def t_join_filter(s, st):
    if "m2" in st["ms"]:
        return None
    m = st["m"]
    return f"inner_join({s} as L, {s}[keep {m}][rename {m} to m2] as Q filter m2 > 2 drop m2)", st


def t_union_split(s, st):
    if not _has(st, "geo"):
        return None
    return f'union({s}[filter geo = "a"], {s}[filter geo <> "a"])', st


def t_exists(s, st):
    if "bool_var" in st["ms"]:
        return None
    return f"exists_in({s}, {s}[filter {st['m']} > 2], all)", {"ids": list(st["ids"]), "ms": ["bool_var"], "m": "bool_var"}


def t_ds_arith(s, st):
    return f"({s} * 2)", st


def t_ds_nvl(s, st):
    return f"nvl({s}, 0)", st


TRANSFORMS = {
    **{f"calc:{k}": T_calc(k) for k in E}, **{f"new:{k}": T_calc_new(k) for k in ("add", "if", "ifsum", "nvl", "case")},
    "filter:m": t_filter_m, "filter:null": t_filter_null, "filter:geo": t_filter_geo, "filter:tp": t_filter_tp,
    "filter:in": t_filter_in, "keep": t_keep, "drop": t_drop, **{f"rename:{n}": T_rename(n) for n in NAMES},
    "sub:tp": t_sub_tp, **{f"aggr:{f}": T_aggr(f) for f in ("sum", "avg", "max", "min", "count", "median")},
    "aggr:two": t_aggr_two, **{f"group:{f}": T_group(f) for f in ("sum", "avg", "max", "count")},
    **{f"an:{k}": T_analytic(k) for k in ("lag", "lead", "runsum", "runcount", "first", "last", "rank", "avgpart", "maxpart")},
    "join:self": t_join_self, "join:left": t_join_left, "join:filter": t_join_filter, "union:split": t_union_split,
    "exists": t_exists, "ds:mul": t_ds_arith, "ds:nvl": t_ds_nvl,
}

# Вход: geo, tp — идентификаторы; m — главная мера (имя меняется вариантом), w — вторая.
BASE = {"ids": ["geo", "tp"], "ms": ["obs_value", "w"], "m": "obs_value"}


def compose(chain, m="obs_value"):
    """Цепочка преобразований → (вложенная программа, программа шагами, выходная структура) или None."""
    st = {**BASE, "m": m, "ms": [m, "w"]}
    s, steps, prev = "D", [], "D"
    for n, key in enumerate(chain):
        if n and chain[n - 1] == "exists":            # мера bool_var: числовые преобразования после неё неприменимы
            return None
        got = TRANSFORMS[key](s, st)
        if got is None:
            return None
        s, st2 = got
        step_expr, _ = TRANSFORMS[key](prev, st)
        name = f"S{n}"
        steps.append(f"{name} := {step_expr};")
        prev, st = name, st2
    nested = f"R <- {s};"
    split = "\n".join(steps[:-1] + [steps[-1].replace(f"S{len(chain) - 1} :=", "R <-")])
    return nested, split, st


def branch_cases(seed=12, n=1500):
    """Цепочки с ветками BRANCH: каждая ветка одна и в паре с каждым преобразованием (до и после), плюс выборка троек."""
    keys = list(TRANSFORMS)
    br = [f"calc:{k}" for k in BRANCH]
    out = [(b,) for b in br] + [(b, k) for b in br for k in keys] + [(k, b) for b in br for k in keys]
    rnd = random.Random(seed)
    out += [tuple(rnd.sample(keys, 2)) + (rnd.choice(br),) for _ in range(n)]
    return list(dict.fromkeys(out))


def cases(triples=3000, seed=11):
    keys = list(TRANSFORMS)
    out = [(k,) for k in keys] + list(itertools.product(keys, repeat=2))
    rnd = random.Random(seed)
    trip = list(itertools.product(keys, repeat=3))
    out += rnd.sample(trip, triples)
    return out
