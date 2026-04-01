"""
monitor_dom.py — Monitor do Diário Oficial Municipal de Feira de Santana
"""

import os, re, json, datetime, hashlib, logging, requests, io
from pathlib import Path
from playwright.sync_api import sync_playwright

# ── LOGGING ───────────────────────────────────────────────────────────────────
LOG_FILE = Path(__file__).parent / "monitor_dom.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
    ]
)
log = logging.getLogger(__name__)

# ── CONFIG — lê do arquivo config.json ────────────────────────────────────────
CONFIG_FILE = Path(__file__).parent / "config.json"
if not CONFIG_FILE.exists():
    raise FileNotFoundError(f"Arquivo de configuração não encontrado: {CONFIG_FILE}")

cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
NOTION_TOKEN  = cfg["NOTION_TOKEN"]
MONITOR_DB_ID = cfg["MONITOR_DOM_DB_ID"]
NTFY_URL      = cfg.get("NTFY_URL", "")
DOM_BASE      = "https://diariooficial.feiradesantana.ba.gov.br"
CACHE_FILE    = Path(__file__).parent / "dom_cache.json"

HEADERS_NOTION = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}

# ── PALAVRAS-CHAVE ─────────────────────────────────────────────────────────────
PALAVRAS_CAMARA = [
    "câmara municipal", "camara municipal", "câmara de vereadores",
    "vereador", "vereadora", "vereadores", "mesa diretora",
    "presidência da câmara", "presidente da câmara", "gabinete da presidência",
]

# ── CACHE ──────────────────────────────────────────────────────────────────────
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

# ── SCRAPING ───────────────────────────────────────────────────────────────────
def buscar_edicao_hoje() -> dict:
    hoje = datetime.date.today()
    log.info(f"Buscando edição do DOM — {hoje.strftime('%d/%m/%Y')}")
    resultado = {"edicao": "", "data": hoje.isoformat(), "url_legislativo": None, "url_executivo": None}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        try:
            page.goto(DOM_BASE, timeout=30000, wait_until="domcontentloaded")
            page.wait_for_timeout(5000)

            links = page.eval_on_selector_all(
                "a[href]",
                "els => els.map(e => ({href: e.href, text: (e.innerText||e.textContent||'[]').trim()}))"
            )
            log.info(f"Links encontrados: {len(links)}")

            for link in links:
                href = link.get("href", "").strip()
                texto = link.get("text", "").strip()
                href_lower = href.lower()

                if "/atos/legislativo/" in href_lower and href_lower.endswith(".pdf"):
                    resultado["url_legislativo"] = href
                    log.info(f"  Legislativo: {href}")
                elif "/atos/executivo/" in href_lower and href_lower.endswith(".pdf"):
                    if not resultado["url_executivo"]:
                        resultado["url_executivo"] = href
                        log.info(f"  Executivo: {href}")

                if not resultado["edicao"] and texto and ("edição" in texto.lower() or "edicao" in href_lower):
                    resultado["edicao"] = texto

            if not resultado["url_legislativo"] and not resultado["url_executivo"]:
                log.warning("PDFs não encontrados via rota direta, tentando fallback...")
                for link in links:
                    href = link.get("href", "")
                    if href.lower().endswith(".pdf") and "feiradesantana" in href.lower():
                        texto = link.get("text", "").lower()
                        if "legislativo" in texto or "câmara" in texto:
                            resultado["url_legislativo"] = href
                        elif not resultado["url_executivo"]:
                            resultado["url_executivo"] = href

            if not resultado["url_legislativo"] and not resultado["url_executivo"]:
                log.warning("Nenhum PDF. Links disponíveis:")
                for l in links[:20]:
                    log.warning(f"  {l.get('text','')[:40]} -> {l.get('href','')}")

        except Exception as e:
            log.error(f"Erro Playwright: {e}")
        finally:
            browser.close()

    if not resultado["edicao"]:
        resultado["edicao"] = f"DOM {hoje.strftime('%d/%m/%Y')}"
    return resultado

