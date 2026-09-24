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

# --- user-service-db (Postgres) ---

resource "docker_volume" "user_service_db_data" {
  name = "user-service-db-data"
}

resource "docker_container" "user_service_db" {
  name  = "user-service-db"
  image = docker_image.service_db.image_id

  networks_advanced {
    name = docker_network.km1.name
  }

  env = [
    "POSTGRES_USER=${var.postgres_user}",
    "POSTGRES_PASSWORD=${var.postgres_password}",
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
    "DATABASE_URL=postgresql://${var.postgres_user}:${var.postgres_password}@user-service-db:5432/user-service-db",
  ]

  depends_on = [docker_container.user_service_db]
}

# --- product-service-db (Postgres) ---

resource "docker_volume" "product_service_db_data" {
  name = "product-service-db-data"
}

resource "docker_container" "product_service_db" {
  name  = "product-service-db"
  image = docker_image.service_db.image_id

  networks_advanced {
    name = docker_network.km1.name
  }

  env = [
    "POSTGRES_USER=${var.postgres_user}",
    "POSTGRES_PASSWORD=${var.postgres_password}",
    "POSTGRES_DB=product-service-db",
    "PGDATA=/var/lib/postgresql/data/pgdata",
  ]

  volumes {
    volume_name    = docker_volume.product_service_db_data.name
    container_path = "/var/lib/postgresql/data"
  }
}

# --- product-service (app) ---

resource "docker_image" "product_service" {
  name = "km1/product-service:local"

  build {
    context = "${path.module}/../services/product-service"
  }
}

resource "docker_container" "product_service" {
  name  = "product-service"
  image = docker_image.product_service.image_id

  networks_advanced {
    name = docker_network.km1.name
  }

  ports {
    internal = 8000
    external = 8002
  }

  env = [
    "DATABASE_URL=postgresql://${var.postgres_user}:${var.postgres_password}@product-service-db:5432/product-service-db",
  ]

  depends_on = [docker_container.product_service_db]
}

# --- order-service-db (Postgres) ---

resource "docker_volume" "order_service_db_data" {
  name = "order-service-db-data"
}

resource "docker_container" "order_service_db" {
  name  = "order-service-db"
  image = docker_image.service_db.image_id

  networks_advanced {
    name = docker_network.km1.name
  }

  env = [
    "POSTGRES_USER=${var.postgres_user}",
    "POSTGRES_PASSWORD=${var.postgres_password}",
    "POSTGRES_DB=order-service-db",
    "PGDATA=/var/lib/postgresql/data/pgdata",
  ]

  volumes {
    volume_name    = docker_volume.order_service_db_data.name
    container_path = "/var/lib/postgresql/data"
  }
}

# --- order-service (app) ---

resource "docker_image" "order_service" {
  name = "km1/order-service:local"

  build {
    context = "${path.module}/../services/order-service"
  }
}

resource "docker_container" "order_service" {
  name  = "order-service"
  image = docker_image.order_service.image_id

  networks_advanced {
    name = docker_network.km1.name
  }

  ports {
    internal = 8000
    external = 8003
  }

  env = [
    "DATABASE_URL=postgresql://${var.postgres_user}:${var.postgres_password}@order-service-db:5432/order-service-db",
    "USER_SERVICE_URL=http://user-service:8000",
    "PRODUCT_SERVICE_URL=http://product-service:8000",
  ]

  depends_on = [docker_container.order_service_db, docker_container.user_service, docker_container.product_service]
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
