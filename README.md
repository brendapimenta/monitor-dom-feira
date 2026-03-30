# Monitor do Diário Oficial — Câmara de Feira de Santana

Automação que roda todo dia útil às 9h e verifica se alguma movimentação
de pessoal pendente foi publicada no Diário Oficial Municipal.

Quando encontra, atualiza automaticamente o registro no Notion:
- Status → PUBLICADO NO DOM
- Nº do Ato / DOM → número da portaria e edição
- Observações → data e link do PDF

---

## Configuração (uma vez só)

### 1. Criar conta no GitHub (gratuita)
Acesse https://github.com e crie uma conta se ainda não tiver.

### 2. Criar o repositório
- Clique em **New repository**
- Nome: `monitor-dom-feira`
- Deixe como **Private** (privado)
- Clique em **Create repository**

### 3. Fazer upload dos arquivos
No repositório criado, clique em **uploading an existing file** e suba:
- `monitor_dom.py`
- `requirements.txt`

Depois crie a pasta `.github/workflows/` e suba:
- `monitor_dom.yml` (dentro da pasta `.github/workflows/`)

> **Dica:** No GitHub, você pode criar pastas escrevendo o caminho no nome
> do arquivo. Ex: `.github/workflows/monitor_dom.yml`

### 4. Obter sua Notion API Key
- Acesse https://www.notion.so/my-integrations
- Clique em **New integration**
- Nome: `Monitor DOM`
- Permissões: Ler e atualizar conteúdo
- Clique em **Save**
- Copie o **Internal Integration Token** (começa com `secret_...`)
- **Importante:** No Notion, abra o BD "Movimentações de Pessoal",
  clique em `...` → **Add connections** → selecione "Monitor DOM"

### 5. Obter o ID do banco de Movimentações
- Abra o BD "Movimentações de Pessoal" no Notion
- A URL será algo como: `https://www.notion.so/SEU-WORKSPACE/58f9adee...`
- O ID é a parte após a última `/` e antes de `?` (sem hífens)
- Exemplo: `58f9adeee27946c3b88801ba1de50964`

### 6. Configurar os Secrets no GitHub
No repositório, vá em **Settings → Secrets and variables → Actions**
e adicione dois secrets:

| Nome | Valor |
|------|-------|
| `NOTION_TOKEN` | Seu token `secret_...` |
| `MOVIMENTACOES_DB_ID` | ID do BD (ex: `58f9adee...`) |

### 7. Testar
- Vá em **Actions** no repositório
- Clique em **Monitor Diário Oficial**
- Clique em **Run workflow** → **Run workflow**
- Aguarde ~2 minutos e veja o resultado nos logs

---

## Como funciona

1. Todo dia útil às 9h, o GitHub inicia a automação na nuvem
2. O script abre o site do DOM com um navegador virtual
3. Coleta todos os PDFs do dia atual
4. Baixa cada PDF e extrai o texto
5. Para cada movimentação com status SOLICITADO ou EM PROCESSAMENTO,
   verifica se o nome do servidor aparece no texto
6. Se encontrar: atualiza o Notion com status, nº do ato e link do PDF

## Rodando manualmente
A qualquer momento você pode ir em **Actions → Run workflow** para
rodar na hora, sem esperar o horário agendado.
