"""Сверка vtlengine с эталоном ref.py: каждая цепочка из результатов run.py (FUZZ_IN, по умолчанию res*.jsonl) заново на
vtlengine против всех сочетаний спорных флагов эталона. Итог — REF_OUT (refcheck.jsonl): verdict = ok:<флаги> | wrong |
crash | refused. Запуск: PYTHONPATH=<src vtlengine> python3 refcheck.py"""
import glob, json, math, os, signal
import ref, run

H = os.path.dirname(os.path.abspath(__file__))


def _val(v):
    if v is ref.ANY:
        return v
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return float(f"{float(v):.9g}")
    return str(v)


def table(ids, ms, rows):
    """{ключ идентификаторов: {мера: значение}}; повтор ключа — признак сбоя, сохраняется списком."""
    out = {}
    for r in rows:
        key = tuple(str(r[i]) for i in sorted(ids))
        out.setdefault(key, []).append({x: _val(r[x]) for x in sorted(ms)})
    return {"ids": sorted(ids), "ms": sorted(ms), "rows": out}


def from_engine(ds):
    ids = [c.name for c in ds.components.values() if c.role.value == "Identifier"]
    ms = [c.name for c in ds.components.values() if c.role.value != "Identifier"]
    return table(ids, ms, ds.data.to_dict("records"))


def records():
    for f in sorted(glob.glob(os.path.join(H, os.environ.get("FUZZ_IN", "res*.jsonl")))):
        for line in open(f):
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("nested"):
                yield r


def same(got, want):
    if got["ids"] != want["ids"] or got["ms"] != want["ms"] or set(got["rows"]) != set(want["rows"]):
        return False
    for k, ws in want["rows"].items():
        gs = got["rows"][k]
        if len(gs) != len(ws):
            return False
        for g, w in zip(gs, ws, strict=True):
            for x in want["ms"]:
                if w[x] is ref.ANY:
                    continue
                a, b = g[x], w[x]
                if isinstance(a, float) and isinstance(b, float):
                    if not math.isclose(a, b, rel_tol=1e-7, abs_tol=1e-9):
                        return False
                elif a != b:
                    return False
    return True


def verdict(got, wants):
    hits = [",".join(f"{n}={v}" for n, v in zip(ref.FLAGS, combo, strict=True)) for combo, w in wants.items() if same(got, w)]
    return ("ok:" + "|".join(hits)) if hits else "wrong"


def main():
    signal.signal(signal.SIGALRM, run._alarm)
    out = open(os.path.join(H, os.environ.get("REF_OUT", "refcheck.jsonl")), "w")
    for r in records():
        chain = r["chain"]
        try:
            wants = {c: table(d["ids"], d["ms"], d["rows"]) for c, d in ref.answers(chain, run.ROWS).items()}
        except Exception as e:
            out.write(json.dumps({"chain": chain, "ref_error": f"{type(e).__name__}: {e}"}, ensure_ascii=False) + "\n")
            continue
        rec = {"chain": chain}
        try:
            got = run.run(r["nested"])
            rec["vtlengine"] = verdict(from_engine(got), wants)
            if rec["vtlengine"] == "wrong":
                rec["v_rows"] = {"|".join(k): v for k, v in list(from_engine(got)["rows"].items())[:6]}
        except Exception as e:
            rec["vtlengine"] = ("refused" if (type(e).__module__ or "").startswith("vtlengine") else "crash") + f": {type(e).__name__}: {str(e)[:120]}"
        w0 = wants[(False, False)]
        if rec.get("vtlengine") == "wrong":
            rec["ref_rows"] = {"|".join(k): [{x: ("ANY" if y is ref.ANY else y) for x, y in v.items()} for v in vs]
                               for k, vs in list(w0["rows"].items())[:6]}
            rec["script"] = r["nested"]
        out.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
        out.flush()


if __name__ == "__main__":
    main()
