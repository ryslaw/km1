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

# --- user-service-db (Postgres) ---

resource "docker_volume" "user_service_db_data" {
  name = "user-service-db-data"
}

resource "docker_image" "user_service_db" {
  name = "postgres:18.6"
}

resource "docker_container" "user_service_db" {
  name  = "user-service-db"
  image = docker_image.user_service_db.image_id

  networks_advanced {
    name = docker_network.km1.name
  }

  env = [
    "POSTGRES_USER=admin",        # TODO: move to variable
    "POSTGRES_PASSWORD=password", # TODO: move to variable
    "POSTGRES_DB=user-service-db",
    "PGDATA=/var/lib/postgresql/data/pgdata",
  ]

  volumes {
    volume_name    = docker_volume.user_service_db_data.name
    container_path = "/var/lib/postgresql/data"
  }
}

# --- user-service (app) ---

resource "docker_image" "user_service" {
  name = "km1/user-service:local"

  build {
    context = "${path.module}/../services/user-service"
  }
}

resource "docker_container" "user_service" {
  name  = "user-service"
  image = docker_image.user_service.image_id

  networks_advanced {
    name = docker_network.km1.name
  }

  ports {
    internal = 8000
    external = 8001
  }

  env = [
    "DATABASE_URL=postgresql://admin:password@user-service-db:5432/user-service-db",
  ]

  depends_on = [docker_container.user_service_db]
}
