"""
Importa planilha de atendimentos para a tabela `atendimentos` no MySQL.

Tempo de espera (padrão): diferença entre data/hora de recepção (chegada) e data/hora de fim
(colunas DT_Recepcao e DT_FilaFim, ou equivalentes — ver ALIASES abaixo).

Fallback (planilhas antigas): Dt_Inicio + hora_inicio + AtendimentoEmSeg (segundos).

Uso:
  cd backend
  python scripts/import_excel.py --file "C:\\Users\\...\\arquivo.xlsx" --truncate
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime

import pandas as pd
import pymysql

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.config import get_settings  # noqa: E402
from app.db import connection_kwargs  # noqa: E402

DIAS_PT = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]

# (nome normalizado minúsculas com hífen virando _, nome canônico na linha)
ALIASES_TO_CANON: list[tuple[str, str]] = [
    ("dt_recepcao", "DT_Recepcao"),
    ("dthora_recepcao", "DT_Recepcao"),
    ("dt_filafim", "DT_FilaFim"),
    ("dthora_fim", "DT_FilaFim"),
    ("dt_inicio", "Dt_Inicio"),
    ("hora_inicio", "hora_inicio"),
    ("ds_unidade", "DS_Unidade"),
    ("ds_cbo", "DS_CBO"),
    ("atendimentoemseg", "AtendimentoEmSeg"),
    ("ds_corclassificacao", "DS_CorClassificacao"),
]


def _norm_key(k: str) -> str:
    return str(k).strip().lower().replace("-", "_")


def _norm_row(r: dict) -> dict:
    out = {str(k).strip(): v for k, v in r.items()}
    by_norm = {_norm_key(k): k for k in out}
    for alias_norm, canon in ALIASES_TO_CANON:
        if alias_norm in by_norm and canon not in out:
            orig_key = by_norm[alias_norm]
            out[canon] = out[orig_key]
    return out


def parse_datetime(val) -> datetime | None:
    """Interpreta data/hora completa (recepção, fim de fila, etc.)."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    if isinstance(val, pd.Timestamp):
        if pd.isna(val):
            return None
        return val.to_pydatetime()
    if isinstance(val, datetime):
        return val
    if isinstance(val, date) and not isinstance(val, datetime):
        return datetime.combine(val, datetime.min.time())
    s = str(val).strip()
    if not s:
        return None
    try:
        return pd.to_datetime(s).to_pydatetime()
    except Exception:
        return None


def parse_date(val) -> datetime | None:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    if isinstance(val, pd.Timestamp):
        if pd.isna(val):
            return None
        return val.to_pydatetime()
    if isinstance(val, date) and not isinstance(val, datetime):
        return datetime.combine(val, datetime.min.time())
    if isinstance(val, datetime):
        return val
    s = str(val).strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s[:10], fmt)
        except ValueError:
            continue
    try:
        return pd.to_datetime(s).to_pydatetime()
    except Exception:
        return None


def parse_time(val) -> str | None:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    if hasattr(val, "strftime"):
        return val.strftime("%H:%M:%S")
    s = str(val).strip()
    if not s:
        return None
    parts = s.replace(".", ":").split(":")
    if len(parts) >= 2:
        h, m = int(parts[0]), int(parts[1])
        sec = int(float(parts[2])) if len(parts) > 2 else 0
        return f"{h:02d}:{m:02d}:{sec:02d}"
    return None


