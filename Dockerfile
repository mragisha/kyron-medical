# Step 1: Start from an official Python image
# "slim" = smaller image, no unnecessary OS packages
FROM python:3.11-slim

# Step 2: Set the working directory inside the container
# All subsequent commands run from /app inside the container
WORKDIR /app

# Step 3: Copy requirements first (before the rest of the code)
# This is a Docker caching trick: if requirements haven't changed,
# Docker reuses the cached layer and skips reinstalling packages
COPY requirements.txt .

# Step 4: Install all Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Step 5: Copy the entire project into the container
COPY . .

# Step 6: Tell Docker which port the app listens on (documentation only)
EXPOSE 8080

# Step 7: Start the app using uvicorn
# Cloud Run injects PORT=8080 as an environment variable
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
