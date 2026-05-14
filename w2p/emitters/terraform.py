from __future__ import annotations

import json
import re

from ..models import ServiceNode, TopologySpec

SECRET_KEY_PATTERN = re.compile(r"(SECRET|TOKEN|PASSWORD|PRIVATE_KEY|API_KEY|DATABASE_URL)", re.IGNORECASE)


def generate_terraform_files(topology: TopologySpec) -> dict[str, str]:
    if topology.deployment.provider == "azure":
        return _generate_azure_terraform_files(topology)
    if topology.deployment.provider == "gcp":
        return _generate_gcp_terraform_files(topology)
    return _generate_aws_terraform_files(topology)


def _generate_aws_terraform_files(topology: TopologySpec) -> dict[str, str]:
    services_json = json.dumps(_services_map(topology), indent=2, sort_keys=True)
    datastores_json = json.dumps(_datastores_map(topology), indent=2, sort_keys=True)
    project_name = _slug(topology.metadata.name)

    main_tf = _MAIN_TF.replace("__PROJECT_NAME__", project_name)
    main_tf = main_tf.replace("__SERVICES_JSON__", services_json)
    main_tf = main_tf.replace("__DATASTORES_JSON__", datastores_json)

    variables_tf = _VARIABLES_TF.replace("__AWS_REGION__", topology.deployment.region)
    variables_tf = variables_tf.replace("__ENVIRONMENT__", topology.deployment.environment)

    tfvars = f'''environment = "{topology.deployment.environment}"
aws_region  = "{topology.deployment.region}"

# Supply existing private network IDs from your landing zone.
vpc_id             = "vpc-00000000000000000"
private_subnet_ids = ["subnet-00000000000000000", "subnet-11111111111111111"]

# Keep empty by default. Add approved CIDRs explicitly.
ingress_cidr_blocks = []
egress_cidr_blocks  = []

# Required when services use secret://, ssm://, or AWS secret ARNs in env values.
secret_resource_arns = []
'''

    return {
        "terraform/main.tf": main_tf,
        "terraform/outputs.tf": _OUTPUTS_TF,
        "terraform/terraform.tfvars.example": tfvars,
        "terraform/variables.tf": variables_tf,
        "terraform/versions.tf": _VERSIONS_TF,
    }


def _generate_azure_terraform_files(topology: TopologySpec) -> dict[str, str]:
    project_name = _slug(topology.metadata.name)
    services_json = json.dumps(_services_map(topology), indent=2, sort_keys=True)
    datastores_json = json.dumps(_datastores_map(topology), indent=2, sort_keys=True)
    main_tf = _AZURE_MAIN_TF.replace("__PROJECT_NAME__", project_name)
    main_tf = main_tf.replace("__SERVICES_JSON__", services_json)
    main_tf = main_tf.replace("__DATASTORES_JSON__", datastores_json)
    variables_tf = _AZURE_VARIABLES_TF.replace("__AZURE_LOCATION__", topology.deployment.region)
    variables_tf = variables_tf.replace("__ENVIRONMENT__", topology.deployment.environment)
    tfvars = f'''environment    = "{topology.deployment.environment}"
azure_location = "{topology.deployment.region}"

# Keep empty by default. Add approved CIDRs explicitly.
ingress_cidr_blocks = []
egress_cidr_blocks  = []
'''
    return {
        "terraform/main.tf": main_tf,
        "terraform/outputs.tf": _AZURE_OUTPUTS_TF,
        "terraform/terraform.tfvars.example": tfvars,
        "terraform/variables.tf": variables_tf,
        "terraform/versions.tf": _AZURE_VERSIONS_TF,
    }


