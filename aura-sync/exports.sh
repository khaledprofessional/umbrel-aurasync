# Sourced by umbrelOS before every app lifecycle operation.
# Change the owner here after forking if the GitHub Actions workflow publishes
# images under your own GitHub Container Registry namespace.
export APP_AURA_SYNC_IMAGE_OWNER="khaledprofessional"
export APP_AURA_SYNC_IMAGE_TAG="1.0.2"

# Stable per-install secret used to authenticate webhook calls. External
# services authenticate with: Authorization: Bearer <token>
export APP_AURA_SYNC_WEBHOOK_TOKEN="$(derive_entropy "${app_entropy_identifier}-webhook-token")"
