variable "aws_region" {
  description = "AWS region for the target environment."
  type        = string
  default     = "ap-south-1"
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
  description = "Throwaway local AWS-compatible access key. Do not use a real AWS key."
  type        = string
  default     = "test"
  sensitive   = true
}

variable "local_aws_secret_key" {
  description = "Throwaway local AWS-compatible secret key. Do not use a real AWS key."
  type        = string
  default     = "test"
  sensitive   = true
}
