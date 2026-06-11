# Deploy على VPS (Ubuntu 22.04)

## 1. تثبيت المتطلبات

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3-pip python3-venv postgresql nginx
```

## 2. إعداد PostgreSQL

```bash
sudo -u postgres psql
```

```sql
CREATE DATABASE balport;
CREATE USER balport_user WITH PASSWORD 'ضع_كلمة_سر_قوية';
GRANT ALL PRIVILEGES ON DATABASE balport TO balport_user;
\q
```

## 3. رفع الكود على السيرفر

```bash
# من جهازك المحلي
scp -r balport-app/ user@YOUR_SERVER_IP:/home/user/
scp Balport_Invoices_Cleaned.csv user@YOUR_SERVER_IP:/home/user/
```

## 4. إعداد البيئة على السيرفر

```bash
cd /home/user/balport-app
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

أنشئ ملف `.env`:

```bash
cp .env.example .env
nano .env
# عدّل DATABASE_URL وSECRET_KEY
```

```
DATABASE_URL=postgresql://balport_user:كلمة_السر@localhost:5432/balport
SECRET_KEY=اكتب_نص_عشوائي_طويل_هنا
APP_USERNAME=admin
APP_PASSWORD=كلمة_سر_قوية_لتسجيل_الدخول
```

> **مهم:** إذا تركت `APP_PASSWORD` فارغة سيعمل التطبيق **بدون تسجيل دخول** وأي شخص يصل للرابط يستطيع تعديل البيانات.

## 5. استيراد البيانات

```bash
source venv/bin/activate
python import_data.py
```

## 6. إعداد Gunicorn كـ Service

```bash
sudo nano /etc/systemd/system/balport.service
```

```ini
[Unit]
Description=Balport Flask App
After=network.target

[Service]
User=user
WorkingDirectory=/home/user/balport-app
Environment="PATH=/home/user/balport-app/venv/bin"
EnvironmentFile=/home/user/balport-app/.env
ExecStart=/home/user/balport-app/venv/bin/gunicorn -w 3 -b 127.0.0.1:5000 app:app

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable balport
sudo systemctl start balport
```

## 7. إعداد Nginx

```bash
sudo nano /etc/nginx/sites-available/balport
```

```nginx
server {
    listen 80;
    server_name YOUR_DOMAIN_OR_IP;

    location / {
        proxy_pass         http://127.0.0.1:5000;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
    }

    location /static/ {
        alias /home/user/balport-app/static/;
        expires 7d;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/balport /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

## 8. (اختياري) HTTPS مجاني مع Certbot

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d yourdomain.com
```

---

## التحقق من أن كل شيء يعمل

```bash
sudo systemctl status balport   # يجب أن يكون active (running)
sudo journalctl -u balport -f   # مراقبة الأخطاء
```