def _generate_gcp_terraform_files(topology: TopologySpec) -> dict[str, str]:
    project_name = _slug(topology.metadata.name)
    services_json = json.dumps(_services_map(topology), indent=2, sort_keys=True)
    datastores_json = json.dumps(_datastores_map(topology), indent=2, sort_keys=True)
    main_tf = _GCP_MAIN_TF.replace("__PROJECT_NAME__", project_name)
    main_tf = main_tf.replace("__SERVICES_JSON__", services_json)
    main_tf = main_tf.replace("__DATASTORES_JSON__", datastores_json)
    variables_tf = _GCP_VARIABLES_TF.replace("__GCP_REGION__", topology.deployment.region)
    variables_tf = variables_tf.replace("__ENVIRONMENT__", topology.deployment.environment)
    tfvars = f'''environment = "{topology.deployment.environment}"
gcp_region  = "{topology.deployment.region}"

# Set this to the target Google Cloud project before apply.
gcp_project_id = "your-project-id"

# Keep empty by default. Add approved CIDRs explicitly.
ingress_cidr_blocks = []
egress_cidr_blocks  = []
'''
    return {
        "terraform/main.tf": main_tf,
        "terraform/outputs.tf": _GCP_OUTPUTS_TF,
        "terraform/terraform.tfvars.example": tfvars,
        "terraform/variables.tf": variables_tf,
        "terraform/versions.tf": _GCP_VERSIONS_TF,
    }


def _services_map(topology: TopologySpec) -> dict[str, dict]:
    return {service.id: _service_map(service) for service in sorted(topology.services, key=lambda item: item.id)}


def _service_map(service: ServiceNode) -> dict:
    plain_env: dict[str, str] = {}
    secrets: list[dict[str, str]] = []

    for key, value in sorted(service.env.items()):
        if SECRET_KEY_PATTERN.search(key) or value.startswith(("secret://", "ssm://", "arn:aws:")):
            secrets.append({"name": key, "value_from": _secret_value_from(value, service.id, key)})
        else:
            plain_env[key] = value

    return {
        "cpu": service.resources.cpu_millicores,
        "env": plain_env,
        "image": service.image,
        "memory": service.resources.memory_mib,
        "ports": [port.port for port in sorted(service.ports, key=lambda item: item.port)],
        "public": service.security.public,
        "replicas": service.replicas,
        "secrets": secrets,
    }


def _datastores_map(topology: TopologySpec) -> dict[str, dict]:
    return {
        datastore.id: {
            "backups_enabled": datastore.backups_enabled,
            "encrypted_at_rest": datastore.encrypted_at_rest,
            "kind": datastore.kind,
            "version": datastore.version,
        }
        for datastore in sorted(topology.datastores, key=lambda item: item.id)
    }


def _secret_value_from(value: str, service_id: str, key: str) -> str:
    if value.startswith("secret://"):
        return value.removeprefix("secret://")
    if value.startswith("ssm://"):
        return value.removeprefix("ssm://")
    if value.startswith("arn:aws:"):
        return value
    return f"/w2p/{service_id}/{key.lower()}"


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9-]+", "-", value.lower()).strip("-")
    slug = re.sub(r"-+", "-", slug)
    return slug or "w2p"


_VERSIONS_TF = """terraform {
  required_version = ">= 1.6.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}

provider "aws" {
  region = var.aws_region
}
"""

_VARIABLES_TF = """variable "environment" {
  description = "Deployment environment."
  type        = string
  default     = "__ENVIRONMENT__"

  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "environment must be dev, staging, or prod."
  }
}

variable "aws_region" {
  description = "AWS region for generated infrastructure."
  type        = string
  default     = "__AWS_REGION__"
}

variable "vpc_id" {
  description = "Existing VPC ID from the approved landing zone."
  type        = string
}

variable "private_subnet_ids" {
  description = "Private subnet IDs for workloads and datastores."
  type        = list(string)
}

variable "ingress_cidr_blocks" {
  description = "Approved CIDRs allowed to reach public services. Empty means no ingress."
  type        = list(string)
  default     = []
}

variable "egress_cidr_blocks" {
  description = "Approved CIDRs for HTTPS egress. Empty means no egress."
  type        = list(string)
  default     = []
}

variable "secret_resource_arns" {
  description = "Secrets Manager or SSM Parameter ARNs that ECS tasks may read."
  type        = list(string)
  default     = []
}

variable "log_retention_days" {
  description = "CloudWatch log retention."
  type        = number
  default     = 30
}

variable "db_instance_class" {
  description = "RDS instance class for generated relational datastores."
  type        = string
  default     = "db.t4g.micro"
}

variable "cache_node_type" {
  description = "ElastiCache node type for generated Redis datastores."
  type        = string
  default     = "cache.t4g.micro"
}
"""

