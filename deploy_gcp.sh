#!/bin/bash

# --- GCP Deployment Script for K7 Laundry (Port 80 Version) ---
# Usage: 
# 1. SSH into your GCP VM.
# 2. Clone your repo: git clone <YOUR_REPO_URL> ~/k7_laundry
# 3. Run this script: bash deploy_gcp.sh

set -e

echo "Starting deployment setup..."

# 1. Update system and install Python tools
sudo apt update && sudo apt install -y python3-pip python3-venv

# 2. Navigate to project directory
cd ~/k7_laundry

# 3. Setup Virtual Environment and install dependencies
echo "Setting up virtual environment..."
python3 -m venv venv
./venv/bin/pip install -r requirements.txt

# 4. Create the background service (systemd)
echo "Configuring systemd service on Port 80..."
MY_USER=$(whoami)
sudo bash -c "cat << EOF > /etc/systemd/system/laundry.service
[Unit]
Description=K7 Laundry App
After=network.target

[Service]
User=root
WorkingDirectory=/home/$MY_USER/k7_laundry
ExecStart=/home/$MY_USER/k7_laundry/venv/bin/python3 -m uvicorn main:app --host 0.0.0.0 --port 80
Restart=always

[Install]
WantedBy=multi-user.target
EOF"

# 5. Start and enable the service
echo "Starting the app..."
sudo systemctl daemon-reload
sudo systemctl enable laundry
sudo systemctl start laundry

echo "------------------------------------------------"
echo "Deployment Complete!"
echo "Your app should be live at: http://$(curl -s ifconfig.me)"
echo "------------------------------------------------"
sudo systemctl status laundry --no-pager
