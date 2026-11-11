"""Эталон для синтетических программ: смысл каждого преобразования gen.TRANSFORMS, написанный заново на чистом Python
по справочнику VTL 2.1 (VTL 2.1 Reference Manual, sdmx.org), без pandas — на нём стоит сам vtlengine, и общие ловушки
(индекс, NaN против None, группировка с пропусками) эталон с ним делил бы. Данных десять строк — скорость не важна.

Правила справочника, на которые опирается эталон:
- if / case: ветка then — только когда условие TRUE; NULL и FALSE — else (с. 226); case — первая истинная ветка (с. 228);
- filter оставляет точку только при TRUE (NULL отбрасывается);
- окно аналитики без windowClause — весь раздел: «data points between unbounded preceding and unbounded following»;
- арифметика и сравнения с NULL дают NULL; агрегаты пропуски не берут (в справочнике прямо не сказано — принято как в SQL).
Спорные места справочника — флаги FLAGS: эталон считает все сочетания, проверка принимает ответ, совпавший хоть с
одним, и называет сочетание. Деление на ноль справочник не определяет — такие строки эталон помечает ANY."""
import itertools, math

ANY = object()                         # значение, которое эталон не определяет: подходит любое
FLAGS = {
    "count_nulls": (False, True),      # count(мера) / count(набор): «число точек» (с. 193) — с пропусками или без
    "nulls_first": (False, True),      # место пропуска в order by (rank): справочник не называет
}


class DivZero(Exception):
    pass


def num(v):
    return v if v is None or v is ANY else float(v)


def ar(f, *xs):
    if any(x is ANY for x in xs):
        return ANY
    if any(x is None for x in xs):
        return None
    try:
        return f(*xs)
    except ZeroDivisionError:
        return ANY
    except (ValueError, OverflowError):
        return ANY


def gt(a, b):
    return ar(lambda x, y: x > y, a, b)


def ifte(c, a, b):
    if c is ANY:
        return ANY
    return a if c is True else b


def half_up(x, d=0):
    q = 10 ** d
    return math.floor(x * q + 0.5) / q if x >= 0 else -math.floor(-x * q + 0.5) / q


def E(key, x, w):
    return {
        "add": lambda: ar(lambda a: a + 1, x), "mulw": lambda: ar(lambda a, b: a * b, x, w),
        "divw": lambda: ar(lambda a, b: a / b, x, w), "neg": lambda: ar(lambda a: -a, x), "abs": lambda: ar(abs, x),
        "ln": lambda: ar(lambda a: math.log(abs(a) + 1), x), "exp": lambda: ar(lambda a: math.exp(a / 10), x),
        "pow": lambda: ar(lambda a: a ** 2, x), "sqrt": lambda: ar(lambda a: math.sqrt(abs(a)), x),
        "nvl": lambda: 0.0 if x is None else x, "if": lambda: ifte(gt(x, 2), 1.0, 0.0),
        "ifnull": lambda: 0.0 if x is None else x,
        "ifsum": lambda: ar(lambda a, b: a + b, ifte(gt(x, 2), 1.0, 0.0), ifte(gt(w, 2), 1.0, 0.0)),
        "ifmul": lambda: ar(lambda a: 2 * a, ifte(gt(x, 2), x, 0.0)),
        "case": lambda: ifte(gt(x, 2), 1.0, ifte(gt(x, 0), 2.0, 3.0)),
        "castint": lambda: ar(lambda a: float(half_up(a)), x),
        "mod": lambda: ar(lambda a: float(int(half_up(abs(a))) % 3), x),
        "between": lambda: ifte(ar(lambda a: 1 <= a <= 4, x), 1.0, 0.0),
    }[key]()


def _group(rows, keys):
    out = {}
    for r in rows:
        out.setdefault(tuple(r[k] for k in keys), []).append(r)
    return out


def _agg(fn, vals, flags):
    if fn == "count":
        return float(len(vals) if flags["count_nulls"] else sum(v is not None for v in vals))
    if any(v is ANY for v in vals):
        return ANY
    xs = [v for v in vals if v is not None]
    if not xs:
        return None
    if fn == "sum":
        return sum(xs)
    if fn == "avg":
        return sum(xs) / len(xs)
    if fn == "max":
        return max(xs)
    if fn == "min":
        return min(xs)
    if fn == "median":
        xs = sorted(xs)
        n = len(xs)
        return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2
    raise KeyError(fn)


