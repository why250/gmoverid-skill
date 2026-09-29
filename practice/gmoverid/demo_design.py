"""Minimal gm/ID sizing exercise using the generated nmos180 lookup table."""

from __future__ import annotations

import json
from pathlib import Path

from design_gmoverid import GmIdTable, print_op


def main() -> None:
    target_gmid = 15.0
    target_id = 100e-6

    table = GmIdTable("nmos180", W=10.0, L=0.18, vds=0.9)
    op = table.size(gmid=target_gmid, Id=target_id)

    # Keep the exercise self-checking so it can be used as a smoke test.
    assert abs(op["Id_A"] - target_id) < 1e-12
    assert 1.0 < op["W_um"] < 100.0
    assert op["ft_Hz"] > 1e9
    assert op["gmro"] > 5.0

    print_op(op)

    result_path = Path(__file__).resolve().parent / "logs" / "practice_design.json"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(
        json.dumps(op, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\nResult: {result_path}")


if __name__ == "__main__":
    main()
