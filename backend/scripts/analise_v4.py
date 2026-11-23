#!/usr/bin/env python3
"""Analise versionada das rodadas oficiais (v4, preliminar, v3).

Somente biblioteca padrao. Nao altera resultados: apenas leitura e saida
em 04-ARTEFATOS/analise-v4/.

Uso:
  python3 scripts/analise_v4.py experiments/official-v4-142-732/results.json \
      --outdir ../04-ARTEFATOS/analise-v4 --sufixo "" \
      --catalog artefatos/oficiais/catalogo-experimental-142-v2.json
"""

import argparse
import csv
import hashlib
import json
import os
import random
import statistics
import sys
from collections import defaultdict

CENARIOS = ["curto", "medio", "longo"]
PERFIS = ["litoral", "cultural", "gastronomico", "diversificado"]
ESTRATEGIAS = ["baseline_random", "personalized", "personalized_id"]

METRICAS = [
    "compatibility_media",
    "compatibility_media_normalized",
    "cobertura_interesses",
    "inserted_activity_count",
    "zero_score_inserted_count",
    "total_distance_m",
    "total_travel_minutes",
    "distancia_por_atividade",
]
MENOR_MELHOR = {"total_distance_m", "total_travel_minutes", "distancia_por_atividade"}

CATALOG_PT2EN = {
    "id": "id",
    "nome": "name",
    "tipo": "type",
    "lat": "lat",
    "lon": "lon",
    "cidade": "city",
    "origem_bloco": "origin_block",
    "categorias": "categories",
    "duracao_estimada_min": "duration_estimated_min",
    "duracao_estimada_max": "duration_estimated_max",
    "fonte_duracao": "source_duration",
    "observacao_anotacao": "observation_annotation",
}
CATALOG_FIELDS = [
    "id", "name", "type", "lat", "lon", "city", "origin_block",
    "categories", "duration_estimated_min", "duration_estimated_max",
    "source_duration", "observation_annotation",
]
N_BASELINE = 30
SEED_RECALC = 20261116
N_RECALC = 40
TOLERANCIA = 1e-6


