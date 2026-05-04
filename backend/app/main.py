from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .config import get_settings
from .db import get_conn

app = FastAPI(
    title="Motor de Busca — Tempo de Espera (Santana de Parnaíba)",
    description="API de apoio à decisão com dados históricos de atendimento.",
    version="1.0.0",
)

_settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings["cors_origins"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DIAS_PT = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]


class SearchBody(BaseModel):
    q: Optional[str] = Field(None, description="Busca geral em unidade ou especialidade")
    unidade: Optional[str] = None
    especialidade: Optional[str] = None
    dia_semana: Optional[str] = None
    hora: Optional[int] = Field(None, ge=0, le=23, description="Hora do dia (0–23)")


def _search_sql(
    q: Optional[str],
    unidade: Optional[str],
    especialidade: Optional[str],
    dia_semana: Optional[str],
    hora: Optional[int],
) -> tuple[str, list[Any]]:
    where: list[str] = ["1=1"]
    params: list[Any] = []

    if q and q.strip():
        like = f"%{q.strip()}%"
        where.append("(unidade LIKE %s OR especialidade LIKE %s)")
        params.extend([like, like])

    if unidade and unidade.strip():
        where.append("unidade LIKE %s")
        params.append(f"%{unidade.strip()}%")

    if especialidade and especialidade.strip():
        where.append("especialidade LIKE %s")
        params.append(f"%{especialidade.strip()}%")

    if dia_semana and dia_semana.strip():
        where.append("dia_semana = %s")
        params.append(dia_semana.strip())

    if hora is not None:
        where.append("HOUR(hora_atendimento) = %s")
        params.append(hora)

    where_sql = " AND ".join(where)

    esp_label = (
        especialidade.strip()
        if especialidade and especialidade.strip()
        else "Todas as especialidades (média agregada)"
    )
    hora_label = f"{hora:02d}h" if hora is not None else "Todas as horas do dia"
    dia_label = dia_semana.strip() if dia_semana and dia_semana.strip() else "Todos os dias da semana"

    sql = f"""
        SELECT
            unidade AS nome_unidade,
            ROUND(AVG(tempo_espera_minutos), 1) AS tempo_medio_minutos,
            %s AS especialidade,
            %s AS horario_analisado,
            %s AS dia_semana_retorno,
            COUNT(*) AS amostras
        FROM atendimentos
        WHERE {where_sql}
        GROUP BY unidade
        HAVING COUNT(*) >= 1
        ORDER BY tempo_medio_minutos ASC
        LIMIT 3
    """
    return sql, [esp_label, hora_label, dia_label, *params]


@app.get("/api/health")
def health():
    """HTTP 200 sempre (para health check em PaaS como Render); campo `db` indica MySQL."""
    try:
        with get_conn() as c:
            with c.cursor() as cur:
                cur.execute("SELECT 1 AS ok")
                row = cur.fetchone()
        ok = bool(row and row.get("ok") == 1)
        return {"status": "ok", "db": ok}
    except Exception as e:
        return {"status": "degraded", "db": False, "detail": f"Banco indisponível: {e!s}"}


@app.get("/api/meta")
def meta():
    with get_conn() as c:
        with c.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT unidade FROM atendimentos ORDER BY unidade LIMIT 500"
            )
            unidades = [r["unidade"] for r in cur.fetchall()]
            cur.execute(
                "SELECT DISTINCT especialidade FROM atendimentos ORDER BY especialidade LIMIT 500"
            )
            especialidades = [r["especialidade"] for r in cur.fetchall()]
            cur.execute("SELECT COUNT(*) AS total_registros FROM atendimentos")
            total_row = cur.fetchone()
            total_registros = int(total_row["total_registros"] if total_row else 0)
    return {
        "dias_semana": DIAS_PT,
        "horas": list(range(24)),
        "unidades": unidades,
        "especialidades": especialidades,
        "total_registros": total_registros,
    }


@app.get("/api/suggest")
def suggest(term: str = Query("", min_length=1), limit: int = Query(12, ge=1, le=50)):
    t = f"%{term.strip()}%"
    with get_conn() as c:
        with c.cursor() as cur:
            cur.execute(
                """
                SELECT label, tipo FROM (
                    SELECT DISTINCT unidade AS label, 'unidade' AS tipo
                    FROM atendimentos WHERE unidade LIKE %s
                    UNION
                    SELECT DISTINCT especialidade AS label, 'especialidade' AS tipo
                    FROM atendimentos WHERE especialidade LIKE %s
                ) x LIMIT %s
                """,
                (t, t, limit),
            )
            rows = cur.fetchall()
    return {"suggestions": [{"label": r["label"], "tipo": r["tipo"]} for r in rows]}


@app.post("/api/search")
def search(body: SearchBody):
    sql, params = _search_sql(
        body.q, body.unidade, body.especialidade, body.dia_semana, body.hora
    )
    with get_conn() as c:
        with c.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()

    results = []
    for r in rows:
        results.append(
            {
                "nome_unidade": r["nome_unidade"],
                "tempo_medio_minutos": float(r["tempo_medio_minutos"]),
                "especialidade": str(r["especialidade"]),
                "horario_analisado": str(r["horario_analisado"]),
                "dia_semana": str(r["dia_semana_retorno"]),
                "amostras": int(r["amostras"]),
            }
        )
    return {"top3": results, "mensagem_contexto": _mensagem_apoio(results, body)}


