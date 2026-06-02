# Delivery360 - Guía de Despliegue a Producción

## 📋 Checklist Pre-Despliegue

### ✅ FASE 1: Preparación (Completada)

- [x] Documentación de arquitectura
- [x] Documentación de API
- [x] Archivo `.env.example`
- [x] Modelo Vehicle corregido
- [x] Seed script validado
- [ ] Tests automatizados (pendiente)
- [ ] Validación de email (pendiente)
- [x] SECRET_KEY generado

### ✅ FASE 2: Infraestructura (Completada)

- [x] Kubernetes manifests completos
- [x] Terraform AWS configurado
- [x] CI/CD pipeline GitHub Actions
- [x] Documentación de despliegue

---

## 🚀 Proceso de Despliegue Paso a Paso

### SEMANA 1-2: Configuración de Infraestructura

#### Día 1-3: Setup de AWS

```bash
# 1. Configurar AWS CLI
aws configure

# 2. Crear bucket para Terraform state
aws s3 mb s3://delivery360-terraform-state
aws s3api put-bucket-versioning \
  --bucket delivery360-terraform-state \
  --versioning-configuration Status=Enabled

# 3. Crear tabla DynamoDB para locks
aws dynamodb create-table \
  --table-name terraform-locks \
  --attribute-definitions AttributeName=LockID,AttributeType=S \
  --key-schema AttributeName=LockID,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST

# 4. Aplicar infraestructura
cd infrastructure/terraform/aws
terraform init
terraform plan -var="environment=staging" -out=tfplan
terraform apply tfplan
```

**Resultado Esperado:**
- ✅ VPC con 3 AZs
- ✅ EKS Cluster 1.28
- ✅ RDS PostgreSQL 16
- ✅ ElastiCache Redis 7
- ✅ S3 Buckets

#### Día 4-5: Configurar Kubernetes

```bash
# 1. Configurar kubectl
aws eks update-kubeconfig \
  --name delivery360-cluster \
  --region us-east-1

# 2. Instalar NGINX Ingress Controller
helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx
helm install ingress-nginx ingress-nginx/ingress-nginx \
  --namespace ingress-nginx \
  --create-namespace \
  --set controller.replicaCount=2 \
  --set controller.autoscaling.enabled=true \
  --set controller.autoscaling.minReplicas=2 \
  --set controller.autoscaling.maxReplicas=10

# 3. Instalar cert-manager para SSL
helm repo add jetstack https://charts.jetstack.io
helm install cert-manager jetstack/cert-manager \
  --namespace cert-manager \
  --create-namespace \
  --set installCRDs=true

# 4. Crear ClusterIssuer para Let's Encrypt
cat > cluster-issuer.yaml << 'YAML'
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-prod
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory
    email: admin@delivery360.com
    privateKeySecretRef:
      name: letsencrypt-prod-key
    solvers:
      - http01:
          ingress:
            class: nginx
YAML

kubectl apply -f cluster-issuer.yaml
```

#### Día 6-7: Configurar Secretos

```bash
# Generar contraseñas seguras
SECRET_KEY=$(python -c "import secrets; print(secrets.token_urlsafe(64))")
DB_PASSWORD=$(openssl rand -base64 32)
REDIS_PASSWORD=$(openssl rand -base64 32)

# Crear secretos en Kubernetes
kubectl create namespace delivery360

kubectl create secret generic postgres-secret \
  --from-literal=POSTGRES_PASSWORD="$DB_PASSWORD" \
  -n delivery360

kubectl create secret generic backend-secret \
  --from-literal=SECRET_KEY="$SECRET_KEY" \
  --from-literal=SMTP_USERNAME="tu@email.com" \
  --from-literal=SMTP_PASSWORD="tu_smtp_password" \
  --from-literal=MAPBOX_TOKEN="tu_mapbox_token" \
  --from-literal=SENTRY_DSN="tu_sentry_dsn" \
  -n delivery360
```

### SEMANA 3: CI/CD y Testing

#### Día 8-10: Configurar GitHub Actions

1. **Configurar Secrets en GitHub:**

Ir a `Settings > Secrets and variables > Actions` y agregar:

```
STAGING_KUBECONFIG=<base64 del kubeconfig>
PRODUCTION_KUBECONFIG=<base64 del kubeconfig>
MAPBOX_TOKEN=<tu token>
SENTRY_AUTH_TOKEN=<tu token>
SENTRY_DSN=<tu dsn>
NEXT_PUBLIC_API_URL=https://api-staging.delivery360.com
```

2. **Configurar Environments:**

```
Environments > staging:
  - Protection rules: Required reviewers
  - Deployment branches: develop

Environments > production:
  - Protection rules: Required reviewers (2 personas)
  - Deployment branches: tags v*.*.*
```

3. **Probar Pipeline:**

```bash
# Hacer push a develop para trigger staging
git checkout -b develop
git push origin develop
```

#### Día 11-12: Tests de Integración

```bash
# 1. Verificar deployments
kubectl get pods -n delivery360
kubectl get svc -n delivery360

# 2. Verificar logs
kubectl logs -f deployment/backend -n delivery360

# 3. Ejecutar health checks
curl https://api-staging.delivery360.com/health

# 4. Ejecutar tests E2E
cd frontend
npm run test:e2e
```