def raw_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def catalog_hash_compat(registros):
    """sha256 canonico do catalogo (normalizacao pt->en, ordenado por id)."""
    norm = []
    for r in registros:
        item = {}
        for campo_pt, campo_en in CATALOG_PT2EN.items():
            item[campo_en] = r.get(campo_pt)
        norm.append({f: item.get(f) for f in CATALOG_FIELDS})
    norm.sort(key=lambda i: i["id"] or "")
    payload = json.dumps(norm, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def carrega_resultados(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def valor_metrica(execucao, metrica):
    """Valor da metrica ou None se ausente (nao inventa)."""
    if metrica == "inserted_activity_count":
        v = execucao.get("inserted_activity_count")
        return None if v is None else float(v)
    if metrica in ("total_distance_m", "total_travel_minutes"):
        itin = execucao.get("itinerary_metrics") or {}
        v = itin.get(metrica)
        return None if v is None else float(v)
    if metrica == "distancia_por_atividade":
        n = execucao.get("inserted_activity_count")
        itin = execucao.get("itinerary_metrics") or {}
        d = itin.get("total_distance_m")
        if n is None or d is None or n == 0:
            return None
        return float(d) / float(n)
    # compatibility_media / normalized / cobertura / zero_score
    ev = execucao.get("evaluation_metrics") or {}
    mt = execucao.get("metrics") or {}
    if metrica in ev:
        return float(ev[metrica])
    if metrica in mt:
        return float(mt[metrica])
    return None


def coleta(dados):
    execucoes = []
    for e in dados["executions"]:
        if e.get("status") and e.get("status") not in ("completed", "succeeded"):
            continue
        vals = {m: valor_metrica(e, m) for m in METRICAS}
        ids = list((e.get("result") or {}).get("activities") or [])
        execucoes.append({
            "run_id": e.get("run_id"),
            "scenario_id": e.get("scenario_id"),
            "profile_id": e.get("profile_id"),
            "strategy": e.get("strategy"),
            "seed": e.get("seed"),
            "vals": vals,
            "ids": ids,
            "bruta": e,
        })
    return execucoes


def combinacoes(execs):
    conj = sorted({(e["scenario_id"], e["profile_id"]) for e in execs})
    ordem = sorted(conj, key=lambda cp: (CENARIOS.index(cp[0]) if cp[0] in CENARIOS else 99,
                                         PERFIS.index(cp[1]) if cp[1] in PERFIS else 99))
    return ordem


def grupo(execs, comb, estrategia):
    return [e for e in execs
            if (e["scenario_id"], e["profile_id"]) == comb and e["strategy"] == estrategia]


def estatistica(valores):
    vals = [v for v in valores if v is not None]
    n = len(vals)
    out = {"n": n}
    if n == 0:
        out.update({"mediana": None, "q1": None, "q3": None, "media": None, "desvio": None})
        return out
    out["mediana"] = statistics.median(vals)
    out["media"] = statistics.fmean(vals)
    out["desvio"] = statistics.stdev(vals) if n >= 2 else None
    if n >= 2:
        q = statistics.quantiles(vals, n=4, method="inclusive")
        out["q1"], out["q3"] = q[0], q[2]
    else:
        out["q1"], out["q3"] = None, None
    return out


def p_superioridade(valores_pers, valores_base):
    """P(personalized > baseline) em pares cruzados; empate = 0,5."""
    pares = [(p, b) for p in valores_pers for b in valores_base]
    if not pares:
        return None
    soma = 0.0
    for p, b in pares:
        if p > b:
            soma += 1.0
        elif p == b:
            soma += 0.5
    return soma / len(pares)


def fmt(v):
    if v is None:
        return ""
    if isinstance(v, float):
        return repr(v)
    return str(v)


def escreve_cabecalho(path, dados, execs, sha_raw):
    cont_estr = defaultdict(int)
    cont_comb = defaultdict(int)
    for e in execs:
        cont_estr[e["strategy"]] += 1
        cont_comb[(e["scenario_id"], e["profile_id"])] += 1
    linhas = []
    linhas.append(f"# cabecalho{SUFIXO}\n")
    linhas.append(f"- sha256(results.json): {sha_raw}")
    linhas.append(f"- code_version: {dados.get('code_version')}")
    linhas.append(f"- code_dirty: {dados.get('code_dirty')}")
    linhas.append(f"- catalog_hash: {dados.get('catalog_hash')}")
    linhas.append(f"- routing_matrix_hash: {dados.get('routing_matrix_hash')}")
    linhas.append(f"- tie_break: {dados.get('tie_break')}")
    linhas.append(f"- status: {dados.get('status')}")
    linhas.append(f"- created_at: {dados.get('created_at')}")
    linhas.append(f"- catalog_activity_count: {dados.get('catalog_activity_count')}")
    linhas.append(f"- total de execucoes lidas: {len(execs)}")
    linhas.append("")
    linhas.append("Contagem por estrategia:")
    for s in ESTRATEGIAS:
        linhas.append(f"- {s}: {cont_estr.get(s, 0)}")
    extras = set(cont_estr) - set(ESTRATEGIAS)
    for s in sorted(extras):
        linhas.append(f"- {s} (fora do esperado): {cont_estr[s]}")
    linhas.append("")
    linhas.append("Contagem por combinacao (esperado 61 = 30 + 30 + 1 na v4):")
    for comb in combinacoes(execs):
        linhas.append(f"- {comb[0]}-{comb[1]}: {cont_comb[comb]}")
    linhas.append("")
    linhas.append(f"- 12 x 61 = {12 * 61}; execucoes = {len(execs)}")
    linhas.append(f"- status geral: {dados.get('status')}")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(linhas) + "\n")


def escreve_estatisticas(path, execs):
    comb_list = combinacoes(execs)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["combinacao", "estrategia", "metrica", "n", "mediana", "q1", "q3",
                    "media", "desvio_padrao"])
        for comb in comb_list:
            for s in ESTRATEGIAS:
                g = grupo(execs, comb, s)
                if not g:
                    continue
                for m in METRICAS:
                    vals = [e["vals"].get(m) for e in g]
                    if all(v is None for v in vals):
                        w.writerow([f"{comb[0]}-{comb[1]}", s, m, "ausente",
                                    "ausente", "ausente", "ausente", "ausente", "ausente"])
                        continue
                    est = estatistica(vals)
                    w.writerow([f"{comb[0]}-{comb[1]}", s, m,
                                est["n"], fmt(est["mediana"]), fmt(est["q1"]), fmt(est["q3"]),
                                fmt(est["media"]), fmt(est["desvio"])])


