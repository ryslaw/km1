locals {
  services = {
    "user-service" = {
      port      = 8001
      extra_env = []
    }
    "product-service" = {
      port      = 8002
      extra_env = []
    }
    "order-service" = {
      port = 8003
      extra_env = [
        "USER_SERVICE_URL=http://user-service:8000",
        "PRODUCT_SERVICE_URL=http://product-service:8000",
      ]
    }
  }
}
