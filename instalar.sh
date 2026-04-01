#!/bin/bash
set -e

echo ""
echo "=================================================="
echo "  Instalando Monitor DOM — Feira de Santana"
echo "=================================================="
echo ""

# Diretório do script
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "📁 Pasta: $DIR"

# 1. Instalar dependências Python
echo ""
echo "📦 Instalando dependências Python..."
pip3 install requests pypdf playwright --quiet
python3 -m playwright install chromium
echo "✅ Dependências instaladas"

# 2. Criar os dois agendamentos via launchd (agendador nativo do Mac)
PLIST_8H=~/Library/LaunchAgents/br.gov.feiradesantana.dom.8h.plist
PLIST_12H=~/Library/LaunchAgents/br.gov.feiradesantana.dom.12h.plist

PYTHON_PATH=$(which python3)

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
    <key>RunAtLoad</key>
    <false/>
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
    <key>RunAtLoad</key>
    <false/>
</dict>
</plist>
PLIST

# 3. Ativar os agendamentos
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
echo "  ⏰ Rodará automaticamente:"
echo "     • Todos os dias às 8h00"
echo "     • Todos os dias às 12h00"
echo ""
echo "  📋 Para testar agora:"
echo "     python3 $DIR/monitor_dom.py"
echo ""
echo "  📄 Logs em:"
echo "     $DIR/monitor_dom.log"
echo ""
