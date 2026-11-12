from decimal import Decimal

CAP = Decimal("5.00")
NORMAL = Decimal("0.02383748")
R_MAX = Decimal("0.17269772")
BOUND = Decimal("4.15355688")
NORMAL_COMPONENTS = {
    "primary": "0.01355736", "rewrite": "0.00778860",
    "embedding": "0.00049152", "gcp_rerank": "0.001", "aws_rerank": "0.001",
}


def may_admit(settled: Decimal, reserve: Decimal = Decimal(0)) -> bool:
    return settled >= 0 and reserve >= 0 and settled + reserve + R_MAX <= CAP


def charges(stopping: bool) -> dict[str, str]:
    return {"worst_case": str(R_MAX)} if stopping else dict(NORMAL_COMPONENTS)
