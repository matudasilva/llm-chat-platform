"""T23 campaign harness. Counting instruments that fail LOUDLY.

The previous version wrapped `.embed`, which does not exist -- the
AttributeError was raised inside `build_retrieval_pipeline`, which runs inside
`get_chat_rag_context`'s best-effort boundary, so it surfaced as
`chat_rag.degraded` and looked exactly like a production defect. Every wrapper
here asserts the attribute exists BEFORE replacing it, so an instrument bug
stops the harness instead of impersonating a system degradation.
"""
import os, re, sys, pathlib

def load_env_to_host():
    env = dict(re.findall(r'^([A-Z_]+)=(.*)$', pathlib.Path(".env").read_text(), re.M))
    h = lambda u: u.replace("@postgres:5432", "@127.0.0.1:15432")
    for k in ("DATABASE_URL", "DATABASE_URL_APP", "DATABASE_URL_OPS"):
        os.environ[k] = h(env[k])
    return env

def _wrap(obj, name, counter, key, tokens=None):
    assert hasattr(obj, name), (
        f"HARNESS BUG: {type(obj).__name__} has no attribute {name!r}; "
        f"public methods: {[m for m in dir(obj) if not m.startswith('_')]}"
    )
    inner = getattr(obj, name)
    async def spy(*a, **k):
        counter[key] = counter.get(key, 0) + 1
        out = await inner(*a, **k)
        if tokens is not None:
            for arg in list(a) + list(k.values()):
                if isinstance(arg, str):
                    tokens[0] += len(arg) // 4
                elif isinstance(arg, (list, tuple)):
                    tokens[0] += sum(len(x) // 4 for x in arg if isinstance(x, str))
        return out
    setattr(obj, name, spy)

def install_counters(counter, embed_tokens):
    from app.core.domain import retrieval_factory
    orig_rr = retrieval_factory.build_reranker
    def counted_rr(cfg=None):
        rr = orig_rr(cfg)
        _wrap(rr, "rerank", counter, "rerank")
        return rr
    retrieval_factory.build_reranker = counted_rr

    orig_emb = retrieval_factory.build_embedding_provider
    def counted_emb(cfg=None):
        e = orig_emb(cfg)
        _wrap(e, "embed_one", counter, "embed_one", embed_tokens)
        _wrap(e, "embed_many", counter, "embed_many", embed_tokens)
        return e
    retrieval_factory.build_embedding_provider = counted_emb