_MAIN_TF = """locals {
  project_name = "__PROJECT_NAME__"
  name_prefix  = "${local.project_name}-${var.environment}"

  services = jsondecode(<<SERVICES_JSON
__SERVICES_JSON__
SERVICES_JSON
  )

  datastores = jsondecode(<<DATASTORES_JSON
__DATASTORES_JSON__
DATASTORES_JSON
  )

  db_datastores = {
    for key, value in local.datastores : key => value
    if contains(["postgres", "mysql"], value.kind)
  }

  redis_datastores = {
    for key, value in local.datastores : key => value
    if value.kind == "redis"
  }

  s3_datastores = {
    for key, value in local.datastores : key => value
    if value.kind == "s3"
  }

  queue_datastores = {
    for key, value in local.datastores : key => value
    if value.kind == "queue"
  }

  networked_datastores = merge(local.db_datastores, local.redis_datastores)

  datastore_ports = {
    postgres = 5432
    mysql    = 3306
    redis    = 6379
  }
}

data "aws_caller_identity" "current" {}

resource "aws_kms_key" "logs" {
  description             = "KMS key for ${local.name_prefix} service logs"
  deletion_window_in_days = 30
  enable_key_rotation     = true
}

resource "aws_cloudwatch_log_group" "service" {
  for_each          = local.services
  name              = "/ecs/${local.name_prefix}/${each.key}"
  retention_in_days = var.log_retention_days
  kms_key_id        = aws_kms_key.logs.arn
}

resource "aws_ecs_cluster" "main" {
  name = "${local.name_prefix}-cluster"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

data "aws_iam_policy_document" "ecs_task_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "task_execution" {
  name               = "${local.name_prefix}-ecs-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_task_assume_role.json
}

resource "aws_iam_role_policy_attachment" "task_execution" {
  role       = aws_iam_role.task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role" "task" {
  name               = "${local.name_prefix}-ecs-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_task_assume_role.json
}

data "aws_iam_policy_document" "task_secrets" {
  statement {
    actions   = ["kms:Decrypt", "secretsmanager:GetSecretValue", "ssm:GetParameters", "ssm:GetParameter"]
    resources = length(var.secret_resource_arns) > 0 ? var.secret_resource_arns : ["arn:aws:ssm:*:*:parameter/w2p/placeholder"]
  }
}

resource "aws_iam_role_policy" "task_execution_secrets" {
  count  = length(var.secret_resource_arns) > 0 ? 1 : 0
  name   = "${local.name_prefix}-secret-read"
  role   = aws_iam_role.task_execution.id
  policy = data.aws_iam_policy_document.task_secrets.json
}

resource "aws_security_group" "service" {
  name        = "${local.name_prefix}-svc"
  description = "W2P service security group"
  vpc_id      = var.vpc_id

  dynamic "ingress" {
    for_each = length(var.ingress_cidr_blocks) == 0 ? {} : {
      for key, value in local.services : key => value
      if value.public && length(value.ports) > 0
    }

    content {
      description = "Approved ingress for ${ingress.key}"
      from_port   = ingress.value.ports[0]
      to_port     = ingress.value.ports[0]
      protocol    = "tcp"
      cidr_blocks = var.ingress_cidr_blocks
    }
  }

  dynamic "egress" {
    for_each = var.egress_cidr_blocks

    content {
      description = "Approved HTTPS egress"
      from_port   = 443
      to_port     = 443
      protocol    = "tcp"
      cidr_blocks = [egress.value]
    }
  }
}

resource "aws_ecs_task_definition" "service" {
  for_each                 = local.services
  family                   = "${local.name_prefix}-${each.key}"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = tostring(each.value.cpu)
  memory                   = tostring(each.value.memory)
  execution_role_arn       = aws_iam_role.task_execution.arn
  task_role_arn            = aws_iam_role.task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  container_definitions = jsonencode([
    {
      name                   = each.key
      image                  = each.value.image
      essential              = true
      readonlyRootFilesystem = true
      user                   = "10001"
      portMappings = [
        for port in each.value.ports : {
          containerPort = port
          hostPort      = port
          protocol      = "tcp"
        }
      ]
      environment = [
        for key, value in each.value.env : {
          name  = key
          value = value
        }
      ]
      secrets = [
        for secret in each.value.secrets : {
          name      = secret.name
          valueFrom = secret.value_from
        }
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.service[each.key].name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "app"
        }
      }
    }
  ])
}

resource "aws_ecs_service" "service" {
  for_each               = local.services
  name                   = "${local.name_prefix}-${each.key}"
  cluster                = aws_ecs_cluster.main.id
  task_definition        = aws_ecs_task_definition.service[each.key].arn
  desired_count          = each.value.replicas
  launch_type            = "FARGATE"
  enable_execute_command = false
  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [aws_security_group.service.id]
    assign_public_ip = false
  }
}

resource "aws_security_group" "datastore" {
  for_each    = local.networked_datastores
  name        = "${local.name_prefix}-${each.key}"
  description = "Datastore access for ${each.key}"
  vpc_id      = var.vpc_id

  ingress {
    from_port       = local.datastore_ports[each.value.kind]
    to_port         = local.datastore_ports[each.value.kind]
    protocol        = "tcp"
    security_groups = [aws_security_group.service.id]
  }
}

resource "aws_db_subnet_group" "main" {
  count      = length(local.db_datastores) > 0 ? 1 : 0
  name       = "${local.name_prefix}-db"
  subnet_ids = var.private_subnet_ids
}

resource "random_password" "database" {
  for_each = local.db_datastores
  length   = 32
  special  = true
}

resource "aws_db_instance" "database" {
  for_each                  = local.db_datastores
  identifier                = "${local.name_prefix}-${each.key}"
  engine                    = each.value.kind
  engine_version            = each.value.version
  instance_class            = var.db_instance_class
  allocated_storage         = 20
  max_allocated_storage     = 100
  db_subnet_group_name      = aws_db_subnet_group.main[0].name
  vpc_security_group_ids    = [aws_security_group.datastore[each.key].id]
  username                  = "w2padmin"
  password                  = random_password.database[each.key].result
  db_name                   = replace(each.key, "-", "_")
  storage_encrypted         = true
  backup_retention_period   = var.environment == "prod" ? 35 : 7
  deletion_protection       = var.environment == "prod"
  skip_final_snapshot       = var.environment != "prod"
  multi_az                  = var.environment == "prod"
  publicly_accessible       = false
  auto_minor_version_upgrade = true
}

resource "aws_elasticache_subnet_group" "main" {
  count      = length(local.redis_datastores) > 0 ? 1 : 0
  name       = "${local.name_prefix}-redis"
  subnet_ids = var.private_subnet_ids
}

resource "random_password" "redis" {
  for_each = local.redis_datastores
  length   = 32
  special  = false
}

resource "aws_elasticache_replication_group" "redis" {
  for_each                   = local.redis_datastores
  replication_group_id       = "${local.name_prefix}-${each.key}"
  description                = "Redis datastore for ${each.key}"
  engine                     = "redis"
  engine_version             = coalesce(each.value.version, "7.1")
  node_type                  = var.cache_node_type
  num_cache_clusters         = var.environment == "prod" ? 2 : 1
  automatic_failover_enabled = var.environment == "prod"
  subnet_group_name          = aws_elasticache_subnet_group.main[0].name
  security_group_ids         = [aws_security_group.datastore[each.key].id]
  at_rest_encryption_enabled = true
  transit_encryption_enabled = true
  auth_token                 = random_password.redis[each.key].result
}

resource "aws_s3_bucket" "object_store" {
  for_each = local.s3_datastores
  bucket   = "${local.name_prefix}-${each.key}-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket_public_access_block" "object_store" {
  for_each                = aws_s3_bucket.object_store
  bucket                  = each.value.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "object_store" {
  for_each = aws_s3_bucket.object_store
  bucket   = each.value.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_versioning" "object_store" {
  for_each = aws_s3_bucket.object_store
  bucket   = each.value.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_sqs_queue" "queue" {
  for_each                  = local.queue_datastores
  name                      = "${local.name_prefix}-${each.key}"
  sqs_managed_sse_enabled   = true
  message_retention_seconds = 1209600
}
"""

