# Delivery360 - Terraform AWS Infrastructure
# Provider configuration for AWS

terraform {
  required_version = ">= 1.5.0"
  
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.23"
    }
    helm = {
      source  = "hashicorp/helm"
      version = "~> 2.11"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.5"
    }
  }
  
  backend "s3" {
    bucket         = "delivery360-terraform-state"
    key            = "production/terraform.tfstate"
    region         = "us-east-1"
    encrypt        = true
    dynamodb_table = "terraform-locks"
  }
}

provider "aws" {
  region = var.aws_region
  
  default_tags {
    tags = {
      Project     = "Delivery360"
      Environment = var.environment
      ManagedBy   = "Terraform"
    }
  }
}

provider "kubernetes" {
  host                   = data.aws_eks_cluster.cluster.endpoint
  cluster_ca_certificate = base64decode(data.aws_eks_cluster.cluster.certificate_authority[0].data)
  token                  = data.aws_eks_cluster_auth.cluster.token
}

provider "helm" {
  kubernetes {
    host                   = data.aws_eks_cluster.cluster.endpoint
    cluster_ca_certificate = base64decode(data.aws_eks_cluster.cluster.certificate_authority[0].data)
    token                  = data.aws_eks_cluster_auth.cluster.token
  }
}

# Data sources
data "aws_eks_cluster" "cluster" {
  name = var.eks_cluster_name
}

data "aws_eks_cluster_auth" "cluster" {
  name = var.eks_cluster_name
}

data "aws_availability_zones" "available" {}

data "aws_caller_identity" "current" {}

# Variables
variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Environment name"
  type        = string
  default     = "production"
}

variable "eks_cluster_name" {
  description = "EKS cluster name"
  type        = string
  default     = "delivery360-cluster"
}

variable "vpc_cidr" {
  description = "VPC CIDR block"
  type        = string
  default     = "10.0.0.0/16"
}

variable "enable_nat_gateway" {
  description = "Enable NAT Gateway"
  type        = bool
  default     = true
}

variable "single_az" {
  description = "Single AZ for cost savings (dev only)"
  type        = bool
  default     = false
}

# Random suffix for unique names
resource "random_id" "suffix" {
  byte_length = 4
}

# VPC Module
module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 5.0"
  
  name = "delivery360-vpc"
  cidr = var.vpc_cidr
  
  azs             = var.single_az ? [data.aws_availability_zones.available.names[0]] : slice(data.aws_availability_zones.available.names, 0, 3)
  private_subnets = var.single_az ? ["10.0.1.0/24"] : ["10.0.1.0/24", "10.0.2.0/24", "10.0.3.0/24"]
  public_subnets  = var.single_az ? ["10.0.101.0/24"] : ["10.0.101.0/24", "10.0.102.0/24", "10.0.103.0/24"]
  
  enable_nat_gateway = var.enable_nat_gateway
  single_nat_gateway = var.single_az
  
  create_database_subnet_group = true
  database_subnets             = var.single_az ? ["10.0.201.0/24"] : ["10.0.201.0/24", "10.0.202.0/24", "10.0.203.0/24"]
  
  enable_dns_hostnames = true
  enable_dns_support   = true
  
  tags = {
    "kubernetes.io/cluster/${var.eks_cluster_name}" = "shared"
    Kubernetes                                    = "true"
  }
}

# EKS Cluster Module
module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 20.0"
  
  cluster_name    = var.eks_cluster_name
  cluster_version = "1.28"
  
  vpc_id     = module.vpc.vpc_id
  subnet_ids = module.vpc.private_subnets
  
  eks_managed_node_groups = {
    general = {
      min_size     = 2
      max_size     = 10
      desired_size = 3
      
      instance_types = ["t3.medium", "t3.large"]
      capacity_type  = "ON_DEMAND"
      
      disk_size = 50
    }
    
    spot = {
      min_size     = 1
      max_size     = 5
      desired_size = 2
      
      instance_types = ["t3.medium", "t3.large"]
      capacity_type  = "SPOT"
      
      disk_size = 50
    }
  }
  
  cluster_endpoint_public_access  = true
  cluster_endpoint_private_access = true
  
  enable_irsa = true
  
  tags = {
    Environment = var.environment
  }
}

# RDS PostgreSQL
module "db" {
  source  = "terraform-aws-modules/rds/aws"
  version = "~> 6.0"
  
  identifier = "delivery360-db-${random_id.suffix.hex}"
  
  engine            = "postgres"
  engine_version    = "16"
  family            = "postgres16"
  major_engine_version = "16"
  instance_class    = "db.t3.medium"
  
