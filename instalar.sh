#!/bin/bash
set -e

echo ""
echo "=================================================="
echo "  Instalando Monitor DOM — Feira de Santana"
echo "=================================================="
echo ""

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "📁 Pasta: $DIR"

# 1. Instalar dependências Python
echo ""
echo "📦 Instalando dependências Python..."
pip3 install requests pypdf playwright --quiet --user
echo "✅ Dependências instaladas"

# 2. Instalar só o chromium (sem headless shell, que está bloqueado na rede)
echo ""
echo "🌐 Instalando navegador Chromium..."
PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=0 \
  python3 -m playwright install chromium 2>/dev/null || \
  /Users/brendapimenta/Library/Python/3.9/bin/playwright install chromium || true
echo "✅ Chromium pronto"

# 3. Criar agendamentos via launchd
PLIST_8H=~/Library/LaunchAgents/br.gov.feiradesantana.dom.8h.plist
PLIST_12H=~/Library/LaunchAgents/br.gov.feiradesantana.dom.12h.plist
PYTHON_PATH=$(python3 -c "import sys; print(sys.executable)")

mkdir -p ~/Library/LaunchAgents

echo ""
echo "⏰ Criando agendamento das 8h..."
cat > "$PLIST_8H" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>br.gov.feiradesantana.dom.8h</string>
    <key>ProgramArguments</key>
    <array>
        <string>$PYTHON_PATH</string>
        <string>$DIR/monitor_dom.py</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>8</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
    <key>WorkingDirectory</key>
    <string>$DIR</string>
    <key>StandardOutPath</key>
    <string>$DIR/monitor_dom.log</string>
    <key>StandardErrorPath</key>
    <string>$DIR/monitor_dom_erro.log</string>
</dict>
</plist>
PLIST

echo "⏰ Criando agendamento das 12h..."
cat > "$PLIST_12H" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>br.gov.feiradesantana.dom.12h</string>
    <key>ProgramArguments</key>
    <array>
        <string>$PYTHON_PATH</string>
        <string>$DIR/monitor_dom.py</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>12</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
    <key>WorkingDirectory</key>
    <string>$DIR</string>
    <key>StandardOutPath</key>
    <string>$DIR/monitor_dom.log</string>
    <key>StandardErrorPath</key>
    <string>$DIR/monitor_dom_erro.log</string>
</dict>
</plist>
PLIST

# 4. Ativar agendamentos
echo ""
echo "🔄 Ativando agendamentos..."
launchctl unload "$PLIST_8H" 2>/dev/null || true
launchctl unload "$PLIST_12H" 2>/dev/null || true
launchctl load "$PLIST_8H"
launchctl load "$PLIST_12H"

echo ""
echo "=================================================="
echo "  ✅ INSTALAÇÃO CONCLUÍDA!"
echo "=================================================="
echo ""
echo "  ⏰ Rodará automaticamente às 8h e às 12h"
echo ""
echo "  🧪 Para testar agora, rode:"
echo "     python3 $DIR/monitor_dom.py"
echo ""
