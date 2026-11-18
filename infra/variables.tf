variable "aws_region" {
  description = "AWS region for the target environment."
  type        = string
  default     = "ap-south-1"
}

variable "local_provisioning_access_key" {
  description = "Local Floci provisioning identity; independent of backend credentials."
  type        = string
  default     = null
  sensitive   = true
}

variable "local_provisioning_secret_key" {
  description = "Secret for the local provisioning identity."
  type        = string
  default     = null
  sensitive   = true
}

variable "vpc_cidr" {
  description = "IPv4 VPC range. Four subnet bits are reserved for each subnet."
  type        = string
  default     = "10.60.0.0/16"

  validation {
    condition     = can(cidrnetmask(var.vpc_cidr)) && can(regex("/(16|17|18|19|20)$", var.vpc_cidr))
    error_message = "vpc_cidr must be an IPv4 CIDR with a /16 through /20 prefix."
  }
}

variable "availability_zones" {
  description = "Two distinct AZs in aws_region; defaults to the region's a and b zones."
  type        = list(string)
  default     = []

  validation {
    condition     = length(var.availability_zones) == 0 || (length(var.availability_zones) == 2 && length(distinct(var.availability_zones)) == 2)
    error_message = "Provide exactly two distinct availability zones, or leave empty."
  }
}

variable "environment" {
  description = "Deployment environment name."
  type        = string

  validation {
    condition     = contains(["local", "dev", "prod"], var.environment)
    error_message = "environment must be one of: local, dev, prod."
  }
}

variable "project_name" {
  description = "Short, DNS-safe project name used by future infrastructure resources."
  type        = string
  default     = "book-ninja"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,30}$", var.project_name))
    error_message = "project_name must be 2-31 lowercase letters, numbers, or hyphens and start with a letter."
  }
}

variable "local_validation" {
  description = "Enable only for local Floci validation; never enable this in AWS environments."
  type        = bool
  default     = false
}

variable "floci_endpoint" {
  description = "Floci's AWS-compatible endpoint, used only when local_validation is true."
  type        = string
  default     = "http://localhost:4566"

  validation {
    condition     = can(regex("^https?://", var.floci_endpoint))
    error_message = "floci_endpoint must start with http:// or https://."
  }
}

variable "local_aws_access_key" {
  description = "Local Floci IAM access key. Do not use a real AWS key."
  type        = string
  default     = null
  sensitive   = true
}

variable "local_aws_secret_key" {
  description = "Local Floci IAM secret key. Do not use a real AWS key."
  type        = string
  default     = null
  sensitive   = true
}