def escreve_comparacao(path, execs):
    comb_list = combinacoes(execs)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["combinacao", "metrica", "mediana_personalized",
                    "mediana_baseline_random", "personalized_id",
                    "diferenca_mediana", "rotulo", "p_superioridade", "nota"])
        for comb in comb_list:
            g_pers = grupo(execs, comb, "personalized")
            g_base = grupo(execs, comb, "baseline_random")
            g_pid = grupo(execs, comb, "personalized_id")
            for m in METRICAS:
                v_pers = [e["vals"].get(m) for e in g_pers]
                v_base = [e["vals"].get(m) for e in g_base]
                v_pid = [e["vals"].get(m) for e in g_pid]
                v_pers_ok = [v for v in v_pers if v is not None]
                v_base_ok = [v for v in v_base if v is not None]
                v_pid_ok = [v for v in v_pid if v is not None]
                if not v_pers_ok or not v_base_ok:
                    w.writerow([f"{comb[0]}-{comb[1]}", m, "ausente", "ausente",
                                fmt(v_pid_ok[0]) if v_pid_ok else "ausente",
                                "ausente", "ausente", "ausente",
                                "menor_melhor" if m in MENOR_MELHOR else ""])
                    continue
                med_p = statistics.median(v_pers_ok)
                med_b = statistics.median(v_base_ok)
                dif = med_p - med_b
                if med_p > med_b:
                    rot = "superior"
                elif med_p < med_b:
                    rot = "inferior"
                else:
                    rot = "igual"
                p = p_superioridade(v_pers_ok, v_base_ok)
                nota = "menor_melhor" if m in MENOR_MELHOR else ""
                w.writerow([f"{comb[0]}-{comb[1]}", m, fmt(med_p), fmt(med_b),
                            fmt(v_pid_ok[0]) if v_pid_ok else "ausente",
                            fmt(dif), rot, fmt(p), nota])


def escreve_contagens(path, execs, sufixo):
    comb_list = combinacoes(execs)
    linhas = [f"# contagens{sufixo}", "",
              "Comparacao por mediana: personalized vs baseline_random.", ""]
    linhas.append("| metrica | superior | igual | inferior | (de 12) | "
                  "sup_exc_div | ig_exc_div | inf_exc_div | (de 9) |")
    linhas.append("|---|---|---|---|---|---|---|---|---|")
    cont_tot = {}
    cont_div = {}
    menos_ativ = 0
    menos_ativ_div = 0
    for m in METRICAS:
        c_tot = {"superior": 0, "igual": 0, "inferior": 0}
        c_div = {"superior": 0, "igual": 0, "inferior": 0}
        for comb in comb_list:
            g_pers = grupo(execs, comb, "personalized")
            g_base = grupo(execs, comb, "baseline_random")
            v_pers = [e["vals"].get(m) for e in g_pers if e["vals"].get(m) is not None]
            v_base = [e["vals"].get(m) for e in g_base if e["vals"].get(m) is not None]
            n_at_p = [e["vals"].get("inserted_activity_count") for e in g_pers
                      if e["vals"].get("inserted_activity_count") is not None]
            n_at_b = [e["vals"].get("inserted_activity_count") for e in g_base
                      if e["vals"].get("inserted_activity_count") is not None]
            if not v_pers or not v_base:
                continue
            med_p = statistics.median(v_pers)
            med_b = statistics.median(v_base)
            if med_p > med_b:
                c_tot["superior"] += 1
            elif med_p < med_b:
                c_tot["inferior"] += 1
            else:
                c_tot["igual"] += 1
            if comb[1] != "diversificado":
                if med_p > med_b:
                    c_div["superior"] += 1
                elif med_p < med_b:
                    c_div["inferior"] += 1
                else:
                    c_div["igual"] += 1
            if m == "inserted_activity_count" and n_at_p and n_at_b:
                if statistics.median(n_at_p) < statistics.median(n_at_b):
                    menos_ativ += 1
                    if comb[1] != "diversificado":
                        menos_ativ_div += 1
        cont_tot[m] = c_tot
        cont_div[m] = c_div
        linhas.append(f"| {m} | {c_tot['superior']} | {c_tot['igual']} | {c_tot['inferior']} | 12 | "
                      f"{c_div['superior']} | {c_div['igual']} | {c_div['inferior']} | 9 |")
    linhas.append("")
    linhas.append(f"- Personalized insere MENOS atividades que a baseline (mediana de "
                  f"inserted_activity_count): {menos_ativ} de 12 combinacoes "
                  f"({menos_ativ_div} de 9 excluindo diversificado).")
    ausentes = [m for m in METRICAS if m not in cont_tot]
    if ausentes:
        linhas.append(f"- Metricas ausentes nesta rodada: {', '.join(ausentes)}.")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(linhas) + "\n")


