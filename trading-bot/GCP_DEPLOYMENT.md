# Google Cloud Run Deployment Guide

## Prerequisites

1. **Google Cloud SDK**: Install `gcloud` CLI

   ```bash
   # macOS
   brew install google-cloud-sdk

   # Or download from: https://cloud.google.com/sdk/docs/install
   ```

2. **Docker**: Ensure Docker is installed and running

   ```bash
   # macOS
   brew install docker
   # Or download Docker Desktop from: https://docker.com/products/docker-desktop
   ```

3. **Authenticate with GCP**:
   ```bash
   gcloud auth login
   gcloud auth configure-docker
   ```

## Recommended: One-Command Build and Deploy

The easiest way to deploy is using the automated build and deploy script:

```bash
./build-and-deploy-gcp.sh
```

This script will:

1. ✅ Read configuration from your `.env` file
2. ✅ Build the Docker image locally with correct platform (linux/amd64)
3. ✅ Set up Artifact Registry authentication
4. ✅ Push the image to GCP Artifact Registry
5. ✅ Deploy to Cloud Run with optimized settings
6. ✅ Activate the service

### With Custom Parameters

```bash
./build-and-deploy-gcp.sh YOUR_PROJECT_ID YOUR_GCP_REGION YOUR_SERVICE_NAME
```

## Alternative: Manual Deployment

If you prefer manual control over the deployment process:

### Option 1: Using deploy-gcp.sh (requires pre-built image)

```bash
./deploy-gcp.sh YOUR_PROJECT_ID YOUR_GCP_REGION YOUR_SERVICE_NAME
```

### Option 2: Step-by-Step Manual Process

1. **Build and push image manually**:

   ```bash
   # Build for Cloud Run platform
   docker build --platform linux/amd64 -t deltadefi-trading-bot:latest . --no-cache

   # Tag for Artifact Registry
   docker tag deltadefi-trading-bot:latest \
     us-central1-docker.pkg.dev/YOUR_PROJECT_ID/trading-bot-repo/deltadefi-trading-bot:latest

   # Configure authentication
   gcloud auth configure-docker us-central1-docker.pkg.dev

   # Push to registry
   docker push us-central1-docker.pkg.dev/YOUR_PROJECT_ID/trading-bot-repo/deltadefi-trading-bot:latest
   ```

2. **Deploy to Cloud Run**:
   ```bash
   gcloud run deploy trading-bot \
     --image us-central1-docker.pkg.dev/YOUR_PROJECT_ID/trading-bot-repo/deltadefi-trading-bot:latest \
     --region us-central1 \
     --env-vars-file .env \
     --port 8080 \
     --memory 1Gi \
     --cpu 1 \
     --max-instances 1 \
     --timeout 3600 \
     --env-vars-file .env \
     --port 8080 \
     --no-cpu-throttling \
     --execution-environment gen2 \
     --no-traffic
   ```

## Environment Variables

Your `.env` file should contain:

- `EXCHANGE__DELTADEFI_API_KEY`: Your DeltaDeFi API key
- `EXCHANGE__TRADING_PASSWORD`: Your trading password
- `SYSTEM__MODE`: Set to `testnet` or `mainnet`
- `GCP_PROJECT_ID`: Your GCP project ID
- `GCP_REGION`: Your preferred region (e.g., `us-central1`)
- `GCP_SERVICE_NAME`: Service name (e.g., `trading-bot`)

## Monitoring

```bash
# View logs
gcloud run logs read --service trading-bot --region us-central1 --follow

# Check service status
gcloud run services describe trading-bot --region us-central1

# View metrics in GCP Console
https://console.cloud.google.com/run
```

## Configuration

The bot uses these Cloud Run settings:

- **Memory**: 1GB
- **CPU**: 1 vCPU
- **Concurrency**: 1 (single instance)
- **Timeout**: 1 hour
- **Auto-scaling**: 0-1 instances

## Troubleshooting

### Common Issues

1. **"Default STARTUP TCP probe failed" Error**:

   - This was fixed in the latest version with the Cloud Run optimized entry point
   - The health server now starts immediately to satisfy Cloud Run's startup probe
   - Make sure you're using the latest Docker image

2. **Container exits immediately**:

   ```bash
   # Check logs for specific error messages
   gcloud run logs read --service trading-bot --region us-central1 --limit 50
   ```

3. **API connection issues**:

   - Verify your `.env` file has correct values for `EXCHANGE__DELTADEFI_API_KEY` and `EXCHANGE__TRADING_PASSWORD`
   - Check if the trading bot can connect to DeltaDeFi testnet/mainnet

4. **Memory issues**:

   - Increase memory allocation in deployment scripts
   - Monitor memory usage in Cloud Run console

5. **SSL/Certificate errors**:
   - Usually resolved by the Docker image's certificate setup
   - Check container logs for specific SSL errors

### Health Check

Test if your deployment is working:

```bash
# Get service URL
SERVICE_URL=$(gcloud run services describe trading-bot --region us-central1 --format 'value(status.url)')

# Test health endpoint
curl $SERVICE_URL/health

# Should return JSON with service status
```

## Cost Optimization

- Service scales to zero when not active
- Only pay for actual usage
- Estimated cost: $5-20/month for continuous trading

## Security

- Environment variables are encrypted at rest
- Service runs in Google's secure container environment
- No public HTTP endpoint needed (bot runs as background service)
