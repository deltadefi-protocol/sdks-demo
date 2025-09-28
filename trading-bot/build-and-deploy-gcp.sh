#!/bin/bash

# Build and Deploy Trading Bot to Google Cloud Run
# Usage: ./build-and-deploy-gcp.sh [PROJECT_ID] [REGION] [SERVICE_NAME]

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

# Use Artifact Registry paths
LOCAL_IMAGE="deltadefi-trading-bot:latest"
ARTIFACT_REGISTRY_IMAGE="$REGION-docker.pkg.dev/$PROJECT_ID/trading-bot-repo/$SERVICE_NAME:latest"

# Validate configuration AFTER variables are set
if [ -z "$PROJECT_ID" ] || [ "$PROJECT_ID" == "your-gcp-project-id" ]; then
    echo "❌ Please set GCP_PROJECT_ID in .env or provide as argument"
    echo "Usage: ./build-and-deploy-gcp.sh [PROJECT_ID] [REGION] [SERVICE_NAME]"
    exit 1
fi

echo "🚀 Building and Deploying Trading Bot to Google Cloud Run"
echo "Project: $PROJECT_ID"
echo "Region: $REGION"
echo "Service: $SERVICE_NAME"
echo "Local Image: $LOCAL_IMAGE"
echo "Artifact Registry Image: $ARTIFACT_REGISTRY_IMAGE"

# Check if docker is installed
if ! command -v docker &> /dev/null; then
    echo "❌ Docker is not installed. Please install it first."
    exit 1
fi

# Check if gcloud is installed
if ! command -v gcloud &> /dev/null; then
    echo "❌ gcloud CLI is not installed. Please install it first."
    echo "https://cloud.google.com/sdk/docs/install"
    exit 1
fi

# Set the project
echo "📋 Setting GCP project..."
gcloud config set project $PROJECT_ID

# Configure Docker authentication for Artifact Registry
echo "🔐 Configuring Docker authentication..."
gcloud auth configure-docker $REGION-docker.pkg.dev

# Step 1: Local Docker build
echo "🔨 Building Docker image locally..."
docker build --platform linux/amd64 -t $LOCAL_IMAGE . --no-cache

# Step 2: Tag for Artifact Registry
echo "🏷️ Tagging image for Artifact Registry..."
docker tag $LOCAL_IMAGE $ARTIFACT_REGISTRY_IMAGE

# Step 3: Push to Artifact Registry
echo "📤 Pushing image to Artifact Registry..."
docker push $ARTIFACT_REGISTRY_IMAGE

# Step 4: Deploy to Cloud Run (using your working deploy-gcp.sh logic)
echo "🚀 Deploying to Cloud Run..."

# Check if service exists
if gcloud run services describe $SERVICE_NAME --region $REGION --quiet >/dev/null 2>&1; then
  echo "🔄 Updating existing service..."
  gcloud run deploy $SERVICE_NAME \
    --image $ARTIFACT_REGISTRY_IMAGE \
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
    --image $ARTIFACT_REGISTRY_IMAGE \
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

echo "🎉 Trading bot built and deployed successfully!"
echo ""
echo "📊 Useful commands:"
echo "   View logs: gcloud run logs read --service $SERVICE_NAME --region $REGION --follow"
echo "   Get URL: gcloud run services describe $SERVICE_NAME --region $REGION --format 'value(status.url)'"
echo "   Service status: gcloud run services list --region $REGION"
echo ""
echo "🐳 Docker commands used:"
echo "   Local image: $LOCAL_IMAGE"
echo "   Registry image: $ARTIFACT_REGISTRY_IMAGE"