_OUTPUTS_TF = """output "ecs_cluster_name" {
  value = aws_ecs_cluster.main.name
}

output "ecs_service_names" {
  value = {
    for key, value in aws_ecs_service.service : key => value.name
  }
}

output "rds_endpoints" {
  value = {
    for key, value in aws_db_instance.database : key => value.endpoint
  }
  sensitive = true
}

output "redis_primary_endpoints" {
  value = {
    for key, value in aws_elasticache_replication_group.redis : key => value.primary_endpoint_address
  }
  sensitive = true
}

output "s3_bucket_names" {
  value = {
    for key, value in aws_s3_bucket.object_store : key => value.bucket
  }
}

output "sqs_queue_urls" {
  value = {
    for key, value in aws_sqs_queue.queue : key => value.url
  }
}
"""

_AZURE_VERSIONS_TF = """terraform {
  required_version = ">= 1.6.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.110"
    }
  }
}

provider "azurerm" {
  features {}
}
"""

_AZURE_VARIABLES_TF = """variable "environment" {
  description = "Deployment environment."
  type        = string
  default     = "__ENVIRONMENT__"

  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "environment must be dev, staging, or prod."
  }
}

variable "azure_location" {
  description = "Azure location for generated infrastructure."
  type        = string
  default     = "__AZURE_LOCATION__"
}

variable "ingress_cidr_blocks" {
  description = "Approved CIDRs allowed to reach public services. Empty means no ingress."
  type        = list(string)
  default     = []
}

variable "egress_cidr_blocks" {
  description = "Approved CIDRs for outbound access. Empty means no internet egress."
  type        = list(string)
  default     = []
}
"""

