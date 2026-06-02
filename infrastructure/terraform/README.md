# Delivery360 - Terraform Infrastructure as Code

## 📋 Requisitos Previos

- Terraform >= 1.5.0
- AWS CLI configurado
- kubectl para EKS
- Helm 3.x

## 🚀 Quick Start

### 1. Configurar AWS Credentials

```bash
aws configure
# O usar variables de entorno
export AWS_ACCESS_KEY_ID="tu_access_key"
export AWS_SECRET_ACCESS_KEY="tu_secret_key"
export AWS_DEFAULT_REGION="us-east-1"
```

### 2. Inicializar Backend S3 (Primera vez)

```bash
cd infrastructure/terraform/aws

# Crear bucket para estado
aws s3 mb s3://delivery360-terraform-state --region us-east-1
aws s3api put-bucket-versioning --bucket delivery360-terraform-state --versioning-configuration Status=Enabled

# Crear tabla DynamoDB para locks
aws dynamodb create-table \
  --table-name terraform-locks \
  --attribute-definitions AttributeName=LockID,AttributeType=S \
  --key-schema AttributeName=LockID,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST \
  --region us-east-1
```

### 3. Inicializar Terraform

```bash
terraform init
```

### 4. Planificar Infraestructura

```bash
# Desarrollo (single AZ, más económico)
terraform plan -var="environment=development" -var="single_az=true" -out=tfplan

# Producción (multi AZ, alta disponibilidad)
terraform plan -var="environment=production" -var="single_az=false" -out=tfplan
```

### 5. Aplicar Infraestructura

```bash
terraform apply tfplan
```

## 🏗️ Recursos Provisionados

| Recurso | Descripción | Costo Mensual Aprox. |
|---------|-------------|---------------------|
| **EKS Cluster** | Kubernetes 1.28 | $73 + nodos |
| **Node Groups** | 3x t3.medium (on-demand) + 2x t3.medium (spot) | ~$150 |
| **RDS PostgreSQL** | db.t3.medium, 100GB, multi-AZ | ~$150 |
| **ElastiCache Redis** | cache.t3.medium, 3 nodos | ~$100 |
| **VPC** | 3 AZs, subnets públicas/privadas | Gratis |
| **NAT Gateway** | 1 por AZ (producción) | ~$100 |
| **S3 Buckets** | App data + logs | ~$5 |
| **Total Estimado** | | **~$578/mes** |

*Costos pueden variar según región y uso*

## 📁 Estructura de Archivos

```
terraform/
├── aws/
│   ├── main.tf              # Configuración principal
│   ├── variables.tf         # Variables (inline en main.tf)
│   ├── outputs.tf           # Outputs (inline en main.tf)
│   ├── versions.tf          # Versiones de providers
│   └── README.md            # Esta documentación
├── gcp/                     # (Futuro soporte GCP)
└── modules/                 # Módulos reutilizables
```

## 🔧 Configuración por Entorno

### Development

```bash
terraform apply \
  -var="environment=development" \
  -var="single_az=true" \
  -var="enable_nat_gateway=false"
```

### Staging

```bash
terraform apply \
  -var="environment=staging" \
  -var="single_az=false" \
  -var="enable_nat_gateway=true"
```

### Production

```bash
terraform apply \
  -var="environment=production" \
  -var="single_az=false" \
  -var="enable_nat_gateway=true"
```

## 🔐 Gestión de Secretos

Los secretos sensibles se generan automáticamente:

- Contraseña de RDS: `random_password.db_password`
- Token de autenticación Redis: `random_password.redis_auth`

Para acceder a los valores:

```bash
terraform output -raw rds_endpoint
terraform output -raw redis_endpoint
```

## 🔄 Actualizaciones

### Actualizar Versión de EKS

```bash
terraform state show module.eks.aws_eks_cluster.this[0]
# Editar cluster_version en variables
terraform plan -target=module.eks
terraform apply
```

### Escalar Node Group

```bash
terraform apply \
  -var="desired_size_general=5" \
  -var="max_size_general=15"
```

### Actualizar Instancia de RDS

```bash
terraform apply \
  -var="db_instance_class=db.t3.large"
```

## 🛡️ Seguridad

### Encriptación

- ✅ RDS: Encriptación en reposo activada
- ✅ ElastiCache: Encriptación en tránsito y reposo
- ✅ S3: Encriptación SSE-S3 por defecto
- ✅ VPC: Security groups restrictivos

### Network Security

- ✅ Subnets privadas para bases de datos
- ✅ NAT Gateway para salida a internet
- ✅ Security groups específicos por servicio
- ✅ VPC Flow Logs (opcional)

### Compliance

- ✅ Tags automáticos para governance
- ✅ Deletion protection en RDS
- ✅ Snapshots automáticos (30 días retención)
- ✅ Multi-AZ en producción

## 💰 Optimización de Costos

### Para Desarrollo

```bash
terraform apply \
  -var="single_az=true" \
  -var="enable_nat_gateway=false" \
  -var="eks_managed_node_groups={}"
```

### Usar Spot Instances

El node group "spot" ya está configurado con instancias spot (70% descuento).

### Auto Scaling

- HPA configurado en Kubernetes
- Node group auto scaling: 2-10 nodos
- RDS storage auto scaling: 100GB → 500GB

## 🆘 Troubleshooting

### Estado Bloqueado

```bash
# Forzar unlock
terraform force-unlock <LOCK_ID>
```

### Ver Estado

```bash
terraform state list
terraform state show module.eks
```

### Importar Recursos Existentes

```bash
terraform import module.vpc.aws_vpc.this vpc-12345678
```

### Debug Mode

```bash
export TF_LOG=DEBUG
terraform apply
```

## 🧹 Destruir Infraestructura

⚠️ **ADVERTENCIA**: Esto eliminará todos los recursos

```bash
# Deshabilitar deletion protection primero
terraform apply -var="deletion_protection=false"

# Destruir todo
terraform destroy
```

## 📊 Monitoreo y Alertas

### CloudWatch

Todos los recursos envían métricas a CloudWatch:

- EKS: CPU, memoria, pods
- RDS: CPU, conexiones, IOPS
- ElastiCache: Hit rate, memoria
- VPC: Network in/out

### Dashboards Recomendados

1. **EKS Cluster Health**
2. **Application Performance**
3. **Database Metrics**
4. **Cost Analysis**

## 🚀 Próximos Pasos

Después de aplicar Terraform:

1. Configurar kubectl:
   ```bash
   aws eks update-kubeconfig --name delivery360-cluster --region us-east-1
   ```

2. Instalar addons:
   ```bash
   # NGINX Ingress Controller
   helm install ingress-nginx ingress-nginx/ingress-nginx \
     --namespace ingress-nginx --create-namespace
   
   # cert-manager para SSL
   helm install cert-manager jetstack/cert-manager \
     --namespace cert-manager --create-namespace \
     --set installCRDs=true
   
   # External Secrets
   helm install external-secrets external-secrets/external-secrets \
     --namespace external-secrets --create-namespace
   ```

3. Deploy aplicación:
   ```bash
   cd ../../kubernetes/manifests
   kubectl apply -k .
   ```

## 📞 Soporte

Para issues relacionados con Terraform:

1. Revisar logs de CloudWatch
2. Verificar permisos IAM
3. Consultar estado de recursos en AWS Console
4. Revisar [documentación oficial de Terraform AWS Provider](https://registry.terraform.io/providers/hashicorp/aws/latest/docs)
