provider "google" {
  project = "your-gcp-project-id"
  region  = "us-central1"
  zone    = "us-central1-a"
}

resource "google_compute_network" "vpc_network" {
  name = "yantrix-scout-network"
}

resource "google_compute_firewall" "allow_http_https_8000" {
  name    = "yantrix-scout-allow-web"
  network = google_compute_network.vpc_network.name

  allow {
    protocol = "tcp"
    ports    = ["22", "80", "443", "8000"]
  }

  source_ranges = ["0.0.0.0/0"]
  target_tags   = ["client-scout"]
}

resource "google_compute_instance" "scout_vm" {
  name         = "yantrix-client-scout"
  machine_type = "e2-medium"
  tags         = ["client-scout"]

  boot_disk {
    initialize_params {
      image = "ubuntu-os-cloud/ubuntu-2404-lts-amd64"
      size  = 30
      type  = "pd-balanced"
    }
  }

  network_interface {
    network = google_compute_network.vpc_network.name
    access_config {
      # Ephemeral public IP
    }
  }

  metadata = {
    ssh-keys = "ubuntu:${file("~/.ssh/id_rsa.pub")}"
  }
}

output "public_ip" {
  value = google_compute_instance.scout_vm.network_interface[0].access_config[0].nat_ip
}