_AZURE_MAIN_TF = """locals {
  project_name = "__PROJECT_NAME__"
  name_prefix  = "${local.project_name}-${var.environment}"

  services = jsondecode(<<SERVICES_JSON
__SERVICES_JSON__
SERVICES_JSON
  )

  datastores = jsondecode(<<DATASTORES_JSON
__DATASTORES_JSON__
DATASTORES_JSON
  )
}

resource "azurerm_resource_group" "main" {
  name     = "${local.name_prefix}-rg"
  location = var.azure_location
}

resource "azurerm_virtual_network" "main" {
  name                = "${local.name_prefix}-vnet"
  address_space       = ["10.42.0.0/16"]
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
}

resource "azurerm_subnet" "workloads" {
  name                 = "workloads"
  resource_group_name  = azurerm_resource_group.main.name
  virtual_network_name = azurerm_virtual_network.main.name
  address_prefixes     = ["10.42.1.0/24"]
}

resource "azurerm_network_security_group" "workloads" {
  name                = "${local.name_prefix}-workloads-nsg"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name

  security_rule {
    name                       = "deny-internet-ingress"
    priority                   = 4096
    direction                  = "Inbound"
    access                     = "Deny"
    protocol                   = "*"
    source_port_range          = "*"
    destination_port_range     = "*"
    source_address_prefix      = "Internet"
    destination_address_prefix = "*"
  }
}

resource "azurerm_subnet_network_security_group_association" "workloads" {
  subnet_id                 = azurerm_subnet.workloads.id
  network_security_group_id = azurerm_network_security_group.workloads.id
}

resource "azurerm_log_analytics_workspace" "main" {
  name                = "${local.name_prefix}-logs"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  sku                 = "PerGB2018"
  retention_in_days   = var.environment == "prod" ? 30 : 14
}

resource "azurerm_container_app_environment" "main" {
  name                       = "${local.name_prefix}-apps"
  location                   = azurerm_resource_group.main.location
  resource_group_name        = azurerm_resource_group.main.name
  log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id
}

# Services and datastores are captured in locals for provider-specific module expansion.
# local.services and local.datastores are intentionally generated from the topology contract.
"""