  allocated_storage     = 100
  max_allocated_storage = 500
  storage_encrypted     = true
  storage_type          = "gp3"
  
  db_name  = "delivery360_prod"
  username = "delivery360_admin"
  password = random_password.db_password.result
  port     = 5432
  
  multi_az               = !var.single_az
  db_subnet_group_name   = module.vpc.database_subnet_group_name
  vpc_security_group_ids = [aws_security_group.rds.id]
  
  maintenance_window              = "Mon:00:00-Mon:03:00"
  backup_retention_period         = 30
  backup_window                   = "03:00-06:00"
  enabled_cloudwatch_logs_exports = ["postgresql", "upgrade"]
  
  deletion_protection = true
  skip_final_snapshot = false
  final_snapshot_identifier = "delivery360-final-snapshot"
  
  parameters = [
    {
      name  = "pg_stat_statements.track"
      value = "all"
    },
    {
      name  = "pg_stat_statements.max"
      value = "10000"
    }
  ]
  
  tags = {
    Environment = var.environment
  }
}

resource "random_password" "db_password" {
  length           = 32
  special          = true
  override_special = "!#$%&*()-_=+[]{}<>:?"
}

# ElastiCache Redis
module "redis" {
  source  = "terraform-aws-modules/elasticache/aws"
  version = "~> 7.0"
  
  cluster_id = "delivery360-redis-${random_id.suffix.hex}"
  
  engine          = "redis"
  engine_version  = "7.0"
  node_type       = "cache.t3.medium"
  num_cache_nodes = var.single_az ? 1 : 3
  
  parameter_group_name = "default.redis7"
  subnet_group_name    = aws_elasticache_subnet_group.redis.name
  security_group_ids   = [aws_security_group.redis.id]
  
  at_rest_encryption_enabled = true
  transit_encryption_enabled = true
  auth_token                 = random_password.redis_auth.result
  
  snapshot_retention_limit = 7
  maintenance_window       = "sun:05:00-sun:09:00"
  
  tags = {
    Environment = var.environment
  }
}

resource "random_password" "redis_auth" {
  length           = 32
  special          = false
}

resource "aws_elasticache_subnet_group" "redis" {
  name       = "delivery360-redis-subnet-group"
  subnet_ids = module.vpc.private_subnets
}

# Security Groups
resource "aws_security_group" "rds" {
  name_prefix = "delivery360-rds-"
  vpc_id      = module.vpc.vpc_id
  
  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [module.eks.cluster_security_group_id]
  }
  
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
  
  tags = {
    Name = "delivery360-rds-sg"
  }
}

resource "aws_security_group" "redis" {
  name_prefix = "delivery360-redis-"
  vpc_id      = module.vpc.vpc_id
  
  ingress {
    from_port       = 6379
    to_port         = 6379
    protocol        = "tcp"
    security_groups = [module.eks.cluster_security_group_id]
  }
  
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
  
  tags = {
    Name = "delivery360-redis-sg"
  }
}

# S3 Buckets
resource "aws_s3_bucket" "app_data" {
  bucket = "delivery360-app-data-${random_id.suffix.hex}"
  
  tags = {
    Name        = "Application Data"
    Environment = var.environment
  }
}

resource "aws_s3_bucket" "logs" {
  bucket = "delivery360-logs-${random_id.suffix.hex}"
  
  tags = {
    Name        = "Application Logs"
    Environment = var.environment
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "logs_lifecycle" {
  bucket = aws_s3_bucket.logs.id
  
  rule {
    id     = "expire-old-logs"
    status = "Enabled"
    
    expiration {
      days = 90
    }
  }
}

# Outputs
output "eks_cluster_endpoint" {
  description = "EKS cluster endpoint"
  value       = module.eks.cluster_endpoint
}

output "eks_cluster_name" {
  description = "EKS cluster name"
  value       = module.eks.cluster_name
}

output "vpc_id" {
  description = "VPC ID"
  value       = module.vpc.vpc_id
}

output "rds_endpoint" {
  description = "RDS endpoint"
  value       = module.db.db_instance_address
  sensitive   = true
}

output "redis_endpoint" {
  description = "Redis endpoint"
  value       = module.redis.elasticache_cluster_primary_endpoint
  sensitive   = true
}

output "s3_app_data_bucket" {
  description = "S3 bucket for app data"
  value       = aws_s3_bucket.app_data.id
}

output "s3_logs_bucket" {
  description = "S3 bucket for logs"
  value       = aws_s3_bucket.logs.id
}
