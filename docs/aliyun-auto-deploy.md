# Aliyun auto deploy

This project supports two deployment modes.

## Mode A: ECS local build, no ACR

This is the simplest mode for a single ECS. Because ECS may not be able to access GitHub reliably, Flow uploads the checked-out code to ECS and then builds locally:

```text
git push -> Aliyun Flow -> upload source archive to ECS -> docker compose build/up
```

On ECS, prepare `/opt/newquant/backend.env`.

Use this command in Aliyun Flow deploy step:

```bash
ssh root@39.97.43.118 'APP_DIR=/opt/newquant REPO_DIR=/root/newQuant REPO_URL=https://github.com/Jesse0722/newQuant.git BRANCH=master bash /opt/newquant/deploy-local-build.sh'
```

If ECS cannot access GitHub reliably, use Flow to upload the checked-out code instead:

```bash
ECS_HOST=39.97.43.118 ECS_USER=root APP_DIR=/opt/newquant bash deploy/aliyun/flow-upload-build.sh
```

## Mode B: Build in Flow and push to ACR

This mode is prepared for:

```text
git push -> Aliyun Flow -> build images -> push ACR -> ECS docker compose deploy
```

## 1. Create ACR repository

Create one image repository in Aliyun Container Registry, for example:

```text
registry.cn-hangzhou.aliyuncs.com/your_namespace/newquant
```

The pipeline will push two tags into the same repository:

```text
backend-latest
frontend-latest
backend-${COMMIT_ID}
frontend-${COMMIT_ID}
```

## 2. Prepare ECS

Install Docker and Docker Compose plugin on ECS, then create the app directory:

```bash
mkdir -p /opt/newquant/data
```

Upload or create these files under `/opt/newquant`:

```text
docker-compose.prod.yml
deploy.sh
backend.env
.env.deploy
```

Use these repo files as templates:

```text
docker-compose.prod.yml
deploy/aliyun/deploy.sh
deploy/aliyun/backend.env.example
deploy/aliyun/env.deploy.example
```

On ECS, make the deploy script executable:

```bash
chmod +x /opt/newquant/deploy.sh
```

Or run the bootstrap script locally after SSH access works:

```bash
export ECS_HOST=your_ecs_public_ip
export ECS_USER=root
export ACR_REGISTRY=registry.cn-hangzhou.aliyuncs.com
export ACR_USERNAME=your_acr_username
export IMAGE_REGISTRY=registry.cn-hangzhou.aliyuncs.com/your_namespace/newquant

deploy/aliyun/bootstrap-ecs.sh
```

## 3. Configure Flow variables

Add these variables in Aliyun Flow:

```text
ACR_REGISTRY=registry.cn-hangzhou.aliyuncs.com
IMAGE_REGISTRY=registry.cn-hangzhou.aliyuncs.com/your_namespace/newquant
ACR_USERNAME=your_acr_username
ACR_PASSWORD=your_acr_password
ECS_HOST=your_ecs_public_ip
ECS_USER=root
```

Store SSH credentials with Flow host deployment credentials instead of hardcoding private keys.

## 4. Build stage

Use this command in the Flow build step:

```bash
bash deploy/aliyun/flow-build.sh
```

## 5. Deploy stage

Use Flow host deployment or SSH task to run on ECS:

```bash
bash /opt/newquant/deploy.sh
```

## 6. Trigger

Enable code source trigger or repository webhook in Flow.

Recommended rules:

```text
push master/main -> auto deploy
tag v* -> production deploy with manual approval
```
