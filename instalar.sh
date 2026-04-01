#!/bin/bash

echo ""
echo "=================================================="
echo "  Instalando Monitor DOM — Feira de Santana"
echo "=================================================="
echo ""

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "📁 Pasta: $DIR"

# 1. Instalar dependências Python (sem playwright, já está instalado)
echo ""
echo "📦 Verificando dependências Python..."
pip3 install requests pypdf --quiet --user 2>/dev/null || true
echo "✅ Dependências OK"

# 2. Instalar playwright apenas se não estiver instalado
PLAYWRIGHT_BIN="$HOME/Library/Python/3.9/bin/playwright"
if [ ! -f "$PLAYWRIGHT_BIN" ]; then
    pip3 install playwright --quiet --user 2>/dev/null || true
fi

# 3. Instalar APENAS o chromium (não o headless shell)
echo ""
echo "🌐 Verificando Chromium..."
CHROMIUM_DIR="$HOME/Library/Caches/ms-playwright/chromium-1208"
if [ -d "$CHROMIUM_DIR" ]; then
    echo "✅ Chromium já instalado"
else
    PLAYWRIGHT_BROWSERS_PATH="$HOME/Library/Caches/ms-playwright" \
    PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 \
    "$PLAYWRIGHT_BIN" install chromium 2>/dev/null || true
    echo "✅ Chromium instalado"
fi

# 4. Criar agendamentos
PLIST_8H="$HOME/Library/LaunchAgents/br.gov.feiradesantana.dom.8h.plist"
PLIST_12H="$HOME/Library/LaunchAgents/br.gov.feiradesantana.dom.12h.plist"
PYTHON_PATH=$(python3 -c "import sys; print(sys.executable)")
mkdir -p "$HOME/Library/LaunchAgents"

echo ""
echo "⏰ Criando agendamentos..."

cat > "$PLIST_8H" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>br.gov.feiradesantana.dom.8h</string>
    <key>ProgramArguments</key>
    <array>
        <string>$PYTHON_PATH</string>
        <string>$DIR/monitor_dom.py</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict><key>Hour</key><integer>8</integer><key>Minute</key><integer>0</integer></dict>
    <key>WorkingDirectory</key><string>$DIR</string>
    <key>StandardOutPath</key><string>$DIR/monitor_dom.log</string>
    <key>StandardErrorPath</key><string>$DIR/monitor_dom_erro.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PLAYWRIGHT_BROWSERS_PATH</key>
        <string>$HOME/Library/Caches/ms-playwright</string>
    </dict>
</dict>
</plist>
PLIST

cat > "$PLIST_12H" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>br.gov.feiradesantana.dom.12h</string>
    <key>ProgramArguments</key>
    <array>
        <string>$PYTHON_PATH</string>
        <string>$DIR/monitor_dom.py</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict><key>Hour</key><integer>12</integer><key>Minute</key><integer>0</integer></dict>
    <key>WorkingDirectory</key><string>$DIR</string>
    <key>StandardOutPath</key><string>$DIR/monitor_dom.log</string>
    <key>StandardErrorPath</key><string>$DIR/monitor_dom_erro.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PLAYWRIGHT_BROWSERS_PATH</key>
        <string>$HOME/Library/Caches/ms-playwright</string>
    </dict>
</dict>
</plist>
PLIST

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
echo "  🧪 Para testar agora:"
echo "     python3 $DIR/monitor_dom.py"
echo ""