_AZURE_OUTPUTS_TF = """output "resource_group_name" {
  value = azurerm_resource_group.main.name
}

output "container_app_environment_id" {
  value = azurerm_container_app_environment.main.id
}
"""

_GCP_VERSIONS_TF = """terraform {
  required_version = ">= 1.6.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.45"
    }
  }
}

provider "google" {
  project = var.gcp_project_id
  region  = var.gcp_region
}
"""

_GCP_VARIABLES_TF = """variable "environment" {
  description = "Deployment environment."
  type        = string
  default     = "__ENVIRONMENT__"

  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "environment must be dev, staging, or prod."
  }
}

variable "gcp_project_id" {
  description = "Google Cloud project ID."
  type        = string
}

variable "gcp_region" {
  description = "Google Cloud region for generated infrastructure."
  type        = string
  default     = "__GCP_REGION__"
}

variable "ingress_cidr_blocks" {
  description = "Approved CIDRs allowed to reach public services. Empty means no ingress."
  type        = list(string)
  default     = []
}

variable "egress_cidr_blocks" {
  description = "Approved CIDRs for outbound access. Empty means no internet egress."
  type        = list(string)
  default     = []
}
"""

_GCP_MAIN_TF = """locals {
  project_name = "__PROJECT_NAME__"
  name_prefix  = "${local.project_name}-${var.environment}"

  services = jsondecode(<<SERVICES_JSON
__SERVICES_JSON__
SERVICES_JSON
  )

  datastores = jsondecode(<<DATASTORES_JSON
__DATASTORES_JSON__
DATASTORES_JSON
  )
}

resource "google_compute_network" "main" {
  name                    = "${local.name_prefix}-vpc"
  auto_create_subnetworks = false
}

resource "google_compute_subnetwork" "workloads" {
  name          = "${local.name_prefix}-workloads"
  ip_cidr_range = "10.42.1.0/24"
  network       = google_compute_network.main.id
  region        = var.gcp_region
}

resource "google_compute_firewall" "deny_ingress" {
  name      = "${local.name_prefix}-deny-ingress"
  network   = google_compute_network.main.name
  direction = "INGRESS"
  priority  = 65534

  deny {
    protocol = "all"
  }
}

resource "google_artifact_registry_repository" "services" {
  repository_id = "${local.name_prefix}-services"
  location      = var.gcp_region
  format        = "DOCKER"
}

# Services and datastores are captured in locals for provider-specific module expansion.
# local.services and local.datastores are intentionally generated from the topology contract.
"""

_GCP_OUTPUTS_TF = """output "network_name" {
  value = google_compute_network.main.name
}

output "artifact_registry_repository" {
  value = google_artifact_registry_repository.services.name
}
"""
