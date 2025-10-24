# Waterfall All-in-One Docker Configuration

## 🚀 Vue d'ensemble

Cette configuration permet de déployer toute l'application Waterfall dans un seul conteneur Docker incluant :

- ✅ Tous les services backend (Auth, Identity, Guardian)
- ✅ Application web (Next.js)
- ✅ Base de données PostgreSQL intégrée
- ✅ Reverse proxy Nginx avec SSL
- ✅ Gestion automatique des secrets
- ✅ Configuration de production optimisée

## 📦 Utilisation

### Démarrage rapide

```bash
# Construction et démarrage
docker compose -f compose/docker-compose.allinone.yml up -d --build

# Vérification du statut
docker compose -f compose/docker-compose.allinone.yml ps

# Consultation des logs
docker compose -f compose/docker-compose.allinone.yml logs -f
```

### Accès à l'application

- **Application web** : https://localhost (HTTPS)
- **API de santé** : https://localhost/api/health
- **Redirection HTTP** : http://localhost → https://localhost

## ⚙️ Configuration

### Variables d'environnement

Créez un fichier `.env` dans le répertoire racine :

```bash
# Secrets (optionnels - générés automatiquement si non définis)
JWT_SECRET=your-super-secret-jwt-key-32-chars-min
INTERNAL_AUTH_TOKEN=your-internal-auth-token-32-chars
POSTGRES_PASSWORD=your-secure-postgres-password

# Configuration des services (optionnel)
FLASK_ENV=production
LOG_LEVEL=info
NODE_ENV=production
```

### Volumes persistants

Les données importantes sont automatiquement persistées :

- **`postgres_data`** : Base de données PostgreSQL
- **`waterfall_secrets`** : Secrets générés automatiquement
- **`waterfall_logs`** : Logs de l'application
- **`nginx_logs`** : Logs Nginx
- **`postgres_logs`** : Logs PostgreSQL

## 🔒 Sécurité

### Génération automatique des secrets

Si aucun secret n'est fourni, le conteneur génère automatiquement :
- JWT Secret (32 caractères)
- Internal Auth Token (32 caractères)
- Mot de passe PostgreSQL (32 caractères)

Les secrets sont stockés dans `/opt/waterfall/secrets/` et persistés via le volume `waterfall_secrets`.

### Certificats SSL

- **Génération automatique** : Certificats auto-signés créés au premier démarrage
- **Certificats personnalisés** : Décommentez les volumes dans `docker-compose.allinone.yml`

```yaml
volumes:
  - ./ssl/server.crt:/etc/ssl/waterfall/server.crt:ro
  - ./ssl/server.key:/etc/ssl/waterfall/server.key:ro
```

## 🏗️ Architecture

### Services internes

| Service | Port interne | Description |
|---------|-------------|-------------|
| PostgreSQL | 5432 | Base de données |
| Auth Service | 5001 | Service d'authentification |
| Identity Service | 5002 | Service de gestion des identités |
| Guardian Service | 5003 | Service de permissions |
| Web Service | 3000 | Application Next.js |
| Nginx | 80/443 | Reverse proxy et SSL |

### Routage Nginx

- **`/api/auth/*`** → Auth Service (5001)
- **`/api/identity/*`** → Identity Service (5002)
- **`/api/guardian/*`** → Guardian Service (5003)
- **`/*`** → Web Service (3000)

## 📊 Monitoring et Santé

### Health Checks

```bash
# Health check global
curl -k https://localhost/health

# Health check détaillé des services
curl -k https://localhost/api/health
```

### Logs en temps réel

```bash
# Tous les services
docker compose -f compose/docker-compose.allinone.yml logs -f

# Service spécifique
docker exec waterfall-app supervisorctl tail -f auth-service
docker exec waterfall-app supervisorctl tail -f web-service
```

### Gestion des processus

```bash
# Status des services
docker exec waterfall-app supervisorctl status

# Redémarrer un service
docker exec waterfall-app supervisorctl restart auth-service

# Arrêter/démarrer un service
docker exec waterfall-app supervisorctl stop web-service
docker exec waterfall-app supervisorctl start web-service
```

## 🔧 Maintenance

### Sauvegarde des données

```bash
# Sauvegarde PostgreSQL
docker exec waterfall-app pg_dump -U waterfall -h localhost waterfall_auth > backup_auth.sql
docker exec waterfall-app pg_dump -U waterfall -h localhost waterfall_identity > backup_identity.sql
docker exec waterfall-app pg_dump -U waterfall -h localhost waterfall_guardian > backup_guardian.sql

# Sauvegarde des secrets
docker cp waterfall-app:/opt/waterfall/secrets ./secrets-backup/
```

### Mise à jour

```bash
# Arrêt propre
docker compose -f compose/docker-compose.allinone.yml down

# Reconstruction avec nouvelle version
docker compose -f compose/docker-compose.allinone.yml up -d --build

# Les données et secrets sont conservés grâce aux volumes
```

### Nettoyage

```bash
# Arrêt et suppression (ATTENTION: supprime les données)
docker compose -f compose/docker-compose.allinone.yml down -v

# Suppression de l'image
docker rmi $(docker images | grep waterfall-app | awk '{print $3}')
```

## ⚡ Optimisation

### Ressources recommandées

- **RAM minimum** : 1GB
- **RAM recommandée** : 2GB
- **CPU minimum** : 1 core
- **Stockage** : 5GB pour les données et logs

### Tuning PostgreSQL

Pour des environnements avec plus de ressources, modifiez `/var/lib/postgresql/15/main/postgresql.conf` :

```bash
# Accès au conteneur
docker exec -it waterfall-app bash

# Édition de la configuration PostgreSQL
nano /var/lib/postgresql/15/main/postgresql.conf

# Redémarrage PostgreSQL
supervisorctl restart postgresql
```

## 🐛 Dépannage

### Problèmes courants

1. **Services ne démarrent pas**
   ```bash
   docker exec waterfall-app supervisorctl status
   docker logs waterfall-app
   ```

2. **Base de données inaccessible**
   ```bash
   docker exec waterfall-app psql -U waterfall -h localhost -l
   ```

3. **Certificats SSL invalides**
   ```bash
   docker exec waterfall-app ls -la /etc/ssl/waterfall/
   ```

### Redémarrage des services

```bash
# Redémarrage complet
docker compose -f compose/docker-compose.allinone.yml restart

# Redémarrage d'un service spécifique
docker exec waterfall-app supervisorctl restart auth-service
```