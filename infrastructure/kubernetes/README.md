# Delivery360 - Kubernetes Infrastructure

## 📋 Requisitos Previos

- Kubernetes 1.28+
- kubectl configurado
- Helm 3.x (opcional para algunos componentes)
- NGINX Ingress Controller
- cert-manager para SSL
- Metrics Server para HPA

## 🚀 Despliegue Rápido

### 1. Crear Namespace y Recursos Base

```bash
cd infrastructure/kubernetes/manifests

# Aplicar todos los recursos
kubectl apply -k .

# O aplicar individualmente
kubectl apply -f namespace.yaml
kubectl apply -f configmap.yaml
kubectl apply -f secrets-template.yaml  # Editar primero!
kubectl apply -f postgres.yaml
kubectl apply -f redis.yaml
kubectl apply -f backend.yaml
kubectl apply -f celery.yaml
kubectl apply -f frontend.yaml
kubectl apply -f ingress.yaml
kubectl apply -f hpa.yaml
kubectl apply -f network-policies.yaml
```

### 2. Configurar Secretos (CRÍTICO)

Antes de desplegar, genera los secretos reales:

```bash
# Generar SECRET_KEY
python -c "import secrets; print(secrets.token_urlsafe(64))"

# Generar contraseñas seguras
openssl rand -base64 32

# Editar secrets-template.yaml y crear el secreto real
kubectl create secret generic backend-secret \
  --from-literal=SECRET_KEY='TU_SECRET_KEY_AQUI' \
  --from-literal=SMTP_USERNAME='tu@email.com' \
  --from-literal=SMTP_PASSWORD='tu_password' \
  -n delivery360
```

### 3. Verificar Despliegue

```bash
# Ver pods
kubectl get pods -n delivery360

# Ver servicios
kubectl get svc -n delivery360

# Ver logs
kubectl logs -f deployment/backend -n delivery360

# Verificar health check
kubectl exec -it deployment/backend -n delivery360 -- curl http://localhost:8000/health
```

### 4. Escalar Aplicación

```bash
# Escalar backend manualmente
kubectl scale deployment backend --replicas=5 -n delivery360

# El HPA ajustará automáticamente basado en CPU/Memoria
kubectl get hpa -n delivery360
```

## 🔧 Configuración por Entorno

### Desarrollo

```bash
kubectl apply -k environments/dev
```

### Staging

```bash
kubectl apply -k environments/staging
```

### Producción

```bash
kubectl apply -k environments/production
```

## 📊 Monitoreo

### Métricas con Prometheus

Los deployments incluyen annotations para scraping automático:

```yaml
prometheus.io/scrape: "true"
prometheus.io/port: "8000"
prometheus.io/path: "/metrics"
```

### Dashboards Grafana

Importar dashboards desde `configs/grafana-dashboards/`

## 🔒 Seguridad

### Network Policies

- Backend solo acepta tráfico de Frontend e Ingress
- PostgreSQL solo acepta tráfico de Backend
- Redis solo acepta tráfico de Backend y Celery

### Secrets Management

**Producción:** Usar External Secrets Operator o SOPS

```bash
# Instalar External Secrets
helm repo add external-secrets https://external-secrets.github.io/kubernetes-external-secrets
helm install external-secrets external-secrets/external-secrets
```

## 🔄 Actualizaciones

### Rollout de Nueva Versión

```bash
# Actualizar imagen
kubectl set image deployment/backend backend=delivery360/backend:v1.1.0 -n delivery360

# Monitorear rollout
kubectl rollout status deployment/backend -n delivery360

# Rollback si es necesario
kubectl rollout undo deployment/backend -n delivery360
```

## 🆘 Troubleshooting

### Pods no inician

```bash
kubectl describe pod <pod-name> -n delivery360
kubectl logs <pod-name> -n delivery360
```

### Problemas de Conexión a DB

```bash
kubectl exec -it deployment/postgres -n delivery360 -- psql -U delivery360_user -d delivery360_prod
```

### Debug de Red

```bash
kubectl run -it --rm debug --image=nicolaka/netshoot -n delivery360
```

## 📁 Estructura de Archivos

```
manifests/
├── namespace.yaml              # Namespace delivery360
├── configmap.yaml              # ConfigMaps para todos los servicios
├── secrets-template.yaml       # Template de secretos (NO USAR EN PROD)
├── postgres.yaml               # PostgreSQL StatefulSet + PVC
├── redis.yaml                  # Redis Deployment + Service
├── backend.yaml                # Backend API Deployment + Service
├── celery.yaml                 # Celery Worker + Beat Deployments
├── frontend.yaml               # Frontend Next.js Deployment + Service
├── ingress.yaml                # Ingress con SSL y rate limiting
├── hpa.yaml                    # Horizontal Pod Autoscalers
├── network-policies.yaml       # Network Policies de seguridad
└── kustomization.yaml          # Kustomize configuration
```

## 💰 Costos Estimados (GCP/AWS)

| Componente | CPU | Memoria | Costo Mensual Aprox. |
|------------|-----|---------|---------------------|
| Backend (3 pods) | 0.75 vCPU | 1.5 GB | $45 |
| Frontend (2 pods) | 0.2 vCPU | 0.5 GB | $15 |
| Celery (2 pods) | 0.5 vCPU | 1 GB | $30 |
| PostgreSQL | 1 vCPU | 2 GB | $50 |
| Redis | 0.1 vCPU | 0.25 GB | $15 |
| **Total** | **2.55 vCPU** | **5.25 GB** | **~$155/mes** |

*Costos varían según región y proveedor*
