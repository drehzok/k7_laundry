#!/bin/bash

# --- GCP Deployment Script for K7 Laundry (HTTPS/SSL Version) ---
# Usage: 
# 1. SSH into your GCP VM.
# 2. Clone your repo: git clone <YOUR_REPO_URL> ~/k7_laundry
# 3. Run this script: bash deploy_gcp.sh YOUR_EMAIL YOUR_DOMAIN

set -e

EMAIL=${1:-"your-email@gmail.com"}
DOMAIN=${2:-"k7-laundry.duckdns.org"}

echo "Starting deployment setup with HTTPS..."

# 1. Update system and install Python, Nginx, and Certbot
sudo apt update && sudo apt install -y python3-pip python3-venv nginx certbot python3-certbot-nginx

# 2. Navigate to project directory
cd ~/k7_laundry

# 3. Setup Virtual Environment and install dependencies
echo "Setting up virtual environment..."
python3 -m venv venv
./venv/bin/pip install -r requirements.txt

# 4. Create the background service (systemd) on Port 8000
echo "Configuring systemd service on Port 8000..."
MY_USER=$(whoami)
sudo bash -c "cat << 'EOF' > /etc/systemd/system/laundry.service
[Unit]
Description=K7 Laundry App
After=network.target

[Service]
User=$MY_USER
WorkingDirectory=/home/$MY_USER/k7_laundry
ExecStart=/home/$MY_USER/k7_laundry/venv/bin/python3 -m uvicorn main:app --host 127.0.0.1 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
EOF"

# Fix the MY_USER variable in the service file since we used 'EOF'
sudo sed -i "s/\$MY_USER/$MY_USER/g" /etc/systemd/system/laundry.service

# 5. Configure Nginx as a Reverse Proxy
echo "Configuring Nginx..."
sudo bash -c "cat << 'EOF' > /etc/nginx/sites-available/default
server {
    listen 80;
    server_name \$DOMAIN;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF"

# Replace the placeholder $DOMAIN in the Nginx config
sudo sed -i "s/\$DOMAIN/$DOMAIN/g" /etc/nginx/sites-available/default

# 6. Restart everything
echo "Starting the app and Nginx..."
sudo systemctl daemon-reload
sudo systemctl enable laundry
sudo systemctl restart laundry
sudo systemctl restart nginx

# 7. Setup SSL (HTTPS) with Certbot
echo "Setting up SSL certificate..."
sudo certbot --nginx -d $DOMAIN --non-interactive --agree-tos --email $EMAIL || echo "Certbot failed. Make sure your domain is pointing to this IP and try again later."

echo "------------------------------------------------"
echo "Deployment Complete!"
echo "Your app should be live at: https://$DOMAIN"
echo "------------------------------------------------"
sudo systemctl status laundry --no-pager
sudo systemctl status nginx --no-pager
