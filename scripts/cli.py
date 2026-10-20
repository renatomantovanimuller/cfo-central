"""CLI do CFO Central.

    python -m scripts.cli migrate            # cria/atualiza o schema (Alembic no Postgres; create_all no SQLite)
    python -m scripts.cli sync [--full]      # Pluggy → razão
    python -m scripts.cli rebuild            # só reconstrói razão/revisões/snapshots
    python -m scripts.cli market             # BCB + Yahoo
    python -m scripts.cli user <usuario>     # cria/troca senha
    python -m scripts.cli summary            # resumo no terminal
    python -m scripts.cli export <arquivo.xlsx>
    python -m scripts.cli curate <arquivo.json>  # aplica curadoria (apelidos, comerciantes, regras, ajustes) e reconstrói
"""
from __future__ import annotations

import getpass
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config.settings import get_settings  # noqa: E402
from app.database.migrate import migrate  # noqa: E402


def main(argv: list[str]) -> None:
    if not argv:
        print(__doc__)
        return
    cmd, args = argv[0], argv[1:]
    migrate()
    if cmd == "migrate":
        print("schema ok:", get_settings().database_url.split("@")[-1])
    elif cmd == "sync":
        from app.services.pipeline import pipeline
        print(json.dumps(pipeline.sync("cli", full="--full" in args), indent=2, default=str, ensure_ascii=False))
    elif cmd == "rebuild":
        from app.services.pipeline import pipeline
        print(json.dumps(pipeline.post_process("cli"), indent=2, default=str, ensure_ascii=False))
    elif cmd == "market":
        from app.services.pipeline import pipeline
        res = pipeline.market("cli")
        print(json.dumps({k: (v if k != "yahoo" else len(v)) for k, v in res.items()}, indent=2, default=str))
    elif cmd == "user":
        from app.auth.security import set_password
        username = args[0] if args else input("usuário: ")
        pwd = getpass.getpass("nova senha: ")
        set_password(username, pwd)
        print("ok")
    elif cmd == "summary":
        from app.analytics.summary import print_summary
        print_summary()
    elif cmd == "export":
        from app.analytics.export import export_xlsx
        out = Path(args[0] if args else "cfo-central-export.xlsx")
        out.write_bytes(export_xlsx())
        print("gerado:", out)
    elif cmd == "curate":
        from app.database.session import session_scope
        from app.services.curation import apply_curation_file
        from app.services.pipeline import pipeline
        with session_scope() as s:
            report = apply_curation_file(s, args[0])
        print(json.dumps(report, indent=2, ensure_ascii=False))
        res = pipeline.post_process("curadoria")
        print(json.dumps({k: v for k, v in res.items() if k in ("counts", "reviews")}, indent=2, default=str,
                         ensure_ascii=False))
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
