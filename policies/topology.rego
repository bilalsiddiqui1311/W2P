package w2p.topology

deny[msg] {
  service := input.services[_]
  not regex.match("(:[^/:]+$)|(@sha256:)", service.image)
  msg := sprintf("service %s does not use a pinned image tag or digest", [service.id])
}

deny[msg] {
  service := input.services[_]
  endswith(service.image, ":latest")
  msg := sprintf("service %s uses a mutable latest image tag", [service.id])
}

deny[msg] {
  service := input.services[_]
  service.security.public
  not service.security.require_auth
  msg := sprintf("public service %s does not require authentication", [service.id])
}

deny[msg] {
  service := input.services[_]
  service.security.public
  not service.security.tls_required
  msg := sprintf("public service %s does not require TLS", [service.id])
}

deny[msg] {
  service := input.services[_]
  service.security.public
  count(service.ports) == 0
  msg := sprintf("public service %s does not declare a port", [service.id])
}

deny[msg] {
  datastore := input.datastores[_]
  datastore.public_access
  msg := sprintf("datastore %s allows public access", [datastore.id])
}

deny[msg] {
  edge := input.edges[_]
  edge.protocol == "http"
  msg := sprintf("edge %s uses plaintext HTTP", [edge.id])
}