# ── DOWNLOAD E EXTRAÇÃO ────────────────────────────────────────────────────────
def baixar_pdf(url: str) -> bytes:
    try:
        r = requests.get(url, timeout=60,
            headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"})
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
        partes = [pag.extract_text() or "" for pag in reader.pages]
        texto = "\n\n".join(partes)
        log.info(f"Texto extraído: {len(texto):,} chars, {len(reader.pages)} páginas")
        return texto
    except Exception as e:
        log.error(f"Erro extração: {e}")
        return ""

# ── SEGMENTAÇÃO E CLASSIFICAÇÃO ────────────────────────────────────────────────
def segmentar_blocos(texto: str, secao_base: str) -> list:
    blocos, bloco_linhas = [], []
    for linha in texto.splitlines():
        if not linha.strip() and bloco_linhas:
            txt = "\n".join(bloco_linhas).strip()
            if len(txt) > 60:
                blocos.append({"texto": txt, "secao_base": secao_base})
            bloco_linhas = []
        else:
            bloco_linhas.append(linha)
    if bloco_linhas:
        txt = "\n".join(bloco_linhas).strip()
        if len(txt) > 60:
            blocos.append({"texto": txt, "secao_base": secao_base})
    log.info(f"[{secao_base}] {len(blocos)} blocos")
    return blocos

def deve_capturar(bloco: dict) -> bool:
    if bloco["secao_base"] == "LEGISLATIVO":
        return True
    return any(p in bloco["texto"].lower() for p in PALAVRAS_CAMARA)

def classificar_secao(bloco: dict) -> str:
    t = bloco["texto"].lower()
    if bloco["secao_base"] == "LEGISLATIVO":
        if any(p in t for p in ["nomear", "exonerar", "nomeação", "exoneração", "aspa"]): return "PESSOAL"
        if any(p in t for p in ["licitação", "pregão", "contrato", "dispensa", "edital"]): return "LICITAÇÕES"
        if any(p in t for p in ["decreto", "portaria", "resolução"]): return "DECRETOS E PORTARIAS"
        return "LEGISLATIVO"
    return "EXECUTIVO"

def classificar_tipo(texto: str) -> str:
    t = texto.lower()
    if any(p in t for p in ["nomear", "nomeação", "nomeado"]):        return "NOMEAÇÃO"
    if any(p in t for p in ["exonerar", "exoneração", "exonerado"]):  return "EXONERAÇÃO"
    if any(p in t for p in ["aspa", "gratificação", "adicional de"]): return "ALTERAÇÃO DE ASPA"
    if any(p in t for p in ["transferir", "transferência"]):          return "TRANSFERÊNCIA"
    if any(p in t for p in ["licitação", "pregão", "chamamento"]):    return "LICITAÇÃO"
    if any(p in t for p in ["contrato", "aditivo", "dispensa"]):      return "CONTRATO"
    if "decreto" in t:                                                  return "DECRETO"
    if any(p in t for p in ["portaria", "resolução"]):                 return "PORTARIA"
    if any(p in t for p in PALAVRAS_CAMARA):                           return "MENÇÃO À CÂMARA"
    return "OUTRO"

def extrair_numero_ato(texto: str) -> str:
    for padrao in [
        r"(?:portaria|decreto|resolução|edital|pregão|contrato)\s*n[°º\.]*\s*[\d\./\-]+",
        r"n[°º\.]\s*[\d\.\/\-]{3,}",
    ]:
        m = re.search(padrao, texto, re.IGNORECASE)
        if m: return m.group(0).strip()[:100]
    return ""

def extrair_envolvidos(texto: str) -> str:
    m = re.search(
        r"(?:nomear|exonerar|designar|transferir)[^,\n]{0,20}(?:senhor[ae]?\s+)?([A-ZÁÉÍÓÚÂÊÎÔÛÃÕ][A-ZÁÉÍÓÚÂÊÎÔÛÃÕa-záéíóúâêîôûãõ\s]{8,60})",
        texto, re.IGNORECASE
    )
    return m.group(1).strip()[:200] if m else ""

def gerar_titulo(texto: str, tipo: str, secao: str) -> str:
    num = extrair_numero_ato(texto)
    env = extrair_envolvidos(texto)
    if num and env: return f"{tipo} — {num} — {env}"[:200]
    if num:         return f"{tipo} — {num}"[:200]
    if env:         return f"{tipo} — {env}"[:200]
    return f"{secao}: {' '.join(texto.split()[:10])}"[:200]

def gerar_resumo(texto: str) -> str:
    return " ".join([l.strip() for l in texto.splitlines() if l.strip()][:4])[:500]

# ── NOTION ─────────────────────────────────────────────────────────────────────
def criar_registro_notion(titulo, secao, tipo, resumo, envolvido, numero_ato, link_dom, data_dom, edicao):
    props = {
        "TÍTULO":   {"title": [{"text": {"content": titulo}}]},
        "SEÇÃO":    {"select": {"name": secao}},
        "TIPO":     {"select": {"name": tipo}},
        "RESUMO":   {"rich_text": [{"text": {"content": resumo}}]},
        "SERVIDOR / ENVOLVIDO": {"rich_text": [{"text": {"content": envolvido}}]},
        "Nº DO ATO":  {"rich_text": [{"text": {"content": numero_ato}}]},
        "EDIÇÃO":     {"rich_text": [{"text": {"content": edicao}}]},
        "Status":     {"select": {"name": "NOVO"}},
        "NOTIFICADO": {"checkbox": False},
        "DATA DO DOM":     {"date": {"start": data_dom}},
        "DATA DE CAPTURA": {"date": {"start": datetime.date.today().isoformat()}},
    }
    if link_dom:
        props["LINK DO DOM"] = {"url": link_dom}

    r = requests.post(
        "https://api.notion.com/v1/pages",
        headers=HEADERS_NOTION,
        json={"parent": {"type": "database_id", "database_id": MONITOR_DB_ID}, "properties": props},
        timeout=15,
    )
    if r.status_code in (200, 201):
        return r.json().get("id")
    log.error(f"Erro Notion {r.status_code}: {r.text[:300]}")
    return None

# ── NTFY ────────────────────────────────────────────────────────────────────────
def notificar_ntfy(titulo: str, mensagem: str, prioridade: str = "default"):
    if not NTFY_URL:
        return
    try:
        requests.post(NTFY_URL, data=mensagem.encode("utf-8"),
            headers={"Title": titulo.encode("utf-8"), "Priority": prioridade, "Tags": "newspaper"},
            timeout=10)
        log.info("ntfy enviado")
    except Exception as e:
        log.warning(f"Erro ntfy: {e}")

# ── PROCESSAR SEÇÃO ────────────────────────────────────────────────────────────
def processar_secao(url_pdf, secao_base, edicao, data_dom, cache) -> list:
    if not url_pdf:
        log.info(f"[{secao_base}] sem PDF hoje")
        return []
    conteudo = baixar_pdf(url_pdf)
    if not conteudo: return []
    texto = extrair_texto(conteudo)
    if not texto: return []

    blocos = segmentar_blocos(texto, secao_base)
    relevantes = [b for b in blocos if deve_capturar(b)]
    log.info(f"[{secao_base}] {len(relevantes)} relevantes de {len(blocos)}")

    criados = []
    for bloco in relevantes:
        txt = bloco["texto"]
        h = hash_bloco(txt)
        if h in cache: continue
        secao     = classificar_secao(bloco)
        tipo      = classificar_tipo(txt)
        titulo    = gerar_titulo(txt, tipo, secao)
        resumo    = gerar_resumo(txt)
        envolvido = extrair_envolvidos(txt)
        num_ato   = extrair_numero_ato(txt)
        page_id = criar_registro_notion(titulo, secao, tipo, resumo, envolvido, num_ato, url_pdf, data_dom, edicao)
        if page_id:
            cache.add(h)
            criados.append(f"• [{tipo}] {titulo}")
            log.info(f"OK: {titulo}")
        else:
            log.warning(f"Falha: {titulo}")
    return criados

# ── MAIN ────────────────────────────────────────────────────────────────────────
def main():
    hoje_fmt = datetime.date.today().strftime("%d/%m/%Y")
    log.info("=" * 60)
    log.info(f"Monitor DOM — {hoje_fmt}")
    log.info("=" * 60)

    cache = carregar_cache()
    edicao_info = buscar_edicao_hoje()
    url_leg = edicao_info["url_legislativo"]
    url_exe = edicao_info["url_executivo"]
    edicao  = edicao_info["edicao"]
    data    = edicao_info["data"]

    if not url_leg and not url_exe:
        log.warning("DOM não encontrado hoje.")
        notificar_ntfy(f"DOM {hoje_fmt} — Não encontrado",
            "O Diário Oficial não foi encontrado.", prioridade="low")
        return

    criados_leg = processar_secao(url_leg, "LEGISLATIVO", edicao, data, cache)
    criados_exe = processar_secao(url_exe, "EXECUTIVO",   edicao, data, cache)
    salvar_cache(cache)

    total = len(criados_leg) + len(criados_exe)
    if total > 0:
        linhas = []
        if criados_leg:
            linhas.append("LEGISLATIVO:")
            linhas.extend(criados_leg[:10])
        if criados_exe:
            linhas.append("EXECUTIVO (Câmara):")
            linhas.extend(criados_exe[:5])
        notificar_ntfy(f"DOM {hoje_fmt} — {total} nova(s)",
            f"Edição: {edicao}\n{total} publicação(ões):\n\n" + "\n".join(linhas))
    else:
        notificar_ntfy(f"DOM {hoje_fmt} — Sem novidades",
            f"Diário lido. Sem publicações novas.\nEdição: {edicao}", prioridade="low")

    log.info(f"Concluído. {total} novo(s).")
    log.info("=" * 60)

if __name__ == "__main__":
    main()