### SEMANA 4: Staging y UAT

#### Día 15-17: User Acceptance Testing

**Checklist de Validación:**

- [ ] Login/Logout funcional
- [ ] Registro de repartidores
- [ ] Creación de órdenes
- [ ] Asignación de repartidores
- [ ] Tracking en tiempo real
- [ ] Prueba de entrega (foto/firma)
- [ ] Dashboard por roles
- [ ] Notificaciones email
- [ ] Pagos y retiros
- [ ] Responsive mobile

#### Día 18-19: Performance Testing

```bash
# Instalar k6
sudo apt install k6

# Ejecutar load test
k6 run tests/load/staging.js

# Métricas objetivo:
# - p95 latency < 500ms
# - Error rate < 0.1%
# - Throughput > 100 req/s
```

### SEMANA 5: Producción

#### Día 22: Deploy a Producción

```bash
# 1. Crear tag de versión
git checkout main
git pull
git tag v1.0.0
git push origin v1.0.0

# 2. Monitorear deployment
# GitHub Actions ejecutará deploy-production automáticamente

# 3. Verificar rollout
kubectl rollout status deployment/backend -n delivery360
kubectl rollout status deployment/frontend -n delivery360

# 4. Smoke tests
curl -f https://api.delivery360.com/health || exit 1
curl -f https://app.delivery360.com || exit 1
```

#### Día 23-25: Hypercare

**Monitoreo Intensivo:**

```bash
# 1. Revisar métricas cada hora
kubectl top pods -n delivery360
kubectl top nodes

# 2. Revisar errores en Sentry
# https://sentry.io/organizations/delivery360

# 3. Revisar logs de aplicación
kubectl logs -f deployment/backend -n delivery360 --tail=100

# 4. Revisar métricas de negocio
# - Órdenes creadas
# - Repartidores activos
# - Tiempos de entrega
```

---

## 🔧 Comandos Útiles

### Troubleshooting

```bash
# Ver estado de pods
kubectl get pods -n delivery360 -o wide

# Describir pod con errores
kubectl describe pod <pod-name> -n delivery360

# Ver logs
kubectl logs <pod-name> -n delivery360
kubectl logs -f deployment/backend -n delivery360 --tail=200

# Exec en pod para debug
kubectl exec -it <pod-name> -n delivery360 -- bash

# Reiniciar deployment
kubectl rollout restart deployment/backend -n delivery360

# Rollback
kubectl rollout undo deployment/backend -n delivery360
```

### Escalado Manual

```bash
# Escalar backend
kubectl scale deployment/backend --replicas=5 -n delivery360

# Escalar frontend
kubectl scale deployment/frontend --replicas=4 -n delivery360
```

### Backup de Base de Datos

```bash
# Crear snapshot manual
aws rds create-db-snapshot \
  --db-instance-identifier delivery360-db-xxxxx \
  --db-snapshot-identifier delivery360-manual-backup-$(date +%Y%m%d)

# Exportar datos
kubectl exec -it deployment/postgres -n delivery360 -- \
  pg_dump -U delivery360_user delivery360_prod > backup.sql
```

---

## 📊 Monitoreo Post-Deploy

### Dashboards Esenciales

1. **Infraestructura:**
   - CPU/Memoria de pods
   - Uso de nodos EKS
   - Estado de RDS y Redis

2. **Aplicación:**
   - Requests por segundo
   - Latencia p50/p95/p99
   - Error rate por endpoint

3. **Negocio:**
   - Órdenes activas
   - Repartidores online
   - Entregas completadas

### Alertas Críticas

Configurar alertas para:

- ❗ Error rate > 1%
- ❗ Latencia p95 > 2s
- ❗ Pods reiniciándose constantemente
- ❗ CPU/Memoria > 80%
- ❗ RDS connections > 80%
- ❗ Disk usage > 85%

---

## 🎯 Criterios de Éxito

El despliegue se considera exitoso cuando:

✅ **Disponibilidad:**
- Uptime > 99.9%
- Sin downtime no planificado

✅ **Performance:**
- p95 latency < 500ms
- Time to First Byte < 200ms

✅ **Funcionalidad:**
- 100% de features críticas operativas
- 0 bugs críticos reportados

✅ **Seguridad:**
- SSL válido en todos los dominios
- 0 vulnerabilidades críticas en scans

✅ **Negocio:**
- Primeras órdenes procesadas exitosamente
- Repartidores pueden completar entregas

---

## 📞 Contactos de Emergencia

| Rol | Nombre | Contacto |
|-----|--------|----------|
| Tech Lead | [Nombre] | [Teléfono/Email] |
| DevOps | [Nombre] | [Teléfono/Email] |
| On-call | [Rotativo] | [PagerDuty] |

---

## 📝 Lecciones Aprendidas

Después del deploy, documentar:

1. ¿Qué salió bien?
2. ¿Qué problemas surgieron?
3. ¿Cómo mejorar el proceso para la próxima vez?
4. ¿Qué automatizaciones faltan?

---

**Última actualización:** $(date +%Y-%m-%d)
**Versión del documento:** 1.0
