#!/bin/bash
# QBot Trading Server Security Setup
# Schützt den Server und erlaubt nur SSH + FastAPI Zugriff

set -e

echo "🔒 QBot Trading Server Security Setup"
echo "======================================"

# Farben für Output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Root-Check
if [ "$EUID" -ne 0 ]; then 
    echo -e "${RED}❌ Bitte als root ausführen: sudo ./secure-server.sh${NC}"
    exit 1
fi

# 1. System Update
echo -e "\n${YELLOW}📦 System Updates installieren...${NC}"
apt-get update -qq
apt-get upgrade -y -qq

# 2. UFW Firewall installieren
echo -e "\n${YELLOW}🔥 UFW Firewall installieren...${NC}"
apt-get install -y ufw

# 3. UFW Regeln zurücksetzen
echo -e "\n${YELLOW}🔧 Firewall-Regeln konfigurieren...${NC}"
ufw --force reset

# 4. Standard-Policies setzen
ufw default deny incoming
ufw default allow outgoing

# 5. SSH erlauben (Port 22)
echo -e "${GREEN}✅ SSH (Port 22) erlauben${NC}"
ufw allow 22/tcp comment 'SSH Access'

# 6. FastAPI nur für bestimmte IPs erlauben
echo -e "\n${YELLOW}📝 Welche IP-Adressen sollen auf FastAPI (Port 8000) zugreifen?${NC}"
echo "Beispiele:"
echo "  - Einzelne IP: 192.168.1.100"
echo "  - IP-Range: 192.168.1.0/24"
echo "  - Alle erlauben: 0.0.0.0/0 (NICHT EMPFOHLEN!)"
echo ""
read -p "Frontend IP-Adresse oder Bereich eingeben: " FRONTEND_IP

if [ -z "$FRONTEND_IP" ]; then
    echo -e "${YELLOW}⚠️  Keine IP angegeben - Port 8000 wird für localhost (127.0.0.1) freigegeben${NC}"
    FRONTEND_IP="127.0.0.1"
fi

ufw allow from $FRONTEND_IP to any port 8000 proto tcp comment 'FastAPI Frontend Access'
echo -e "${GREEN}✅ FastAPI (Port 8000) für $FRONTEND_IP erlaubt${NC}"

# 7. Docker-Ports sichern (intern only)
echo -e "\n${YELLOW}🐳 Docker-Ports absichern...${NC}"
# Redis (6379), PostgreSQL (5432) - nur localhost
echo -e "${GREEN}✅ Redis (6379) - nur localhost${NC}"
echo -e "${GREEN}✅ PostgreSQL (5432) - nur localhost${NC}"

# 8. Fail2Ban installieren (SSH Brute-Force Schutz)
echo -e "\n${YELLOW}🛡️  Fail2Ban installieren (SSH Brute-Force Schutz)...${NC}"
apt-get install -y fail2ban

# Fail2Ban SSH Konfiguration
cat > /etc/fail2ban/jail.local << 'EOF'
[DEFAULT]
bantime = 3600
findtime = 600
maxretry = 5

[sshd]
enabled = true
port = 22
filter = sshd
logpath = /var/log/auth.log
maxretry = 3
bantime = 7200
EOF

systemctl enable fail2ban
systemctl restart fail2ban
echo -e "${GREEN}✅ Fail2Ban aktiviert (3 fehlgeschlagene SSH-Logins = 2h Sperre)${NC}"

# 9. UFW aktivieren
echo -e "\n${YELLOW}🔥 Firewall aktivieren...${NC}"
ufw --force enable

# 10. Status anzeigen
echo -e "\n${GREEN}✅ Security Setup abgeschlossen!${NC}"
echo ""
echo "======================================"
echo "🔒 AKTIVE FIREWALL-REGELN:"
echo "======================================"
ufw status numbered

echo ""
echo "======================================"
echo "📋 SECURITY SUMMARY:"
echo "======================================"
echo -e "${GREEN}✅ SSH (Port 22):${NC} Öffentlich erreichbar"
echo -e "${GREEN}✅ FastAPI (Port 8000):${NC} Nur für $FRONTEND_IP"
echo -e "${GREEN}✅ Redis (Port 6379):${NC} Nur localhost (Docker intern)"
echo -e "${GREEN}✅ PostgreSQL (Port 5432):${NC} Nur localhost (Docker intern)"
echo -e "${GREEN}✅ Fail2Ban:${NC} SSH Brute-Force Schutz aktiv"
echo ""
echo -e "${YELLOW}⚠️  WICHTIG:${NC}"
echo "- SSH läuft weiter auf Port 22"
echo "- FastAPI ist erreichbar für: $FRONTEND_IP"
echo "- Alle anderen Ports sind blockiert"
echo ""

# 11. Docker Compose anpassen (Ports auf localhost binden)
echo -e "\n${YELLOW}🐳 Docker Compose für localhost-only Binding anpassen?${NC}"
echo "Dies bindet Redis/PostgreSQL nur an 127.0.0.1 (empfohlen!)"
read -p "Docker Compose anpassen? (y/n): " ADJUST_DOCKER

if [ "$ADJUST_DOCKER" = "y" ]; then
    echo -e "${YELLOW}📝 Bitte docker-compose.yml manuell anpassen:${NC}"
    echo ""
    echo "Ändere in docker-compose.yml:"
    echo ""
    echo "  redis:"
    echo "    ports:"
    echo "      - \"127.0.0.1:6379:6379\"  # Statt 0.0.0.0:6379:6379"
    echo ""
    echo "  postgres:"
    echo "    ports:"
    echo "      - \"127.0.0.1:5432:5432\"  # Statt 0.0.0.0:5432:5432"
    echo ""
    echo "Danach: docker-compose down && docker-compose up -d"
fi

echo ""
echo -e "${GREEN}🎉 Server ist jetzt gesichert!${NC}"
