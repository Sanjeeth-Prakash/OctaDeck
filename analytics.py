"""Aggregate request history in SQLite and load a bounded set of traces."""
from time import time

WINDOWS = {"24h": (86400, 3600), "7d": (604800, 86400),
           "30d": (2592000, 86400), "90d": (7776000, 604800)}

MODEL_METRICS = """,
    ranked AS (
      SELECT a.*, ROW_NUMBER() OVER(PARTITION BY provider, model ORDER BY a.duration_ms) AS rn,
             COUNT(*) OVER(PARTITION BY provider, model) AS n
      FROM attempts a JOIN cohort c ON a.run_id=c.id WHERE stage <> 'file check'
    )
    SELECT provider, model, COUNT(*) AS calls,
           COUNT(*) FILTER(WHERE outcome <> 'ok') AS failed,
           AVG(CASE WHEN rn IN ((n+1)/2,(n+2)/2) THEN duration_ms END) AS median_ms,
           SUM(tokens) AS tokens
    FROM ranked GROUP BY provider, model ORDER BY calls DESC, provider, model
"""

def recent_model_metrics(store):
    with store.db() as db:
        return [dict(row) for row in db.execute(
            "WITH cohort AS (SELECT id FROM runs WHERE started>=?)" + MODEL_METRICS,
            (time() - WINDOWS["7d"][0],))]


def report(store, window, mode="", outcome="", model="", trace=""):
    period, bucket = WINDOWS[window]
    cutoff = time() - period
    where = ["started >= ?"]
    parameters = [cutoff]
    if mode:
        where.append("mode = ?")
        parameters.append(mode)
    if model:
        where.append("EXISTS(SELECT 1 FROM attempts a WHERE a.run_id=r.id AND a.model=?)")
        parameters.append(model)
    failed_step = "EXISTS(SELECT 1 FROM attempts a WHERE a.run_id=r.id AND a.outcome <> 'ok')"
    conditions = {"attention": failed_step, "failed": "status='failed'",
                  "recovered": f"status='ok' AND {failed_step}",
                  "clean": f"status='ok' AND NOT {failed_step}"}
    if outcome:
        where.append(conditions[outcome])
    cohort = f"""WITH cohort AS (
        SELECT r.*, {failed_step} AS had_error FROM runs r WHERE {" AND ".join(where)}
    ) """
    with store.db() as db:
        db.execute("BEGIN")
        summary = dict(db.execute(cohort + """
            SELECT COUNT(*) AS requests, COUNT(*) FILTER(WHERE status='ok') AS successful,
                   COUNT(*) FILTER(WHERE status='failed') AS failed,
                   COUNT(*) FILTER(WHERE status='ok' AND had_error) AS recovered
            FROM cohort
        """, parameters).fetchone())
        summary.update(db.execute(cohort + """
            SELECT SUM(tokens) AS tokens, SUM(input_tokens) AS input_tokens, SUM(output_tokens) AS output_tokens,
                   COUNT(*) AS calls, COUNT(*) FILTER(WHERE outcome <> 'ok') AS call_failures,
                   COUNT(tokens) AS usage_reports
            FROM attempts JOIN cohort ON run_id=id WHERE stage <> 'file check'
        """, parameters).fetchone())
        percentiles = db.execute(cohort + """,
            ranked AS (SELECT duration_ms, ROW_NUMBER() OVER (ORDER BY duration_ms) AS rn,
                       COUNT(*) OVER () AS n FROM cohort WHERE status IN ('ok','failed'))
            SELECT MAX(CASE WHEN rn=(n+1)/2 THEN duration_ms END) AS p50_ms,
                   MAX(CASE WHEN rn=(95*n+99)/100 THEN duration_ms END) AS p95_ms FROM ranked
        """, parameters).fetchone()
        summary.update(percentiles)
        models = [dict(row) for row in db.execute(cohort + MODEL_METRICS, parameters)]
        timeline = [dict(row) for row in db.execute(cohort + """
            SELECT CAST((started - ?) / ? AS INTEGER) AS slot,
                   COUNT(*) AS requests, COUNT(*) FILTER(WHERE status='failed') AS failed
            FROM cohort GROUP BY slot ORDER BY slot
        """, [*parameters, cutoff, bucket])]
        traces = [dict(row) for row in db.execute(cohort + """
            SELECT * FROM cohort ORDER BY id=? DESC, started DESC LIMIT 100
        """, [*parameters, trace])]
        if traces:
            by_id = {run["id"]: run for run in traces}
            for run in traces:
                run["attempts"] = []
            placeholders = ",".join("?" for _ in traces)
            for row in db.execute(f"""SELECT run_id,stage,provider,model,outcome,
                                        duration_ms,tokens,input_tokens,output_tokens
                                    FROM attempts WHERE run_id IN ({placeholders}) ORDER BY rowid""", tuple(by_id)):
                attempt = dict(row)
                by_id[attempt.pop("run_id")]["attempts"].append(attempt)
        model_options = [row[0] for row in db.execute("""
            SELECT DISTINCT model FROM attempts JOIN runs ON run_id=id WHERE started>=? ORDER BY model
        """, (cutoff,))]
    return {"summary": summary, "models": models, "timeline": timeline, "traces": traces,
            "model_options": model_options, "cutoff": cutoff, "bucket": bucket}
