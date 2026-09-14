import argparse, asyncio, json, os, sys, time, uuid, pathlib
sys.path.insert(0, "."); sys.path.insert(0, str(pathlib.Path(__file__).parent))
from t23_harness import load_env_to_host, install_counters
load_env_to_host()

ARMS = {
  "gate_a_tracing_off": dict(tracing=False, history=False, ebm25=False, conversation=False),
  "gate_a_tracing_on":  dict(tracing=True,  history=False, ebm25=False, conversation=False),
  "gate_b1_mode_a":     dict(tracing=True,  history=True,  ebm25=False, conversation=True),
  "gate_b2_mode_b":     dict(tracing=True,  history=True,  ebm25=True,  conversation=True),
}

ap = argparse.ArgumentParser()
ap.add_argument("--arm", required=True, choices=list(ARMS))
ap.add_argument("--runs", type=int, default=3)
ap.add_argument("--limit", type=int, default=None)
ap.add_argument("--warmup", action="store_true")
ap.add_argument("--out", required=True)
a = ap.parse_args()
cfg = ARMS[a.arm]

os.environ["CONVERSATION_HISTORY_ENABLED"] = str(cfg["history"]).lower()
os.environ["EBM25_ENABLED"] = str(cfg["ebm25"]).lower()

from app.core.settings import settings
from app.core.observability import tracing
sys.path.insert(0, "experiments/evaluation")
from t23_campaign import CountingTracer, load_golden_set, RERANK_USD_PER_1K_QUERIES
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from httpx import AsyncClient, ASGITransport

counter, embed_tokens = {}, [0]
install_counters(counter, embed_tokens)
tracer = CountingTracer()
tracing.configure_for_testing(tracer if cfg["tracing"] else None)

from app.main import app
TENANT = "orq37-t23"
HDR = {"X-Tenant-ID": TENANT}
golden = load_golden_set()
if a.limit: golden = golden[:a.limit]

async def metrics_rows_since(ts):
    e = create_async_engine(os.environ["DATABASE_URL"])  # chat_ops cannot SELECT (AC34); read as owner
    async with async_sessionmaker(e)() as s:
        rows = (await s.execute(text(
            "SELECT request_id, mode, memory_outcome, generation_outcome, input_tokens, "
            "output_tokens, total_latency_ms, estimated_cost_usd, ebm25_selected_count "
            "FROM rag_request_metrics WHERE tenant_id=:t AND created_at > :ts"),
            {"t": TENANT, "ts": ts})).mappings().all()
    await e.dispose()
    return [dict(r) for r in rows]

async def one(c, q, conv_id):
    body = {"message": q}
    if conv_id: body["conversation_id"] = str(conv_id)
    t0 = time.perf_counter()
    r = await c.post("/chat", json=body, headers=HDR, timeout=300)
    ms = (time.perf_counter() - t0) * 1000
    j = r.json() if r.status_code == 200 else {}
    return ms, r.status_code, j

async def main():
    samples = []
    async with app.router.lifespan_context(app):
        e = create_async_engine(os.environ["DATABASE_URL"])  # chat_ops cannot SELECT (AC34); read as owner
        async with async_sessionmaker(e)() as s:
            start_ts = (await s.execute(text("SELECT now()"))).scalar_one()
        await e.dispose()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            passes = ([("warmup", 0)] if a.warmup else []) + [("measured", i+1) for i in range(a.runs)]
            for kind, run_no in passes:
                # ONE conversation per pass for the history arms, with the 60
                # queries asked in sequence. The window is 20 messages (10
                # turns), so from about the 11th query onward there IS an
                # out-of-window corpus and Mode B has something to rank. Seeding
                # a fresh 2-turn conversation per query would have left every
                # corpus empty and made Mode B measure exactly Mode A.
                conv_id = None
                for item in golden:
                    if cfg["conversation"] and conv_id is None:
                        _, _, j0 = await one(c, "Let's discuss the platform architecture.", None)
                        conv_id = j0.get("conversation_id")
                    tracer.reset()
                    before = dict(counter)
                    ms, code, j = await one(c, item["query"], conv_id)
                    if kind == "measured":
                        samples.append(dict(
                            arm=a.arm, run=run_no, query_id=item["query_id"], language=item["language"],
                            latency_ms=round(ms, 1), status=code,
                            sources=len(j.get("sources") or []),
                            stage_spans=dict(tracer.spans),
                            rerank_calls=counter.get("rerank", 0) - before.get("rerank", 0),
                            embed_calls=(counter.get("embed_one",0)+counter.get("embed_many",0))
                                        - (before.get("embed_one",0)+before.get("embed_many",0)),
                            source_paths=[s.get("document_id") for s in (j.get("sources") or [])],
                        ))
                print(f"  {a.arm} {kind} run={run_no} done ({len(samples)} measured so far)", flush=True)
        rows = await metrics_rows_since(start_ts)
    pathlib.Path(a.out).write_text(json.dumps(
        {"arm": a.arm, "config": cfg, "samples": samples, "metrics_rows": rows,
         "counters_total": counter, "embed_tokens_est": embed_tokens[0]}, indent=2, default=str))
    print(f"  wrote {a.out}: {len(samples)} samples, {len(rows)} metrics rows", flush=True)
asyncio.run(main())
