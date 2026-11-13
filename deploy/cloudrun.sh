#!/usr/bin/env bash
# Deploy to Cloud Run with Gemini on Vertex AI.
# Usage: PROJECT=my-project REGION=asia-south1 ./deploy/cloudrun.sh
set -euo pipefail
: "${PROJECT:?set PROJECT}"
REGION="${REGION:-asia-south1}"
MODEL="${MODEL:-gemini-2.5-flash}"
SA="incident-responder@${PROJECT}.iam.gserviceaccount.com"

gcloud services enable run.googleapis.com aiplatform.googleapis.com cloudbuild.googleapis.com --project "$PROJECT"

gcloud iam service-accounts describe "$SA" --project "$PROJECT" >/dev/null 2>&1 || \
  gcloud iam service-accounts create incident-responder --project "$PROJECT" \
    --display-name "Incident responder agent"

# Least privilege: the service only needs to call Vertex AI models.
gcloud projects add-iam-policy-binding "$PROJECT" \
  --member "serviceAccount:${SA}" --role roles/aiplatform.user --condition None >/dev/null

# --no-allow-unauthenticated: callers need an identity token (roles/run.invoker).
gcloud run deploy incident-responder --source . --project "$PROJECT" --region "$REGION" \
  --service-account "$SA" --no-allow-unauthenticated \
  --set-env-vars "GOOGLE_GENAI_USE_VERTEXAI=TRUE,GOOGLE_CLOUD_PROJECT=${PROJECT},GOOGLE_CLOUD_LOCATION=${REGION},MODEL=${MODEL}"