def escreve_vies_id(path, execs, sufixo):
    def fracao_bloco(ids):
        if not ids:
            return None
        cnt = sum(1 for i in ids if i.startswith("atividade_")
                  and i[len("atividade_"):].isdigit()
                  and 1 <= int(i[len("atividade_"):]) <= 75)
        return cnt / len(ids)
    linhas = [f"# vies_id{sufixo}", "",
              "Mediana da fracao de atividades inseridas com id entre 0001 e 0075 "
              "(bloco 'pontos turisticos').", "",
              "| perfil | cenario | estrategia | n | mediana_fracao |",
              "|---|---|---|---|---|"]
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["perfil", "cenario", "estrategia", "n", "mediana_fracao"])
        for perfil in ["cultural", "diversificado", "gastronomico", "litoral"]:
            for cenario in CENARIOS:
                for s in ESTRATEGIAS:
                    g = [e for e in execs
                         if e["profile_id"] == perfil and e["scenario_id"] == cenario
                         and e["strategy"] == s]
                    vals = [fracao_bloco(e["ids"]) for e in g]
                    vals = [v for v in vals if v is not None]
                    if not vals:
                        w.writerow([perfil, cenario, s, 0, "ausente"])
                        linhas.append(f"| {perfil} | {cenario} | {s} | 0 | ausente |")
                        continue
                    med = statistics.median(vals)
                    w.writerow([perfil, cenario, s, len(vals), fmt(med)])
                    linhas.append(f"| {perfil} | {cenario} | {s} | {len(vals)} | {fmt(med)} |")
    md_path = os.path.splitext(path)[0] + ".md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(linhas) + "\n")


def escreve_dupla_categoria(path, execs):
    def contagem_dupla(g):
        out = {}
        for aid in ["atividade_0005", "atividade_0127"]:
            vals = [sum(1 for i in e["ids"] if i == aid) for e in g]
            if vals:
                out[aid] = (min(vals), statistics.median(vals), max(vals))
            else:
                out[aid] = None
        return out
    comb_list = combinacoes(execs)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["combinacao", "estrategia", "n",
                    "a0005_min", "a0005_mediana", "a0005_max",
                    "a0127_min", "a0127_mediana", "a0127_max"])
        for comb in comb_list:
            for s in ESTRATEGIAS:
                g = grupo(execs, comb, s)
                if not g:
                    continue
                c = contagem_dupla(g)
                row = [f"{comb[0]}-{comb[1]}", s, len(g)]
                for aid, pref in [("atividade_0005", "a0005"), ("atividade_0127", "a0127")]:
                    v = c[aid]
                    if v is None:
                        row += ["ausente", "ausente", "ausente"]
                    else:
                        row += [fmt(v[0]), fmt(v[1]), fmt(v[2])]
                w.writerow(row)


# ---------------- verificações (Etapa 2) ----------------

CHECKS_FALHOU = []


def check_ok(msg):
    print(f"OK: {msg}")


def check_falha(msg):
    CHECKS_FALHOU.append(msg)
    print(f"FALHA: {msg}")


