"""
monitor_dom.py
Monitora o Diário Oficial Municipal de Feira de Santana.
Captura publicações do Legislativo e menções à Câmara no Executivo.
Envia dados ao Notion e notifica via ntfy.
"""

import os
import re
import json
import datetime
import hashlib
import logging
import requests
import io
from pathlib import Path
from playwright.sync_api import sync_playwright

# ── LOGGING ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── CONFIG ───────────────────────────────────────────────────────────────────
NOTION_TOKEN  = os.environ["NOTION_TOKEN"]
MONITOR_DB_ID = os.environ["MONITOR_DOM_DB_ID"]   # c5d910a3-0f52-48d7-be40-a0c41f8a98e5
NTFY_URL      = os.environ.get("NTFY_URL", "")    # ex: https://ntfy.sh/meu-topico

DOM_BASE      = "https://diariooficial.feiradesantana.ba.gov.br"
CACHE_FILE    = Path("dom_cache.json")

HEADERS_NOTION = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}

# ── PALAVRAS-CHAVE ────────────────────────────────────────────────────────────
PALAVRAS_CAMARA = [
    "câmara municipal", "camara municipal", "câmara de vereadores",
    "vereador", "vereadora", "vereadores", "mesa diretora",
    "presidência da câmara", "presidente da câmara", "gabinete da presidência",
]

MARCADORES_LEGISLATIVO = [
    "poder legislativo", "câmara municipal de feira", "camara municipal de feira",
]

# ── CACHE ─────────────────────────────────────────────────────────────────────
def carregar_cache() -> set:
    if CACHE_FILE.exists():
        try:
            return set(json.loads(CACHE_FILE.read_text(encoding="utf-8")))
        except Exception:
            pass
    return set()

def salvar_cache(cache: set):
    CACHE_FILE.write_text(json.dumps(list(cache)), encoding="utf-8")

def hash_bloco(texto: str) -> str:
    return hashlib.md5(texto.strip().lower().encode()).hexdigest()

