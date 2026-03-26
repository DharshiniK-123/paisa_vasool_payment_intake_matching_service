#!/bin/bash
set -e

# Load environment variables from .env file
if [ -f .env ]; then
  set -a
  source .env
  set +a
fi

# Define common project variables
PROJECT_ID="gwx-internship-01"
REGION="us-east1"
SERVICE_NAME="paisavasool-paymentmatching-service"
WORKER_SERVICE_NAME="paisavasool-rq-worker"
GAR_REPO="us-east1-docker.pkg.dev/$PROJECT_ID/gwx-gar-intern-01"
IMAGE="$GAR_REPO/paisavasool-paymentmatching-service:latest"
WORKER_IMAGE="$GAR_REPO/paisavasool-rq-worker:latest"
CONN_NAME="gwx-internship-01:us-east1:gwx-csql-intern-01"



# Database settings
DB_NAME="paisa_vasool_db"
DB_HOST="34.23.138.181"
DB_PORT=5432
DATABASE_URL="postgresql+asyncpg://$DB_USER:$DB_PASSWORD@/$DB_NAME?host=/cloudsql/$CONN_NAME"
WORKER_DATABASE_URL="postgresql+asyncpg://$DB_USER:$DB_PASSWORD@/$DB_NAME?host=/cloudsql/$CONN_NAME"

# Infrastructure settings
REDIS_HOST="10.125.46.155"
REDIS_PORT="6379"
REDIS_URL="redis://$REDIS_HOST:$REDIS_PORT"
GCS_BUCKET="gwx-stg-intern-01"
GCS_FOLDER="paisavasool"

# Mail settings
MAIL_FROM="$MAIL_USERNAME"
MAIL_SERVER="smtp.gmail.com"
MAIL_PORT="587"
MAIL_STARTTLS="True"
MAIL_SSL_TLS="False"

# Worker settings
WORKER_SERVICE_URL="https://paisavasool-rq-worker-717740758627.us-east1.run.app"

ENV_VARS="DATABASE_URL=$DATABASE_URL,REDIS_HOST=$REDIS_HOST,REDIS_PORT=$REDIS_PORT,REDIS_URL=$REDIS_URL,GCS_BUCKET=$GCS_BUCKET,GCS_FOLDER=$GCS_FOLDER,GROQ_API_KEY=$GROQ_API_KEY,GOOGLE_API_KEY=$GOOGLE_API_KEY,MAIL_USERNAME=$MAIL_USERNAME,MAIL_PASSWORD=$MAIL_PASSWORD,MAIL_FROM=$MAIL_FROM,MAIL_SERVER=$MAIL_SERVER,MAIL_PORT=$MAIL_PORT,MAIL_STARTTLS=$MAIL_STARTTLS,MAIL_SSL_TLS=$MAIL_SSL_TLS,WORKER_SERVICE_URL=$WORKER_SERVICE_URL"

WORKER_ENV_VARS="DATABASE_URL=$WORKER_DATABASE_URL,REDIS_HOST=$REDIS_HOST,REDIS_PORT=$REDIS_PORT,REDIS_URL=$REDIS_URL,GCS_BUCKET=$GCS_BUCKET,GCS_FOLDER=$GCS_FOLDER,GROQ_API_KEY=$GROQ_API_KEY,GOOGLE_API_KEY=$GOOGLE_API_KEY,MAIL_USERNAME=$MAIL_USERNAME,MAIL_PASSWORD=$MAIL_PASSWORD,MAIL_FROM=$MAIL_FROM,MAIL_SERVER=$MAIL_SERVER,MAIL_PORT=$MAIL_PORT,MAIL_STARTTLS=$MAIL_STARTTLS,MAIL_SSL_TLS=$MAIL_SSL_TLS"


echo "Building Backend..."
docker build -t "$IMAGE" .
docker push "$IMAGE"

echo "Deploying Backend..."
gcloud run deploy "$SERVICE_NAME" \
  --image="$IMAGE" \
  --region="$REGION" \
  --project="$PROJECT_ID" \
  --allow-unauthenticated \
  --platform=managed \
  --min-instances=0 \
  --max-instances=2 \
  --min=0 \
  --max=2 \
  --service-account="gwx-cloudrun-sa-01@$PROJECT_ID.iam.gserviceaccount.com" \
  --add-cloudsql-instances="$CONN_NAME" \
  --network="gwx-vpc-intern-01" \
  --subnet="gwx-sne-intern-01" \
  --vpc-egress=private-ranges-only \
  --set-env-vars="$ENV_VARS"

echo "Backend deployed"

echo "Building Worker..."
docker build -f Dockerfile.worker -t "$WORKER_IMAGE" .
docker push "$WORKER_IMAGE"

echo "Deploying Worker Service..."
gcloud run deploy "$WORKER_SERVICE_NAME" \
  --image="$WORKER_IMAGE" \
  --region="$REGION" \
  --project="$PROJECT_ID" \
  --allow-unauthenticated \
  --platform=managed \
  --min-instances=0 \
  --max-instances=2 \
  --min=0 \
  --max=2 \
  --service-account="gwx-cloudrun-sa-01@$PROJECT_ID.iam.gserviceaccount.com" \
  --add-cloudsql-instances="$CONN_NAME" \
  --network="gwx-vpc-intern-01" \
  --subnet="gwx-sne-intern-01" \
  --vpc-egress=private-ranges-only \
  --set-env-vars="$WORKER_ENV_VARS"

echo "Worker service deployed"
echo "All deployed!"
echo "If this is first deploy, get worker URL from GCP Console"
echo "and update WORKER_SERVICE_URL in deploy.sh then redeploy backend"