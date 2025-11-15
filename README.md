# Xiaohongshu-Batch-Downloader-Playwright-Python-Docker-Flask-API
This project is a complete automation pipeline to scrape, extract, and batch-download public Xiaohongshu (RED) video posts using a custom Playwright-based API, a Dockerized execution environment, and an optional n8n workflow for automation.


The system supports:
✔️ Batch downloading from a JSON list of Xiaohongshu post URLs
✔️ Automatic extraction of metadata (caption, username, post ID, media links)
✔️ Automatic video downloading
✔️ Robust error handling (timeout retries, invalid links, edge cases)
✔️ Fully containerized API using Docker
✔️ Optional integration with n8n workflows
✔️ Clean directory structure (downloads/, debug/, results/)
✔️ Human-readable logs & result reports


🚀 Project Architecture
xhs-batch
│── app_playwright_update.py   # Flask API with Playwright automation
│── xhs_batch_download.py      # Batch processing script
│── Dockerfile                 # Full environment containerization
│── links.json                 # List of Xiaohongshu post URLs
│── downloads/                 # Automatically downloaded media
│── results/                   # Results report containing metadata
│── debug/                     # Screenshots, HTML dumps for failed runs


🔧 Tech Stack
Python 3.12
Playwright (Chromium)
Flask REST API
Docker & Docker Desktop
PowerShell + Bash scripting
n8n workflow automation (optional)


📦 Running the API in Docker

1. Build the container
docker build -t xhs-playwright-api:latest .

2. Run the API
docker run -d -p 6000:6000 -v "${PWD}:/work" --name xhs-playwright-api xhs-playwright-api:latest

3. Test the /extract API
Send a POST request:
POST http://localhost:6000/extract
{
  "url": "https://www.xiaohongshu.com/explore/<post-id>"
}

📥 Batch Download Mode
Place URLs inside links.json:
[
  "https://www.xiaohongshu.com/explore/123",
  "https://www.xiaohongshu.com/explore/456"
]


Run the batch processor:
docker exec -it xhs-playwright-api python /work/xhs_batch_download.py /work/links.json


Outputs will be saved in:
downloads/
results/results.json
debug/


⚙️ Optional: n8n Integration
A ready-to-use n8n workflow can trigger:
API extraction
Batch download
Automated social media reposting
Automated cloud upload (S3/Drive/etc.)
Scheduling (cron-based automation)