def verifica_baseline_consistente(execs):
    """a) baseline_random igual entre perfis por (cenario, semente)."""
    grupos = defaultdict(list)
    for e in execs:
        if e["strategy"] == "baseline_random":
            grupos[(e["scenario_id"], e["seed"])].append(e)
    falhas = 0
    for chave, g in sorted(grupos.items(), key=lambda kv: str(kv[0])):
        ids0 = g[0]["ids"]
        d0 = g[0]["vals"]["total_distance_m"]
        t0 = g[0]["vals"]["total_travel_minutes"]
        for e in g[1:]:
            if e["ids"] != ids0:
                falhas += 1
                check_falha(f"baseline {chave} {e['profile_id']}: ids divergem")
                break
            if e["vals"]["total_distance_m"] != d0 or e["vals"]["total_travel_minutes"] != t0:
                falhas += 1
                check_falha(f"baseline {chave} {e['profile_id']}: distancia/tempo divergem "
                            f"({e['vals']['total_distance_m']} vs {d0}, "
                            f"{e['vals']['total_travel_minutes']} vs {t0})")
                break
    n_grupos = len(grupos)
    if falhas == 0:
        check_ok(f"baseline identica entre os 4 perfis em {n_grupos} grupos "
                 f"(cenario, semente): ids, total_distance_m e total_travel_minutes")


def verifica_contagens(dados, execs):
    """b) total = 732 e 61 por combinacao (30 + 30 + 1) na v4; adaptado nas antigas."""
    combs = combinacoes(execs)
    esperado_pid = "personalized_id" in {e["strategy"] for e in execs}
    n_pers = len({e["seed"] for e in execs if e["strategy"] == "personalized"})
    total_ok = True
    if len(combs) != 12:
        total_ok = False
        check_falha(f"número de combinações = {len(combs)} (esperado 12)")
    for comb in combs:
        nb = len(grupo(execs, comb, "baseline_random"))
        np_ = len(grupo(execs, comb, "personalized"))
        ni = len(grupo(execs, comb, "personalized_id")) if esperado_pid else 0
        exp = N_BASELINE + np_ + (1 if esperado_pid else 0)
        if nb != N_BASELINE or np_ != n_pers or ni != (1 if esperado_pid else 0):
            total_ok = False
            check_falha(f"{comb[0]}-{comb[1]}: baseline={nb} personalized={np_} "
                        f"personalized_id={ni} (esperado {N_BASELINE}/{n_pers}/"
                        f"{1 if esperado_pid else 0})")
    total = len(execs)
    por_comb = total / len(combs) if combs else 0
    if total_ok:
        if esperado_pid:
            check_ok(f"contagens: total={total}, 12 combinacoes, "
                     f"{N_BASELINE} baseline + {n_pers} personalized + 1 personalized_id "
                     f"por combinacao; total/comb = {por_comb}")
        else:
            check_ok(f"contagens (rodada sem personalized_id): total={total}, "
                     f"12 combinacoes, {N_BASELINE} baseline + {n_pers} personalized "
                     f"por combinacao; total/comb = {por_comb}")


def verifica_recalculo(dados, execs, catalogo):
    """c) recalcular compatibility_media em 40 execuções."""
    if catalogo is None:
        print("aviso: recalc 'compatibility_media' pulado (sem --catalog)")
        return
    reg = catalogo["registros"] if isinstance(catalogo, dict) else catalogo
    hash_calc = catalog_hash_compat(reg)
    hash_alvo = dados.get("catalog_hash")
    if hash_calc != hash_alvo:
        print(f"aviso: hash do catalogo informado ({hash_calc}) difere do "
              f"catalog_hash da rodada ({hash_alvo}); recalc pulado (nao conferivel)")
        return
    check_ok(f"catalog_hash confere com catalogo informado: {hash_calc}")
    categorias = {r["id"]: (r.get("categorias") or []) for r in reg}
    run_ids = sorted(e["run_id"] for e in execs if e["run_id"] is not None)
    amostra = random.Random(SEED_RECALC).sample(run_ids, min(N_RECALC, len(run_ids)))
    por_run = {e["run_id"]: e for e in execs}
    max_dif = 0.0
    falhas = 0
    for rid in amostra:
        e = por_run[rid]
        pesos = e["bruta"].get("profile_weights") or {}
        ativos = {c: w for c, w in pesos.items() if isinstance(w, (int, float)) and w > 0}
        soma_ativa = sum(ativos.values())
        if not e["ids"] or soma_ativa <= 0:
            calc = None
        else:
            ss = []
            for aid in e["ids"]:
                cats = categorias.get(aid, [])
                ss.append(sum(ativos[c] for c in cats if c in ativos) / soma_ativa)
            calc = sum(ss) / len(ss)
        arm = e["vals"].get("compatibility_media")
        if calc is None or arm is None:
            if calc is not None or arm is not None:
                falhas += 1
                check_falha(f"{rid}: compatibility_media ausente/indefinida "
                            f"(calc={calc}, armazenado={arm})")
            continue
        dif = abs(calc - arm)
        max_dif = max(max_dif, dif)
        if dif > TOLERANCIA:
            falhas += 1
            check_falha(f"{rid}: compatibility_media recalculada {calc} != "
                        f"armazenada {arm} (dif {dif})")
    if falhas == 0:
        check_ok(f"recalculo de compatibility_media em {len(amostra)} execucoes: "
                 f"max diferenca absoluta = {max_dif:.3e} (tolerancia {TOLERANCIA})")
        if max_dif > 0:
            check_ok(f"arredondamento observado: maior diferenca "
                     f"calculada-armazenada = {max_dif!r}")


