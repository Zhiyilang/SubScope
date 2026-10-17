"""SubScope -- find the money you are paying without noticing.

A bill file goes in; a ranked list of recurring charges comes out, each with
what it costs per year rather than per month.  Deterministic, integer cents,
no model in the detection path.

    from subscope import normalize, detect, report
    rows = normalize.load(text, "alipay")
    result = detect.scan(rows)
    print(report.render_text(result))
"""

__all__ = ["normalize", "detect", "report"]
__version__ = "1.0.0"
