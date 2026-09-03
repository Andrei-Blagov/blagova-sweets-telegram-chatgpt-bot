# Build and push image to Docker Hub (local alternative to GitHub Actions).
# Usage: .\scripts\build-and-push.ps1
# Optional: .\scripts\build-and-push.ps1 -Tag "v1.0.0"

param(
    [string]$Tag = "latest",
    [string]$Image = "andreiblagov/telegram-chatgpt-bot"
)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

Write-Host "Building $Image`:$Tag ..."
docker build -t "${Image}:${Tag}" .

if ($Tag -ne "latest") {
    docker tag "${Image}:${Tag}" "${Image}:latest"
}

Write-Host "Pushing ${Image}:${Tag} ..."
docker push "${Image}:${Tag}"

if ($Tag -ne "latest") {
    Write-Host "Pushing ${Image}:latest ..."
    docker push "${Image}:latest"
}

Write-Host "Done: ${Image}:${Tag}"
