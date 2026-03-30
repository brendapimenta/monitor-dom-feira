"""
monitor_dom.py
Monitora o Diário Oficial de Feira de Santana e atualiza o Notion
quando encontra publicações relacionadas às movimentações pendentes.
"""

import os
import re
import json
import requests
from datetime import date
from playwright.sync_api import sync_playwright


# ─── Configurações ────────────────────────────────────────────────────────────
NOTION_TOKEN        = os.environ["NOTION_TOKEN"]
MOVIMENTACOES_DB_ID = os.environ["MOVIMENTACOES_DB_ID"]   # ID do BD Movimentações
DOM_BASE_URL        = "https://diariooficial.feiradesantana.ba.gov.br"

HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28",
}

STATUS_PENDENTES = ["SOLICITADO", "EM PROCESSAMENTO"]


# ─── 1. Buscar movimentações pendentes no Notion ───────────────────────────────
def buscar_pendentes():
    url = f"https://api.notion.com/v1/databases/{MOVIMENTACOES_DB_ID}/query"
    payload = {
        "filter": {
            "or": [
                {"property": "Status", "select": {"equals": s}}
                for s in STATUS_PENDENTES
            ]
        }
    }
    r = requests.post(url, headers=HEADERS, json=payload)
    r.raise_for_status()
    results = r.json().get("results", [])

    pendentes = []
    for page in results:
        props = page["properties"]
        nome = props.get("SERVIDOR", {}).get("title", [])
        nome_texto = nome[0]["plain_text"] if nome else ""
        if nome_texto:
            pendentes.append({
                "page_id": page["id"],
                "nome": nome_texto.upper(),
            })

    print(f"[Notion] {len(pendentes)} movimentação(ões) pendente(s) encontrada(s).")
    return pendentes


# ─── 2. Coletar links de PDFs do DOM do dia ───────────────────────────────────
def coletar_pdfs_do_dia():
    hoje = date.today().strftime("%d/%m/%Y")
    pdfs = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        print(f"[DOM] Acessando site... (edição de {hoje})")
        page.goto(DOM_BASE_URL, timeout=30000)
        page.wait_for_load_state("networkidle", timeout=20000)

        # Coletar todos os links de PDF da página
        links = page.eval_on_selector_all(
            "a[href$='.pdf']",
            "els => els.map(e => e.href)"
        )
        browser.close()

    # Filtrar apenas PDFs do dia de hoje (a URL contém a data no formato DDMMYYYY)
    data_url = date.today().strftime("%d%m%Y")
    for link in links:
        if data_url in link:
            pdfs.append(link)

    # Se não encontrou com filtro de data, pegar todos os PDFs listados
    if not pdfs:
        pdfs = links

    print(f"[DOM] {len(pdfs)} PDF(s) encontrado(s) para hoje.")
    return pdfs


# ─── 3. Baixar e extrair texto de um PDF ──────────────────────────────────────
def extrair_texto_pdf(url_pdf):
    try:
        r = requests.get(url_pdf, timeout=30)
        r.raise_for_status()

        import io
        import pypdf

        reader = pypdf.PdfReader(io.BytesIO(r.content))
        texto = ""
        for pg in reader.pages:
            texto += pg.extract_text() or ""
        return texto.upper()
    except Exception as e:
        print(f"  [!] Erro ao processar {url_pdf}: {e}")
        return ""


# ─── 4. Extrair número do ato/edição do texto do PDF ──────────────────────────
def extrair_numero_ato(texto, nome_servidor):
    """Tenta capturar o número da portaria/resolução mais próxima do nome."""
    # Procura por padrões como "Nº 123/2026", "PORTARIA Nº 45/2026"
    padrao = r"(?:PORTARIA|RESOLU[ÇC][ÃA]O|ATO|DECRETO)\s+N[ºo°]?\s*(\d+[\/\-]\d{4})"
    matches = list(re.finditer(padrao, texto))

    # Encontrar a posição do nome no texto
    pos_nome = texto.find(nome_servidor)
    if pos_nome == -1:
        return ""

    # Pegar o número de ato mais próximo ANTES do nome
    mais_proximo = ""
    menor_distancia = float("inf")
    for m in matches:
        dist = abs(m.start() - pos_nome)
        if dist < menor_distancia:
            menor_distancia = dist
            mais_proximo = m.group(0)

    return mais_proximo


def extrair_edicao(texto):
    """Extrai o número da edição do DOM."""
    m = re.search(r"EDI[ÇC][ÃA]O\s+(\d+)", texto)
    return m.group(1) if m else ""


# ─── 5. Atualizar movimentação no Notion ──────────────────────────────────────
def atualizar_notion(page_id, url_pdf, num_ato, edicao):
    info = f"Edição {edicao} | {num_ato}" if edicao else num_ato
    url = f"https://api.notion.com/v1/pages/{page_id}"
    payload = {
        "properties": {
            "Status": {"select": {"name": "PUBLICADO NO DOM"}},
            "Nº DO ATO / DOM": {"rich_text": [{"text": {"content": info}}]},
            "OBSERVAÇÕES": {
                "rich_text": [{
                    "text": {"content": f"Publicado em {date.today().strftime('%d/%m/%Y')}. PDF: {url_pdf}"}
                }]
            },
        }
    }
    r = requests.patch(url, headers=HEADERS, json=payload)
    r.raise_for_status()
    print(f"  ✅ Notion atualizado para página {page_id}")


# ─── 6. Pipeline principal ────────────────────────────────────────────────────
def main():
    print("=" * 60)
    print(f"Monitor DOM — {date.today().strftime('%d/%m/%Y')}")
    print("=" * 60)

    pendentes = buscar_pendentes()
    if not pendentes:
        print("Nenhuma movimentação pendente. Encerrando.")
        return

    pdfs = coletar_pdfs_do_dia()
    if not pdfs:
        print("Nenhum PDF encontrado no DOM hoje. Encerrando.")
        return

    encontrados = 0
    for url_pdf in pdfs:
        print(f"\n[PDF] Processando: {url_pdf}")
        texto = extrair_texto_pdf(url_pdf)
        if not texto:
            continue

        edicao = extrair_edicao(texto)

        for mov in pendentes:
            nome = mov["nome"]
            if nome in texto:
                print(f"  ✓ Encontrado: {nome}")
                num_ato = extrair_numero_ato(texto, nome)
                atualizar_notion(mov["page_id"], url_pdf, num_ato, edicao)
                encontrados += 1

    print(f"\n{'=' * 60}")
    print(f"Concluído. {encontrados} movimentação(ões) atualizada(s) no Notion.")


if __name__ == "__main__":
    main()
