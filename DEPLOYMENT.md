# Production deployment

Target server: `37.32.4.207`

This project is prepared to run as a Django application behind Nginx and Gunicorn.

## Server requirements

- Ubuntu/Debian server
- SSH access
- Python 3
- Node.js and npm
- Nginx
- PostgreSQL database, local or remote

## Files

- `deploy/.env.production.example`: production environment template
- `deploy/server_setup_ubuntu.sh`: one-command server setup script
- `deploy/nginx-virtual-exam.conf`: static Nginx config for `/srv/virtual-exam`
- `deploy/virtual-exam.service`: static Systemd service for `/srv/virtual-exam`

## Recommended path

Copy the project to:

```bash
/srv/virtual-exam
```

Then run:

```bash
cd /srv/virtual-exam
sudo bash deploy/server_setup_ubuntu.sh
```

Edit `.env` before first production use and set the real PostgreSQL password:

```bash
sudo nano /srv/virtual-exam/.env
sudo systemctl restart virtual-exam
```

## Health checks

```bash
sudo systemctl status virtual-exam
sudo nginx -t
curl -I http://37.32.4.207/
```

## Notes

- `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS` already include `37.32.4.207`.
- Static files are served from `staticfiles/`.
- Uploaded files are served from `media/`.
- Gunicorn listens internally on `127.0.0.1:8013`.