def apply(key, ds, flags):
    """Преобразование key над набором ds = {"ids": [...], "ms": [...], "m": главная, "rows": [dict]}."""
    ids, ms, m, rows = ds["ids"], ds["ms"], ds["m"], ds["rows"]
    kind, _, arg = key.partition(":")
    new = lambda **kw: {**ds, **kw}
    if kind == "calc":
        return new(rows=[{**r, m: E(arg, r[m], r.get("w"))} for r in rows])
    if kind == "new":
        return new(ms=[*ms, "k"], rows=[{**r, "k": E(arg, r[m], r.get("w"))} for r in rows])
    if kind == "filter":
        cond = {
            "m": lambda r: gt(r[m], 2), "null": lambda r: r[m] is not None, "geo": lambda r: r["geo"] != "b",
            "tp": lambda r: int(r["tp"]) >= 2020, "in": lambda r: int(r["tp"]) in (2019, 2021) and r["geo"] in ("a", "c"),
        }[arg]
        return new(rows=[r for r in rows if cond(r) is True])
    if kind == "keep":
        return new(ms=[m], rows=[{**{i: r[i] for i in ids}, m: r[m]} for r in rows])
    if kind == "drop":
        gone = [x for x in ms if x != m][-1]
        return new(ms=[x for x in ms if x != gone], rows=[{k: v for k, v in r.items() if k != gone} for r in rows])
    if kind == "rename":
        return new(m=arg, ms=[arg if x == m else x for x in ms], rows=[{(arg if k == m else k): v for k, v in r.items()} for r in rows])
    if kind == "sub":
        return new(ids=[i for i in ids if i != "tp"], rows=[{k: v for k, v in r.items() if k != "tp"} for r in rows if r["tp"] == "2020"])
    if kind == "aggr":
        g = _group(rows, ["geo"])
        if arg == "two":
            return {"ids": ["geo"], "ms": [m, "n"], "m": m, "rows": [
                {"geo": k[0], m: _agg("sum", [r[m] for r in rs], flags), "n": _agg("count", [r[m] for r in rs], flags)} for k, rs in g.items()]}
        return {"ids": ["geo"], "ms": [m], "m": m, "rows": [{"geo": k[0], m: _agg(arg, [r[m] for r in rs], flags)} for k, rs in g.items()]}
    if kind == "group":
        g = _group(rows, ["geo"])
        if arg == "count":   # count набора: точки, где хоть одна мера не пропуск (или все точки — по флагу)
            out = []
            for k, rs in g.items():
                n = len(rs) if flags["count_nulls"] else sum(any(r[x] is not None for x in ms) for r in rs)
                out.append({"geo": k[0], "int_var": float(n)})
            return {"ids": ["geo"], "ms": ["int_var"], "m": "int_var", "rows": out}
        return {"ids": ["geo"], "ms": list(ms), "m": m,
                "rows": [{"geo": k[0], **{x: _agg(arg, [r[x] for r in rs], flags) for x in ms}} for k, rs in g.items()]}
    if kind == "an":
        return new(ms=[*ms, "p"], rows=_analytic(arg, rows, m, flags))
    if kind == "join":
        if arg == "self":
            return new(rows=[{**r, m: ar(lambda a, b: a / b, r[m], r[m])} for r in rows])
        if arg == "left":
            return new(rows=[{**r, m: (r[m] if gt(r[m], 2) is True else 0.0)} for r in rows])
        if arg == "filter":
            return new(rows=[r for r in rows if gt(r[m], 2) is True])
    if kind == "union":
        return ds
    if kind == "exists":
        keep = {tuple(r[i] for i in ids) for r in rows if gt(r[m], 2) is True}
        return {"ids": ids, "ms": ["bool_var"], "m": "bool_var",
                "rows": [{**{i: r[i] for i in ids}, "bool_var": tuple(r[i] for i in ids) in keep} for r in rows]}
    if kind == "ds":
        f = (lambda v: ar(lambda a: a * 2, v)) if arg == "mul" else (lambda v: 0.0 if v is None else v)
        return new(rows=[{**r, **{x: f(r[x]) for x in ms}} for r in rows])
    raise KeyError(key)


def _analytic(kind, rows, m, flags):
    part = "tp" if kind in ("rank", "maxpart") else "geo"
    out = []
    for _k, rs in _group(rows, [part]).items():
        rs = sorted(rs, key=lambda r: r["tp"])
        vals = [r[m] for r in rs]
        for n, r in enumerate(rs):
            if kind == "lag":
                p = vals[n - 1] if n else None
            elif kind == "lead":
                p = vals[n + 1] if n + 1 < len(vals) else None
            elif kind == "runsum":
                p = _agg("sum", vals[:n + 1], flags)
            elif kind == "runcount":
                p = _agg("count", vals[:n + 1], flags)
            elif kind == "first":
                p = vals[0]
            elif kind == "last":
                p = vals[-1]                         # окно по умолчанию — весь раздел (справочник 2.1)
            elif kind == "rank":                     # ничья — одно место; пропуск в мере — место не определено
                nulls = sum(v is None for v in vals)
                p = ANY if r[m] is None or any(v is ANY for v in vals) else \
                    float(1 + sum(v is not None and v > r[m] for v in vals) + (nulls if flags["nulls_first"] else 0))
            elif kind == "avgpart":
                p = _agg("avg", vals, flags)
            elif kind == "maxpart":
                p = _agg("max", vals, flags)
            out.append({**r, "p": p})
    return out


def answers(chain, rows, m="obs_value"):
    """{сочетание флагов: (ids, ms, строки)} — ответ эталона на цепочку при каждом сочетании спорных флагов."""
    out = {}
    for combo in itertools.product(*FLAGS.values()):
        flags = dict(zip(FLAGS, combo, strict=True))
        ds = {"ids": ["geo", "tp"], "ms": [m, "w"], "m": m,
              "rows": [{"geo": g, "tp": t, m: num(a), "w": num(b)} for g, t, a, b in rows]}
        for key in chain:
            ds = apply(key, ds, flags)
        out[combo] = ds
    return out