def verifica_execucao_alvo(execs):
    """d) curto-litoral personalized semente 1001."""
    alvo = [e for e in execs if e["scenario_id"] == "curto" and e["profile_id"] == "litoral"
            and e["strategy"] == "personalized" and e["seed"] == 1001]
    if not alvo:
        print("aviso: execucao curto-litoral personalized semente 1001 nao encontrada")
        return
    e = alvo[0]
    bruta = e["bruta"]
    itin = bruta.get("itinerary_metrics") or {}
    print("--- Etapa 2d: curto-litoral personalized seed 1001 (conforme gravado) ---")
    print(f"run_id: {e['run_id']}")
    for dia in (bruta.get("result") or {}).get("itinerary", {}).get("days", []):
        print(f"dia {dia.get('day')}: ids={dia.get('activities')}")
    print(f"total_distance_m: {itin.get('total_distance_m')}")
    print(f"total_travel_minutes: {itin.get('total_travel_minutes')}")
    print(f"total_visit_minutes: {itin.get('total_visit_minutes')}")
    for dia in itin.get("days", []):
        print(f"occupancy dia {dia.get('day')}: {dia.get('occupancy')}")
    print("--- fim 2d ---")


def main():
    global SUFIXO
    ap = argparse.ArgumentParser()
    ap.add_argument("results")
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--sufixo", default="")
    ap.add_argument("--catalog", default=None)
    ap.add_argument("--sem-verificacoes", action="store_true")
    args = ap.parse_args()
    SUFIXO = args.sufixo

    dados = carrega_resultados(args.results)
    execs = coleta(dados)
    sha_raw = raw_sha256(args.results)
    os.makedirs(args.outdir, exist_ok=True)

    escreve_cabecalho(os.path.join(args.outdir, f"cabecalho{SUFIXO}.md"),
                      dados, execs, sha_raw)
    escreve_estatisticas(os.path.join(args.outdir, f"estatisticas{SUFIXO}.csv"), execs)
    escreve_comparacao(os.path.join(args.outdir, f"comparacao{SUFIXO}.csv"), execs)
    escreve_contagens(os.path.join(args.outdir, f"contagens{SUFIXO}.md"), execs, SUFIXO)
    escreve_vies_id(os.path.join(args.outdir, f"vies_id{SUFIXO}.csv"), execs, SUFIXO)
    escreve_dupla_categoria(os.path.join(args.outdir, f"dupla_categoria{SUFIXO}.csv"), execs)

    if not args.sem_verificacoes:
        print("=== verificacoes ===")
        verifica_baseline_consistente(execs)
        verifica_contagens(dados, execs)
        catalogo = None
        if args.catalog and os.path.exists(args.catalog):
            with open(args.catalog, "r", encoding="utf-8") as f:
                catalogo = json.load(f)
        elif args.catalog:
            print(f"aviso: catalogo informado nao encontrado: {args.catalog}")
        verifica_recalculo(dados, execs, catalogo)
        verifica_execucao_alvo(execs)
        if CHECKS_FALHOU:
            print(f"verificacoes concluidas com {len(CHECKS_FALHOU)} FALHA(s)")
            sys.exit(1)
        print("verificacoes concluidas: todas OK")
    else:
        print("verificacoes puladas (--sem-verificacoes)")
    sys.exit(0)


SUFIXO = ""

if __name__ == "__main__":
    main()