def _mensagem_apoio(results: list[dict], body: SearchBody) -> str:
    if not results:
        return "Não há dados históricos para essa combinação de filtros. Ajuste unidade, especialidade, dia ou hora."
    best = results[0]
    return (
        f"Melhor opção neste recorte: {best['nome_unidade']} "
        f"(tempo médio: {best['tempo_medio_minutos']} min — {best['amostras']} atendimentos analisados). "
        "Decisão de apoio com base em histórico, não em tempo real."
    )


@app.get("/api/insights/melhor-agora")
def melhor_agora(
    especialidade: Optional[str] = None,
):
    """Usa dia/hora atuais (Brasil) como filtro sugerido para orientação rápida."""
    from datetime import datetime

    now = datetime.now()
    dia = DIAS_PT[now.weekday()]
    hora = now.hour
    body = SearchBody(
        q=None,
        unidade=None,
        especialidade=especialidade,
        dia_semana=dia,
        hora=hora,
    )
    sql, params = _search_sql(
        body.q, body.unidade, body.especialidade, body.dia_semana, body.hora
    )
    with get_conn() as c:
        with c.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    if not rows:
        return {
            "dia": dia,
            "hora": hora,
            "destaque": None,
            "mensagem": "Sem amostras para o dia/hora atuais com esse filtro.",
        }
    r0 = rows[0]
    return {
        "dia": dia,
        "hora": hora,
        "destaque": {
            "nome_unidade": r0["nome_unidade"],
            "tempo_medio_minutos": float(r0["tempo_medio_minutos"]),
            "especialidade": r0["especialidade"],
        },
        "mensagem": (
            f"Melhor opção agora ({dia}, {hora:02d}h): {r0['nome_unidade']} "
            f"(tempo médio: {float(r0['tempo_medio_minutos'])} min)."
        ),
    }


@app.get("/api/charts/por-hora")
def chart_por_hora(
    unidade: Optional[str] = None,
    especialidade: Optional[str] = None,
    dia_semana: Optional[str] = None,
):
    where = ["1=1"]
    params: list[Any] = []
    if unidade:
        where.append("unidade LIKE %s")
        params.append(f"%{unidade}%")
    if especialidade:
        where.append("especialidade LIKE %s")
        params.append(f"%{especialidade}%")
    if dia_semana:
        where.append("dia_semana = %s")
        params.append(dia_semana)
    w = " AND ".join(where)
    sql = f"""
        SELECT HOUR(hora_atendimento) AS hora,
               ROUND(AVG(tempo_espera_minutos), 1) AS media_minutos
        FROM atendimentos
        WHERE {w}
        GROUP BY HOUR(hora_atendimento)
        ORDER BY hora
    """
    with get_conn() as c:
        with c.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    return {
        "serie": [
            {"hora": int(r["hora"]), "media_minutos": float(r["media_minutos"])}
            for r in rows
        ]
    }


@app.get("/api/charts/por-dia-semana")
def chart_por_dia(
    unidade: Optional[str] = None,
    especialidade: Optional[str] = None,
):
    where = ["1=1"]
    params: list[Any] = []
    if unidade:
        where.append("unidade LIKE %s")
        params.append(f"%{unidade}%")
    if especialidade:
        where.append("especialidade LIKE %s")
        params.append(f"%{especialidade}%")
    w = " AND ".join(where)
    sql = f"""
        SELECT dia_semana,
               ROUND(AVG(tempo_espera_minutos), 1) AS media_minutos
        FROM atendimentos
        WHERE {w}
        GROUP BY dia_semana
    """
    with get_conn() as c:
        with c.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    order = {d: i for i, d in enumerate(DIAS_PT)}
    serie = sorted(
        [
            {"dia": r["dia_semana"], "media_minutos": float(r["media_minutos"])}
            for r in rows
        ],
        key=lambda x: order.get(x["dia"], 99),
    )
    return {"serie": serie}


@app.get("/api/charts/comparacao-unidades")
def chart_unidades(
    especialidade: Optional[str] = None,
    dia_semana: Optional[str] = None,
    hora: Optional[int] = Query(None, ge=0, le=23),
    limit: int = Query(12, ge=3, le=30),
):
    where = ["1=1"]
    params: list[Any] = []
    if especialidade:
        where.append("especialidade LIKE %s")
        params.append(f"%{especialidade}%")
    if dia_semana:
        where.append("dia_semana = %s")
        params.append(dia_semana)
    if hora is not None:
        where.append("HOUR(hora_atendimento) = %s")
        params.append(hora)
    w = " AND ".join(where)
    sql = f"""
        SELECT unidade AS nome,
               ROUND(AVG(tempo_espera_minutos), 1) AS media_minutos
        FROM atendimentos
        WHERE {w}
        GROUP BY unidade
        ORDER BY media_minutos ASC
        LIMIT %s
    """
    params.append(limit)
    with get_conn() as c:
        with c.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    return {
        "serie": [
            {"unidade": r["nome"], "media_minutos": float(r["media_minutos"])}
            for r in rows
        ]
    }


_FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"


@app.get("/")
def spa_index():
    index = _FRONTEND_DIR / "index.html"
    if not index.is_file():
        raise HTTPException(404, "Frontend não encontrado.")
    return FileResponse(index)


@app.get("/styles.css")
def spa_css():
    p = _FRONTEND_DIR / "styles.css"
    if not p.is_file():
        raise HTTPException(404)
    return FileResponse(p, media_type="text/css")


@app.get("/app.js")
def spa_js():
    p = _FRONTEND_DIR / "app.js"
    if not p.is_file():
        raise HTTPException(404)
    return FileResponse(p, media_type="application/javascript")


@app.get("/fatec-logo.png")
def fatec_logo():
    p = _FRONTEND_DIR / "fatec-logo.png"
    if not p.is_file():
        raise HTTPException(404)
    return FileResponse(p, media_type="image/png")
