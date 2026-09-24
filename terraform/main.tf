terraform {
  required_providers {
    docker = {
      source  = "kreuzwerker/docker"
      version = "~> 3.0"
    }
  }
}

provider "docker" {}

resource "docker_network" "km1" {
  name = "km1-network"
}

resource "docker_image" "service_db" {
  name = "postgres:18.6"
}

# --- db ---
resource "docker_volume" "service_db_data" {
  for_each = local.services
  name     = "${each.key}-db-data"
}

resource "docker_container" "service_db" {
  for_each = local.services
  name     = "${each.key}-db"
  image    = docker_image.service_db.image_id

  networks_advanced {
    name = docker_network.km1.name
  }

  env = [
    "POSTGRES_USER=${var.postgres_user}",
    "POSTGRES_PASSWORD=${var.postgres_password}",
    "POSTGRES_DB=${each.key}-db",
    "PGDATA=/var/lib/postgresql/data/pgdata",
  ]

  volumes {
    volume_name    = docker_volume.service_db_data[each.key].name
    container_path = "/var/lib/postgresql/data"
  }
}

# --- app ---
resource "docker_image" "service" {
  for_each = local.services
  name     = "km1/${each.key}:local"

  build {
    context = "${path.module}/../services/${each.key}"
  }
}

resource "docker_container" "service" {
  for_each = local.services
  name     = each.key
  image    = docker_image.service[each.key].image_id

  networks_advanced {
    name = docker_network.km1.name
  }

  ports {
    internal = 8000
    external = each.value.port
  }

  env = concat(
    ["DATABASE_URL=postgresql://${var.postgres_user}:${var.postgres_password}@${docker_container.service_db[each.key].name}:5432/${each.key}-db"],
    each.value.extra_env
  )
}

# --- status-page ---

resource "docker_image" "status_page" {
  name = "km1/status-page:local"

  build {
    context = "${path.module}/../services/status-page"
  }
}

resource "docker_container" "status_page" {
  name  = "status-page"
  image = docker_image.status_page.image_id

  networks_advanced {
    name = docker_network.km1.name
  }

  ports {
    internal = 8000
    external = 8000
  }
}
