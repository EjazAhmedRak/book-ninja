# Values are populated outside Terraform to keep application secrets out of state.
resource "aws_secretsmanager_secret" "backend" {
  name                    = "${var.project_name}/${var.environment}/backend"
  description             = "Backend runtime JSON; populate separately before application deployment"
  recovery_window_in_days = 7
  tags                    = local.common_tags
}
