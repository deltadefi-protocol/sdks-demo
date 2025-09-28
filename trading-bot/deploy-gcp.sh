#!/bin/bash

# Google Cloud Run Deployment Script for Trading Bot
# Usage: ./deploy-gcp.sh [PROJECT_ID] [REGION] [SERVICE_NAME]

set -e

# Load configuration from .env if available
if [ -f ".env" ]; then
    while IFS= read -r line; do
        # Skip empty lines and comments
        [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
        # Remove inline comments and export
        line=$(echo "$line" | sed 's/#.*$//')
        [[ -n "$line" ]] && export "$line"
    done < .env
fi

# Configuration (command line args override .env)
PROJECT_ID=${1:-${GCP_PROJECT_ID:-"your-gcp-project-id"}}
REGION=${2:-${GCP_REGION:-"us-central1"}}
SERVICE_NAME=${3:-${GCP_SERVICE_NAME:-"deltadefi-trading-bot"}}
IMAGE_NAME="$REGION-docker.pkg.dev/$PROJECT_ID/trading-bot-repo/$SERVICE_NAME:latest"

# Validate configuration AFTER variables are set
if [ -z "$PROJECT_ID" ] || [ "$PROJECT_ID" == "your-gcp-project-id" ]; then
    echo "❌ Please set GCP_PROJECT_ID in .env or provide as argument"
    echo "Usage: ./deploy-gcp.sh [PROJECT_ID] [REGION] [SERVICE_NAME]"
    exit 1
fi

echo "🚀 Deploying Trading Bot to Google Cloud Run"
echo "Project: $PROJECT_ID"
echo "Region: $REGION"
echo "Service: $SERVICE_NAME"
echo "Image: $IMAGE_NAME"

# Deploy to Cloud Run
echo "🚀 Deploying to Cloud Run..."
# Check if service exists
if gcloud run services describe $SERVICE_NAME --region $REGION --quiet >/dev/null 2>&1; then
  echo "🔄 Updating existing service..."
  gcloud run deploy $SERVICE_NAME \
    --image $IMAGE_NAME \
    --platform managed \
    --region $REGION \
    --allow-unauthenticated \
    --memory 1Gi \
    --cpu 1 \
    --concurrency 1 \
    --max-instances 1 \
    --min-instances 0 \
    --timeout 3600 \
    --env-vars-file .env \
    --port 8080 \
    --no-cpu-throttling \
    --execution-environment gen2 \
    --no-traffic
else
  echo "🆕 Creating new service..."
  gcloud run deploy $SERVICE_NAME \
    --image $IMAGE_NAME \
    --platform managed \
    --region $REGION \
    --allow-unauthenticated \
    --memory 1Gi \
    --cpu 1 \
    --concurrency 1 \
    --max-instances 1 \
    --min-instances 0 \
    --timeout 3600 \
    --env-vars-file .env \
    --port 8080 \
    --no-cpu-throttling \
    --execution-environment gen2
fi

echo "✅ Deployment completed!"

# Only update traffic if we used --no-traffic (existing service)
if gcloud run services describe $SERVICE_NAME --region $REGION --quiet >/dev/null 2>&1; then
  echo "📝 Activating the service..."
  gcloud run services update-traffic $SERVICE_NAME --region $REGION --to-latest
fi

echo "🎉 Trading bot deployed and activated!"
echo ""
echo "📊 Useful commands:"
echo "   View logs: gcloud run logs read --service $SERVICE_NAME --region $REGION --follow"
echo "   Get URL: gcloud run services describe $SERVICE_NAME --region $REGION --format 'value(status.url)'"
echo "   Service status: gcloud run services list --region $REGION"
