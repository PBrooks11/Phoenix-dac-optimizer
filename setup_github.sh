#!/bin/bash
# setup_github.sh — Push Phoenix DAC Optimizer to GitHub for Streamlit Cloud deploy
# Usage: bash setup_github.sh YOUR_GITHUB_USERNAME
# Run from: /Users/preston/.bob/playground/dac_optimizer

set -e

USERNAME=${1:-"YOUR_GITHUB_USERNAME"}
REPO="phoenix-dac-optimizer"
DIR="$(cd "$(dirname "$0")" && pwd)"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Phoenix DAC — GitHub + Streamlit Cloud"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Step 1: Initialise git repo in $DIR"
cd "$DIR"
git init
git add .
git commit -m "Initial commit: Phoenix DAC Optimizer v1.0 — IBM AI Builders Challenge"

echo ""
echo "Step 2: Create GitHub repo and push"
echo "  → Go to https://github.com/new"
echo "  → Name: $REPO"
echo "  → Set to PUBLIC (required for Streamlit Cloud free tier)"
echo "  → Do NOT initialise with README (we have one)"
echo ""
read -p "Press Enter when the GitHub repo is created..."

git remote add origin "https://github.com/$USERNAME/$REPO.git"
git branch -M main
git push -u origin main

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Step 3: Deploy to Streamlit Community Cloud"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "  1. Go to: https://share.streamlit.io"
echo "  2. Sign in with your GitHub account"
echo "  3. Click 'New app'"
echo "  4. Repository: $USERNAME/$REPO"
echo "  5. Branch: main"
echo "  6. Main file path: app.py"
echo "  7. Click 'Deploy'"
echo ""
echo "  Your public URL will be:"
echo "  https://$REPO.streamlit.app"
echo ""
echo "  ✅ Update README.md and build_slides.py with your live URL"
echo "  ✅ Add the URL to your bemyapp.com project page"
echo ""
echo "Done! Total time: ~10 minutes"