# ── SCRAPING COM PLAYWRIGHT ───────────────────────────────────────────────────
def buscar_pdf_hoje() -> tuple:
    """
    Acessa o DOM e retorna (url_pdf, edicao, data_str).
    Usa Playwright para renderizar JS.
    """
    hoje = datetime.date.today()
    log.info(f"Acessando DOM — {hoje.strftime('%d/%m/%Y')}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        try:
            page.goto(DOM_BASE, timeout=30000)
            page.wait_for_load_state("networkidle", timeout=20000)

            links = page.eval_on_selector_all(
                "a[href]",
                "els => els.map(e => ({href: e.href, text: e.innerText.trim()}))"
            )

            pdf_url = None
            edicao  = ""

            for link in links:
                href = link.get("href", "")
                texto = link.get("text", "")
                href_lower = href.lower()

                if any(x in href_lower for x in [".pdf", "download", "edicao", "diario", "visualizar"]):
                    pdf_url = href
                    edicao  = texto or href.split("/")[-1]
                    log.info(f"PDF encontrado: {edicao} → {href}")
                    break

            browser.close()

            if pdf_url:
                return pdf_url, edicao, hoje.isoformat()

            log.warning("Nenhum PDF encontrado na página do DOM.")
            return None, None, None

        except Exception as e:
            log.error(f"Erro no Playwright: {e}")
            browser.close()
            return None, None, None

# ── DOWNLOAD E EXTRAÇÃO ───────────────────────────────────────────────────────
def baixar_pdf(url: str) -> bytes:
    try:
        r = requests.get(url, timeout=60)
        r.raise_for_status()
        log.info(f"PDF baixado: {len(r.content):,} bytes")
        return r.content
    except Exception as e:
        log.error(f"Erro ao baixar PDF: {e}")
        return None

def extrair_texto(conteudo: bytes) -> str:
    try:
        import pypdf
        reader = pypdf.PdfReader(io.BytesIO(conteudo))
        partes = []
        for i, pag in enumerate(reader.pages):
            txt = pag.extract_text() or ""
            partes.append(f"[PAG:{i+1}]\n{txt}")
        texto = "\n\n".join(partes)
        log.info(f"Texto extraído: {len(texto):,} chars, {len(reader.pages)} páginas")
        return texto
    except Exception as e:
        log.error(f"Erro ao extrair texto: {e}")
        return ""

# ── SEGMENTAÇÃO ───────────────────────────────────────────────────────────────
def segmentar_blocos(texto: str) -> list:
    blocos = []
    secao_atual = "OUTROS"
    bloco_linhas = []

    for linha in texto.splitlines():
        linha_lower = linha.lower().strip()

        if any(m in linha_lower for m in MARCADORES_LEGISLATIVO):
            secao_atual = "LEGISLATIVO"
        elif "poder executivo" in linha_lower or "prefeitura municipal" in linha_lower:
            secao_atual = "EXECUTIVO"

        if not linha.strip() and bloco_linhas:
            texto_bloco = "\n".join(bloco_linhas).strip()
            if len(texto_bloco) > 50:
                blocos.append({"texto": texto_bloco, "secao": secao_atual})
            bloco_linhas = []
        else:
            bloco_linhas.append(linha)

    if bloco_linhas:
        texto_bloco = "\n".join(bloco_linhas).strip()
        if len(texto_bloco) > 50:
            blocos.append({"texto": texto_bloco, "secao": secao_atual})

    log.info(f"Segmentados {len(blocos)} blocos")
    return blocos

# ── CLASSIFICAÇÃO ─────────────────────────────────────────────────────────────
def deve_capturar(bloco: dict) -> bool:
    texto = bloco["texto"].lower()
    secao = bloco["secao"]
    if secao == "LEGISLATIVO":
        return True
    return any(p in texto for p in PALAVRAS_CAMARA)

def classificar_secao(bloco: dict) -> str:
    texto = bloco["texto"].lower()
    secao = bloco["secao"]
    if secao == "LEGISLATIVO":
        if any(p in texto for p in ["nomear", "exonerar", "nomeação", "exoneração", "aspa"]):
            return "PESSOAL"
        if any(p in texto for p in ["licitação", "pregão", "contrato", "dispensa", "edital"]):
            return "LICITAÇÕES"
        if any(p in texto for p in ["decreto", "portaria", "resolução"]):
            return "DECRETOS E PORTARIAS"
        return "LEGISLATIVO"
    if any(p in texto for p in ["licitação", "pregão", "contrato", "dispensa", "edital"]):
        return "LICITAÇÕES"
    if any(p in texto for p in ["decreto", "portaria", "resolução"]):
        return "DECRETOS E PORTARIAS"
    if any(p in texto for p in PALAVRAS_CAMARA):
        return "EXECUTIVO"
    return "OUTROS"

def classificar_tipo(texto: str) -> str:
    t = texto.lower()
    if any(p in t for p in ["nomear", "nomeação", "nomeado"]):
        return "NOMEAÇÃO"
    if any(p in t for p in ["exonerar", "exoneração", "exonerado"]):
        return "EXONERAÇÃO"
    if any(p in t for p in ["aspa", "gratificação", "adicional de"]):
        return "ALTERAÇÃO DE ASPA"
    if any(p in t for p in ["transferir", "transferência", "relotação"]):
        return "TRANSFERÊNCIA"
    if any(p in t for p in ["licitação", "pregão", "chamamento", "concorrência"]):
        return "LICITAÇÃO"
    if any(p in t for p in ["contrato", "aditivo", "inexigibilidade", "dispensa"]):
        return "CONTRATO"
    if "decreto" in t:
        return "DECRETO"
    if any(p in t for p in ["portaria", "resolução"]):
        return "PORTARIA"
    if any(p in t for p in PALAVRAS_CAMARA):
        return "MENÇÃO À CÂMARA"
    return "OUTRO"

def extrair_numero_ato(texto: str) -> str:
    padroes = [
        r"(?:portaria|decreto|resolução|edital|pregão|contrato)\s*n[°º\.]*\s*[\d\./\-]+",
        r"ato\s*n[°º\.]*\s*[\d\./\-]+",
        r"n[°º\.]\s*[\d\.\/\-]{3,}",
    ]
    for padrao in padroes:
        m = re.search(padrao, texto, re.IGNORECASE)
        if m:
            return m.group(0).strip()[:100]
    return ""

def extrair_envolvidos(texto: str) -> str:
    padroes = [
        r"(?:nomear|exonerar|designar|transferir|conceder)[^,\n]{0,15}(?:a\s+)?(?:senhor[ae]?\s+)?([A-ZÁÉÍÓÚÂÊÎÔÛÃÕÀÈÌÒÙ][A-ZÁÉÍÓÚÂÊÎÔÛÃÕÀÈÌÒÙa-záéíóúâêîôûãõàèìòù\s]{8,60})",
    ]
    for padrao in padroes:
        m = re.search(padrao, texto, re.IGNORECASE)
        if m:
            return m.group(1).strip()[:200]
    return ""

def gerar_titulo(texto: str, tipo: str, secao: str) -> str:
    num = extrair_numero_ato(texto)
    env = extrair_envolvidos(texto)
    if num and env:
        return f"{tipo} — {num} — {env}"[:200]
    if num:
        return f"{tipo} — {num}"[:200]
    if env:
        return f"{tipo} — {env}"[:200]
    primeiras = " ".join(texto.split()[:10])
    return f"{secao}: {primeiras}"[:200]

def gerar_resumo(texto: str) -> str:
    linhas = [l.strip() for l in texto.splitlines() if l.strip()][:4]
    return " ".join(linhas)[:500]

# ── NOTION ────────────────────────────────────────────────────────────────────
def criar_registro_notion(titulo, secao, tipo, resumo, envolvido, numero_ato, link_dom, data_dom):
    props = {
        "TÍTULO": {"title": [{"text": {"content": titulo}}]},
        "SEÇÃO":  {"select": {"name": secao}},
        "TIPO":   {"select": {"name": tipo}},
        "RESUMO": {"rich_text": [{"text": {"content": resumo}}]},
        "SERVIDOR / ENVOLVIDO": {"rich_text": [{"text": {"content": envolvido}}]},
        "Nº DO ATO": {"rich_text": [{"text": {"content": numero_ato}}]},
        "Status":    {"select": {"name": "NOVO"}},
        "NOTIFICADO": {"checkbox": False},
        "DATA DO DOM": {"date": {"start": data_dom}},
        "DATA DE CAPTURA": {"date": {"start": datetime.date.today().isoformat()}},
    }
    if link_dom:
        props["LINK DO DOM"] = {"url": link_dom}

    payload = {
        "parent": {"type": "database_id", "database_id": MONITOR_DB_ID},
        "properties": props,
    }

    r = requests.post(
        "https://api.notion.com/v1/pages",
        headers=HEADERS_NOTION,
        json=payload,
        timeout=15,
    )
    if r.status_code in (200, 201):
        return r.json().get("id", "")
    log.error(f"Erro Notion {r.status_code}: {r.text[:300]}")
    return None

# ── NTFY ──────────────────────────────────────────────────────────────────────
def notificar_ntfy(titulo: str, mensagem: str, prioridade: str = "default"):
    if not NTFY_URL:
        return
    try:
        requests.post(
            NTFY_URL,
            data=mensagem.encode("utf-8"),
            headers={
                "Title": titulo.encode("utf-8"),
                "Priority": prioridade,
                "Tags": "newspaper",
            },
            timeout=10,
        )
        log.info("ntfy enviado ✓")
    except Exception as e:
        log.warning(f"Erro ntfy: {e}")

# ── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    hoje = datetime.date.today().strftime("%d/%m/%Y")
    log.info("=" * 60)
    log.info(f"Monitor DOM — {hoje}")
    log.info("=" * 60)

    cache = carregar_cache()

    # 1. Buscar edição do dia
    pdf_url, edicao, data_dom = buscar_pdf_hoje()
    if not pdf_url:
        log.warning("DOM não disponível hoje.")
        notificar_ntfy(
            f"⚠️ DOM {hoje} — Não encontrado",
            "O Diário Oficial de hoje não foi encontrado ou ainda não publicado.",
            prioridade="low",
        )
        return

    # 2. Baixar e extrair
    conteudo = baixar_pdf(pdf_url)
    if not conteudo:
        return

    texto = extrair_texto(conteudo)
    if not texto:
        return

    # 3. Segmentar e filtrar
    blocos = segmentar_blocos(texto)
    relevantes = [b for b in blocos if deve_capturar(b)]
    log.info(f"Relevantes: {len(relevantes)} de {len(blocos)}")

    # 4. Registrar no Notion
    novos = 0
    resumo_ntfy = []

    for bloco in relevantes:
        txt = bloco["texto"]
        h   = hash_bloco(txt)

        if h in cache:
            continue

        secao     = classificar_secao(bloco)
        tipo      = classificar_tipo(txt)
        titulo    = gerar_titulo(txt, tipo, secao)
        resumo    = gerar_resumo(txt)
        envolvido = extrair_envolvidos(txt)
        num_ato   = extrair_numero_ato(txt)

        page_id = criar_registro_notion(
            titulo=titulo, secao=secao, tipo=tipo,
            resumo=resumo, envolvido=envolvido,
            numero_ato=num_ato, link_dom=pdf_url, data_dom=data_dom,
        )

        if page_id:
            cache.add(h)
            novos += 1
            resumo_ntfy.append(f"• [{tipo}] {titulo}")
            log.info(f"✅ {titulo}")
        else:
            log.warning(f"❌ Falha: {titulo}")

    salvar_cache(cache)

    # 5. Notificação final
    if novos > 0:
        corpo = f"Edição: {edicao}\n{novos} publicação(ões) registrada(s):\n\n" + "\n".join(resumo_ntfy[:15])
        notificar_ntfy(f"📰 DOM {hoje} — {novos} nova(s)", corpo)
    else:
        notificar_ntfy(
            f"📰 DOM {hoje} — Sem novidades",
            f"Diário lido. Nenhuma publicação nova relevante.\nEdição: {edicao}",
            prioridade="low",
        )

    log.info("=" * 60)
    log.info(f"Concluído. {novos} novo(s) registro(s).")
    log.info("=" * 60)


if __name__ == "__main__":
    main()