def row_to_tuple(r: dict) -> tuple | None:
    r = _norm_row(r)
    unidade = str(r.get("DS_Unidade") or "").strip()
    esp = str(r.get("DS_CBO") or "").strip()
    if not unidade or not esp:
        return None
    risco = r.get("DS_CorClassificacao")
    risco_s = None if risco is None or (isinstance(risco, float) and pd.isna(risco)) else str(risco).strip()

    t_recep = parse_datetime(r.get("DT_Recepcao"))
    t_fim = parse_datetime(r.get("DT_FilaFim")) or parse_datetime(r.get("Dt_Fim"))

    if t_recep and t_fim:
        delta_min = (t_fim - t_recep).total_seconds() / 60.0
        if delta_min < 0:
            return None
        minutos = round(delta_min, 2)
        data_d = t_recep.date()
        hora_str = t_recep.strftime("%H:%M:%S")
        dia = DIAS_PT[t_recep.weekday()]
    else:
        d = parse_date(r.get("Dt_Inicio"))
        if not d:
            return None
        hora_str = parse_time(r.get("hora_inicio"))
        if not hora_str:
            return None
        seg = r.get("AtendimentoEmSeg")
        if seg is None or (isinstance(seg, float) and pd.isna(seg)):
            return None
        try:
            minutos = round(float(seg) / 60.0, 2)
        except (TypeError, ValueError):
            return None
        diadt = d if isinstance(d, datetime) else datetime.combine(d, datetime.min.time())
        data_d = diadt.date()
        dia = DIAS_PT[diadt.weekday()]

    return (
        unidade,
        esp,
        data_d,
        hora_str,
        dia,
        minutos,
        risco_s or None,
    )


def _excel_has_required_columns(cols: list[str]) -> tuple[bool, str]:
    n = {_norm_key(c) for c in cols}
    if not {"ds_unidade", "ds_cbo"} <= n:
        return False, "Faltam colunas DS_Unidade e/ou DS_CBO."
    recep = bool(n & {"dt_recepcao", "dthora_recepcao"})
    fim = bool(n & {"dt_filafim", "dthora_fim", "dt_fim"})
    legacy = {"dt_inicio", "hora_inicio", "atendimentoemseg"} <= n
    if recep and fim:
        return True, "recep+fim"
    if legacy:
        return True, "legacy"
    return (
        False,
        "Precisa de (DT_Recepcao ou dthora_recepcao) E (DT_FilaFim, Dt_Fim ou dthora_fim), "
        "OU o conjunto legado Dt_Inicio + hora_inicio + AtendimentoEmSeg.",
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--file",
        default=os.path.join(
            os.path.expanduser("~"),
            "Downloads",
            "Tempo de Espera x Atendimento 1.xlsx",
        ),
    )
    ap.add_argument("--truncate", action="store_true")
    args = ap.parse_args()

    get_settings()  # garante .env carregado
    conn = pymysql.connect(**connection_kwargs())
    try:
        with conn.cursor() as cur:
            if args.truncate:
                cur.execute("TRUNCATE TABLE atendimentos")
                conn.commit()
                print("Tabela atendimentos truncada.")

        print(f"Lendo {args.file} ...")
        df = pd.read_excel(args.file)
        df.columns = [str(c).strip() for c in df.columns]

        ok, mode = _excel_has_required_columns(list(df.columns))
        if not ok:
            raise SystemExit(f"{mode}\nColunas encontradas: {list(df.columns)}")

        print(f"Modo de importação: {mode} (espera = recepção → fim, quando possível).")

        batch: list[tuple] = []
        skipped = 0
        inserted = 0
        for _, row in df.iterrows():
            tup = row_to_tuple(row.to_dict())
            if tup is None:
                skipped += 1
                continue
            batch.append(tup)
            if len(batch) >= 2000:
                _insert_batch(conn, batch)
                inserted += len(batch)
                batch.clear()
                print(".", end="", flush=True)
        if batch:
            _insert_batch(conn, batch)
            inserted += len(batch)
        print(f"\nImportação concluída. Inseridas: {inserted}. Ignoradas: {skipped}.")
        if inserted == 0 and len(df) > 0:
            print(
                "AVISO: nenhuma linha inserida. Confira DT_Recepcao, DT_FilaFim/Dt_Fim (ou legado), "
                "DS_Unidade e DS_CBO. Primeira linha (amostra):"
            )
            print(df.iloc[0].to_dict())
    finally:
        conn.close()


def _insert_batch(conn, batch: list[tuple]):
    sql = """
        INSERT INTO atendimentos
        (unidade, especialidade, data_atendimento, hora_atendimento, dia_semana, tempo_espera_minutos, classificacao_risco)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """
    with conn.cursor() as cur:
        cur.executemany(sql, batch)
    conn.commit()


if __name__ == "__main__":
    main()
