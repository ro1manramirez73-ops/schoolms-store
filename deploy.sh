#!/bin/bash

# Deployment script for SchoolMS
# Run this on your server

echo "Starting deployment..."

# Update system
sudo apt update && sudo apt upgrade -y

# Install required packages
sudo apt install python3 python3-pip python3-venv nginx postgresql postgresql-contrib -y

# Create app directory
sudo mkdir -p /var/www/schoolms
sudo chown -R $USER:$USER /var/www/schoolms

# Copy files (replace with your actual copy command)
# scp -r . user@server:/var/www/schoolms

# Setup virtual environment
cd /var/www/schoolms
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Setup database (PostgreSQL)
sudo -u postgres createdb schoolms
sudo -u postgres createuser schoolms_user
sudo -u postgres psql -c "ALTER USER schoolms_user PASSWORD 'your_password';"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE schoolms TO schoolms_user;"

# Update database connection in app.py to use PostgreSQL instead of SQLite

# Setup systemd service
sudo cp schoolms.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable schoolms
sudo systemctl start schoolms

# Setup nginx
sudo cp nginx.conf /etc/nginx/sites-available/schoolms
sudo ln -s /etc/nginx/sites-available/schoolms /etc/nginx/sites-enabled
sudo nginx -t
sudo systemctl restart nginx

# Setup SSL with Let's Encrypt (optional)
# sudo apt install certbot python3-certbot-nginx -y
# sudo certbot --nginx -d yourdomain.com

echo "Deployment complete! Visit your domain."